import httpx
import pytest
from pydantic import ValidationError

from app.executor import _evaluate_explorer, determine_verdict
from app.models import (
    ExplorerAssertion,
    ExplorerExperimentSpec,
    ExperimentEvidence,
    ExperimentId,
    SideMeasurement,
    Verdict,
)


def _spec(**overrides):
    base = dict(
        name="valid-probe",
        rationale="rationale text",
        hypothesis="hypothesis text",
        assertions=[ExplorerAssertion.STATUS_MATCH],
    )
    base.update(overrides)
    return base


def _side(body, status=200):
    return SideMeasurement(
        success=200 <= status < 400,
        trials_completed=3,
        warmups_completed=0,
        requests=3,
        error_rate=0 if status < 400 else 1,
        p95_latency_ms=10,
        response_status=status,
        response_sample=body,
    )


def test_explorer_fixed_operators_find_schema_difference():
    spec = ExplorerExperimentSpec(
        name="generated-schema-probe",
        rationale="Exercise a generated boundary input.",
        hypothesis="The candidate may change its response shape.",
        assertions=[
            ExplorerAssertion.CANDIDATE_SUCCESS,
            ExplorerAssertion.STATUS_MATCH,
            ExplorerAssertion.RESPONSE_SHAPE_MATCH,
            ExplorerAssertion.RESPONSE_TYPES_MATCH,
        ],
    )
    passed, explanation, thresholds = _evaluate_explorer(
        spec,
        _side({"total": 10}),
        _side({"amount": "10"}),
    )
    assert passed is False
    assert "shape" in explanation
    assert thresholds["decision"] == "review_only"


def test_explorer_finding_cannot_block_release():
    spec = ExplorerExperimentSpec(
        name="generated-review-probe",
        rationale="Look beyond the allowlisted catalog.",
        hypothesis="The candidate may differ.",
        assertions=[ExplorerAssertion.STATUS_MATCH],
    )
    evidence = ExperimentEvidence(
        experiment_id=ExperimentId.AI_EXPLORER,
        title="AI Explorer",
        blocking=False,
        stable=_side({"ok": True}),
        candidate=_side({"ok": False}),
        passed=False,
        explanation="Human review required.",
        review_only=True,
        exploratory_spec=spec,
    )
    verdict, _ = determine_verdict([evidence])
    assert verdict == Verdict.PASS


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"name": 'import os; os.system("rm -rf /")'}, "executable code as a name"),
        ({"name": "../../etc/passwd"}, "path traversal"),
        ({"assertions": ["exec_shell"]}, "an operator outside the fixed set"),
        ({"assertions": []}, "no assertions at all"),
        ({"query_parameters": {str(i): "v" for i in range(20)}}, "unbounded parameters"),
        ({"query_parameters": {"k": "v" * 5000}}, "an oversized parameter value"),
        ({"target_url": "http://169.254.169.254/"}, "an invented target field"),
        ({"headers": {"Authorization": "Bearer x"}}, "invented headers"),
    ],
)
def test_dsl_rejects_specs_outside_the_contract(overrides, reason):
    """A spec the model should never be able to get executed, whatever it emits."""
    with pytest.raises(ValidationError):
        ExplorerExperimentSpec(**_spec(**overrides))


def test_generated_parameters_cannot_alter_the_target():
    """Probe values are data. They must not reach the host, path, or headers."""
    target = "http://stable.internal:8080/api/v1/quote"
    hostile = {
        "a": "../../admin",
        "b": "http://169.254.169.254/latest/meta-data/",
        "c": "x\r\nX-Injected: 1",
    }
    request = httpx.Request("GET", target, params=hostile)

    assert request.url.host == "stable.internal"
    assert request.url.path == "/api/v1/quote"
    assert "\r" not in str(request.url) and "\n" not in str(request.url)
    assert not any("Injected" in name for name in request.headers)


@pytest.mark.asyncio
async def test_guarded_mode_finds_nothing_where_explorer_does():
    """The case that justifies explorer mode existing.

    The candidate misrounds zero-decimal currencies. No catalog experiment
    varies the currency, so guarded mode compares identical responses and
    legitimately passes. Explorer authors a probe that asks for JPY and finds
    the difference — without being able to change the verdict.
    """
    from app.executor import execute_plan, determine_verdict
    from app.models import AnalysisMode, Verdict
    from app.planner import build_plan
    from app.scenarios import SCENARIO_PROFILES

    base = SCENARIO_PROFILES["currency-rounding"]["summary"].suggested_change

    async def analyse(mode):
        change = base.model_copy(update={"analysis_mode": mode})
        plan = build_plan(change)
        evidence = await execute_plan(change, plan)
        verdict, _ = determine_verdict(evidence)
        return plan, evidence, verdict

    guarded_plan, guarded_evidence, guarded_verdict = await analyse(AnalysisMode.GUARDED)
    assert guarded_verdict == Verdict.PASS
    assert guarded_plan.exploratory_experiments == []
    assert not any(item.experiment_id == ExperimentId.AI_EXPLORER for item in guarded_evidence)
    assert all(item.passed is not False for item in guarded_evidence)

    explorer_plan, explorer_evidence, explorer_verdict = await analyse(AnalysisMode.EXPLORER)
    spec = explorer_plan.exploratory_experiments[0]
    assert spec.query_parameters.get("currency") == "JPY"

    probe = next(item for item in explorer_evidence if item.experiment_id == ExperimentId.AI_EXPLORER)
    assert probe.passed is False
    assert "total" in probe.explanation
    assert probe.review_only is True and probe.blocking is False

    # The generated finding is surfaced for review, never promoted to a verdict.
    assert explorer_verdict == Verdict.PASS


def test_model_cannot_opt_out_of_mandatory_availability_checks():
    spec = ExplorerExperimentSpec(
        name="generated-minimal-probe",
        rationale="Ask for only a shape comparison.",
        hypothesis="The shape might differ.",
        assertions=[ExplorerAssertion.RESPONSE_SHAPE_MATCH],
    )
    passed, explanation, thresholds = _evaluate_explorer(
        spec,
        _side({"ok": True}),
        _side({"ok": True}, status=500),
    )
    assert passed is False
    assert "did not respond successfully" in explanation
    assert thresholds["mandatory_assertions"] == "candidate_success,status_match"
