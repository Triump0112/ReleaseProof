"""The model's response is repaired, not trusted — and not discarded either.

Vertex returns JSON shaped by a schema that cannot express the DSL's cross-field
rules, so a strict parse rejected usable plans and silently demoted every run to
the offline fallback. These tests pin the repair behaviour, and pin that repair
never widens what a generated probe is allowed to do.
"""

from __future__ import annotations

import json

import pytest

from app.models import AnalysisMode, ExperimentId, ExplorerAssertion
from app.planner import _PlannerResponse, _coerce_plan, _enforce_bounds
from app.scenarios import SCENARIO_PROFILES


def _plan(payload: dict, mode: AnalysisMode = AnalysisMode.EXPLORER):
    change = SCENARIO_PROFILES["currency-rounding"]["summary"].suggested_change.model_copy(
        update={"analysis_mode": mode}
    )
    raw = _PlannerResponse.model_validate_json(json.dumps(payload))
    return _enforce_bounds(_coerce_plan(raw, change), change)


def test_server_owned_fields_are_never_taken_from_the_model():
    """planner, baselines and mode are the server's to set, not the model's."""
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "adaptive_experiments": [{"experiment_id": "bounded_load", "reason": "r", "hypothesis": "h"}],
    })
    assert plan.planner == "vertex_gemini"
    assert plan.baseline_experiments == [ExperimentId.HEALTH, ExperimentId.SMOKE]
    assert plan.analysis_mode == AnalysisMode.EXPLORER


def test_a_name_outside_the_dsl_pattern_is_slugified_not_rejected():
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "exploratory_experiments": [{
            "name": "Zero Decimal Currency Probe!!", "rationale": "JPY has no minor unit",
            "hypothesis": "JPY differs", "query_parameters": {"currency": "JPY"},
            "assertions": ["candidate_success"], "compare_response_paths": ["total"],
        }],
    })
    spec = plan.exploratory_experiments[0]
    assert spec.name == "zero-decimal-currency-probe"
    assert spec.query_parameters == {"currency": "JPY"}


def test_cross_field_rules_are_satisfied_rather_than_rejected():
    """compare_paths is implied by the paths, and dangling operators are dropped."""
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "exploratory_experiments": [{
            "name": "probe", "rationale": "r", "hypothesis": "h",
            "assertions": ["candidate_success"], "compare_response_paths": ["total"],
        }],
    })
    assert ExplorerAssertion.COMPARE_PATHS in plan.exploratory_experiments[0].assertions

    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "exploratory_experiments": [{
            "name": "probe", "rationale": "r", "hypothesis": "h",
            "assertions": ["required_paths_present"], "required_response_paths": [],
        }],
    })
    assert ExplorerAssertion.REQUIRED_PATHS_PRESENT not in plan.exploratory_experiments[0].assertions


@pytest.mark.parametrize("operator", ["exec_shell", "run_code", "fetch_url", ""])
def test_repair_drops_invented_operators_and_never_invents_one(operator):
    """Leniency must not become a way to smuggle capability into the DSL."""
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "exploratory_experiments": [{
            "name": "probe", "rationale": "r", "hypothesis": "h", "assertions": [operator],
        }],
    })
    assertions = plan.exploratory_experiments[0].assertions
    assert all(isinstance(item, ExplorerAssertion) for item in assertions)
    # Falls back to the mandatory pair rather than to anything broader.
    assert set(assertions) == {ExplorerAssertion.CANDIDATE_SUCCESS, ExplorerAssertion.STATUS_MATCH}


def test_an_experiment_outside_the_catalog_is_dropped():
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "adaptive_experiments": [
            {"experiment_id": "run_shell", "reason": "r", "hypothesis": "h"},
            {"experiment_id": "bounded_load", "reason": "r", "hypothesis": "h"},
        ],
    })
    assert [item.experiment_id for item in plan.adaptive_experiments] == [ExperimentId.LOAD]


def test_guarded_mode_discards_generated_probes_from_the_response():
    """Even if the model authors probes, guarded mode must not run them."""
    plan = _plan({
        "detected_change": "x", "risk_summary": "y",
        "exploratory_experiments": [{
            "name": "probe", "rationale": "r", "hypothesis": "h",
            "assertions": ["candidate_success"], "query_parameters": {"currency": "JPY"},
        }],
    }, mode=AnalysisMode.GUARDED)
    assert plan.exploratory_experiments == []


def test_oversized_values_are_clamped_to_the_dsl_limits():
    plan = _plan({
        "detected_change": "d" * 5000, "risk_summary": "r" * 5000,
        "exploratory_experiments": [{
            "name": "probe", "rationale": "x" * 5000, "hypothesis": "y" * 5000,
            "query_parameters": {"k" * 500: "v" * 5000},
            "assertions": ["candidate_success"],
        }],
    })
    spec = plan.exploratory_experiments[0]
    assert len(plan.detected_change) <= 500
    assert len(plan.risk_summary) <= 1000
    assert len(spec.rationale) <= 500
    assert all(len(k) <= 80 and len(v) <= 500 for k, v in spec.query_parameters.items())
