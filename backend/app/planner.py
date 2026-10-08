from __future__ import annotations

import json
import os

from .catalog import ADAPTIVE_IDS, BASELINE_IDS
from .models import ChangeInput, ExperimentId, ExperimentPlan, PlannedExperiment


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
            "task": "Select at most two bounded experiments for this release change.",
            "rules": [
                "Select only from: " + ", ".join(item.value for item in ADAPTIVE_IDS),
                "Do not choose health_check or api_smoke; the runner always executes them.",
                "Every choice needs a falsifiable hypothesis tied to the supplied diff.",
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
