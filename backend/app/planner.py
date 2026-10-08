from __future__ import annotations

import json
import os

from .catalog import ADAPTIVE_IDS, BASELINE_IDS
from .models import (
    AnalysisMode,
    ChangeInput,
    ExplorerAssertion,
    ExplorerExperimentSpec,
    ExperimentId,
    ExperimentPlan,
    PlannedExperiment,
)


def _fallback_explorer_specs(change: ChangeInput) -> list[ExplorerExperimentSpec]:
    """Offline stand-in for Gemini's probe authoring.

    This is a keyword heuristic, not reasoning: it recognises a few domain
    signatures and emits the matching probe. Gemini infers the interesting
    input from the diff itself. The fallback exists so the gate keeps working
    without Vertex, and the UI labels which one produced the spec.
    """
    if change.analysis_mode != AnalysisMode.EXPLORER or not change.budget.max_exploratory_experiments:
        return []
    text = f"{change.summary}\n{change.diff}".lower()

    baseline_assertions = [
        ExplorerAssertion.CANDIDATE_SUCCESS,
        ExplorerAssertion.STATUS_MATCH,
        ExplorerAssertion.RESPONSE_SHAPE_MATCH,
        ExplorerAssertion.RESPONSE_TYPES_MATCH,
        ExplorerAssertion.LATENCY_WITHIN_POLICY,
    ]

    # Money handling that mentions rounding or decimal places is only wrong for
    # currencies without a minor unit. No catalog experiment varies `currency`,
    # so the default-currency request every fixed probe sends cannot reach it.
    money_signature = ("round", "decimal", "minor unit", "minor_unit", "exponent", "money", "currency")
    if any(word in text for word in money_signature):
        return [
            ExplorerExperimentSpec(
                name="generated-zero-decimal-currency-probe",
                rationale=(
                    "Rounding behaviour was changed, and every catalog experiment sends the default "
                    "currency. A zero-decimal currency is the input that separates the two revisions."
                ),
                hypothesis=(
                    "If the candidate assumes two decimal places, a zero-decimal currency such as JPY "
                    "will produce a different total from the stable revision."
                ),
                query_parameters={"currency": "JPY"},
                assertions=[*baseline_assertions, ExplorerAssertion.COMPARE_PATHS],
                compare_response_paths=["total", "currency"],
            )
        ][: change.budget.max_exploratory_experiments]

    if any(word in text for word in ("total", "amount", "tax", "discount", "price")):
        return [
            ExplorerExperimentSpec(
                name="generated-pricing-invariant-probe",
                rationale="The guarded catalog cannot anticipate every input interaction, so Explorer adds a constrained differential probe.",
                hypothesis="A generated boundary probe may expose an undeclared pricing or response invariant change.",
                query_parameters={"releaseproof_explorer": "boundary"},
                assertions=[*baseline_assertions, ExplorerAssertion.COMPARE_PATHS],
                compare_response_paths=["currency"],
            )
        ][: change.budget.max_exploratory_experiments]

    return [
        ExplorerExperimentSpec(
            name="generated-boundary-probe",
            rationale="The guarded catalog cannot anticipate every input interaction, so Explorer adds a constrained differential probe.",
            hypothesis="A boundary-flavoured request may reveal behaviour that the normal smoke request does not exercise.",
            query_parameters={"releaseproof_explorer": "boundary"},
            assertions=baseline_assertions,
        )
    ][: change.budget.max_exploratory_experiments]


def _fallback_plan(change: ChangeInput, note: str | None = None) -> ExperimentPlan:
    text = f"{change.summary}\n{change.diff}".lower()
    selected: list[tuple[ExperimentId, str, str]] = []

    rules = [
        (
            ("concurr", "replica", "cpu", "memory", "latency", "timeout"),
            ExperimentId.LOAD,
            "Runtime or scaling configuration changed.",
            "The candidate may regress tail latency or error rate under bounded concurrency.",
        ),
        (
            ("field", "schema", "response", "rename", "endpoint", "contract", "amount", "total"),
            ExperimentId.CONTRACT,
            "The API shape may have changed.",
            "Existing clients may receive missing fields or incompatible value types.",
        ),
        (
            ("payload", "body size", "upload", "limit"),
            ExperimentId.PAYLOAD,
            "Payload handling or limits changed.",
            "Near-limit payloads may fail or become disproportionately slow.",
        ),
        (
            ("retry", "idempoten", "duplicate", "payment", "side effect"),
            ExperimentId.IDEMPOTENCY,
            "Retry or side-effect logic changed.",
            "A repeated request may create duplicate effects.",
        ),
        (
            ("dependency", "upstream", "downstream", "client timeout"),
            ExperimentId.TIMEOUT,
            "Dependency interaction changed.",
            "A slow dependency may exhaust the candidate timeout budget.",
        ),
    ]
    for keywords, experiment_id, reason, hypothesis in rules:
        if any(keyword in text for keyword in keywords) and all(item[0] != experiment_id for item in selected):
            selected.append((experiment_id, reason, hypothesis))
        if len(selected) >= change.budget.max_adaptive_experiments:
            break

    selected = selected[: change.budget.max_adaptive_experiments]

    if not selected and change.budget.max_adaptive_experiments:
        selected.append(
            (
                ExperimentId.EDGE,
                "No specialised risk signature was detected, so boundary behaviour is the most informative bounded probe.",
                "The refactor may change behaviour for empty, Unicode or boundary inputs.",
            )
        )

    detected_change = change.summary.strip()
    return ExperimentPlan(
        detected_change=detected_change,
        risk_summary="; ".join(item[2] for item in selected) or "Only baseline availability and smoke behaviour will be checked.",
        baseline_experiments=list(BASELINE_IDS),
        adaptive_experiments=[
            PlannedExperiment(experiment_id=item[0], reason=item[1], hypothesis=item[2]) for item in selected
        ],
        exploratory_experiments=_fallback_explorer_specs(change),
        analysis_mode=change.analysis_mode,
        planner="deterministic_fallback",
        planner_note=note,
    )


def _enforce_bounds(plan: ExperimentPlan, change: ChangeInput) -> ExperimentPlan:
    plan.baseline_experiments = list(BASELINE_IDS)
    allowed = set(ADAPTIVE_IDS)
    seen: set[ExperimentId] = set()
    bounded: list[PlannedExperiment] = []
    for experiment in plan.adaptive_experiments:
        if experiment.experiment_id in allowed and experiment.experiment_id not in seen:
            seen.add(experiment.experiment_id)
            bounded.append(experiment)
        if len(bounded) >= change.budget.max_adaptive_experiments:
            break
    plan.adaptive_experiments = bounded
    plan.analysis_mode = change.analysis_mode
    if change.analysis_mode == AnalysisMode.EXPLORER:
        plan.exploratory_experiments = plan.exploratory_experiments[
            : change.budget.max_exploratory_experiments
        ]
    else:
        plan.exploratory_experiments = []
    return plan


def build_plan(change: ChangeInput) -> ExperimentPlan:
    if os.getenv("RELEASEPROOF_USE_VERTEX", "false").lower() != "true":
        return _fallback_plan(change, "Vertex planner disabled; deterministic local planner used.")

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    model = os.getenv("RELEASEPROOF_GEMINI_MODEL", "gemini-2.5-flash")
    if not project:
        return _fallback_plan(change, "GOOGLE_CLOUD_PROJECT is missing; deterministic fallback used.")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=project, location=location)
        prompt = {
            "task": (
                "Select bounded catalog experiments and, only in explorer mode, author constrained declarative probes."
            ),
            "rules": [
                "Select only from: " + ", ".join(item.value for item in ADAPTIVE_IDS),
                "Do not choose health_check or api_smoke; the runner always executes them.",
                "Every choice needs a falsifiable hypothesis tied to the supplied diff.",
                "In guarded mode exploratory_experiments must be empty.",
                "In explorer mode author at most the requested number of exploratory experiments.",
                "Explorer probes are GET-only against the supplied request path; you may provide query parameters only.",
                "Use only the fixed assertion operators in the schema. Never produce source code, shell commands, URLs, headers, or credentials.",
                "Explorer findings require review and never decide the release verdict.",
                # The catalog probes all send the endpoint's default inputs, so a
                # probe that repeats them is wasted. Value comes only from an
                # input the fixed experiments never try.
                "An explorer probe is only worth running if it sends an input the fixed catalog never sends. "
                "The catalog issues the endpoint's default request and varies only its own reserved parameter "
                "names, so repeating the default request adds nothing.",
                "Read the diff for the input dimension whose behaviour it changed, then choose the specific value "
                "in that dimension most likely to separate the two revisions — a boundary case, an unusual but "
                "valid enum member, or a value where the old and new logic must disagree.",
                "Put the paths whose values should be identical across revisions in compare_response_paths.",
                "Return only JSON matching the response schema.",
            ],
            "change": change.model_dump(mode="json"),
        }
        response = client.models.generate_content(
            model=model,
            contents=json.dumps(prompt),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExperimentPlan,
                temperature=0.1,
            ),
        )
        plan = ExperimentPlan.model_validate_json(response.text)
        plan.planner = "vertex_gemini"
        plan.planner_note = None
        return _enforce_bounds(plan, change)
    except Exception as exc:
        # Planning must never stop the deterministic release gate from operating.
        return _fallback_plan(change, f"Vertex planner failed ({type(exc).__name__}); deterministic fallback used.")
