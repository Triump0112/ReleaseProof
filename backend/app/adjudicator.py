"""Reconcile observed behavioural change against declared intent.

Shape-based checks answer "is the candidate still well-formed?". They cannot
answer "did this change do what its author said, and nothing else?" — a
candidate can keep every field, type and status code while silently altering a
value the diff never mentions.

This module closes that gap in three stages, and the split matters:

1. ``response_deltas`` deterministically enumerates every field-level
   difference between the stable and candidate responses. No model involved,
   so the evidence is reproducible and auditable.
2. ``classify_deltas`` asks Gemini to label each delta as explained by the
   diff, benign non-determinism, or unexplained. This is the one judgement
   that genuinely requires language understanding: only the diff and its
   description say which effects were intended.
3. ``adjudicate`` applies a fixed rule over those labels.

The trust boundary from the rest of the system is preserved. Gemini classifies
and must cite evidence; it never sets a threshold and never emits the verdict.
A classification it declines to justify is treated as unexplained, so the
failure mode is a blocked release rather than a silently shipped regression.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .models import (
    Adjudication,
    ChangeInput,
    DeltaLabel,
    DeltaClassification,
    ResponseDelta,
)


# Field names whose values are expected to differ between any two responses,
# including two calls to the same revision. Used only by the offline fallback;
# the model is given the raw deltas and reaches its own conclusion.
_NOISE_NAME_PATTERN = re.compile(
    r"(^|_)(id|uuid|guid|trace|span|request|correlation|nonce|etag|token|session)($|_)"
    r"|(^|_)(timestamp|time|date|at|ms|duration|elapsed|latency|seconds|epoch)($|_)",
    re.IGNORECASE,
)

MAX_DELTAS = 40


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a JSON body to dotted paths so differences are addressable."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        # Index positionally; reordering shows up as value deltas, which the
        # classifier can still recognise as benign when the diff implies it.
        for index, item in enumerate(value):
            flat.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        flat[prefix or "$"] = value
    return flat


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def response_deltas(stable: Any, candidate: Any) -> list[ResponseDelta]:
    """Enumerate field-level differences. Deterministic and model-free."""
    if stable is None and candidate is None:
        return []
    stable_flat = _flatten(stable) if stable is not None else {}
    candidate_flat = _flatten(candidate) if candidate is not None else {}

    deltas: list[ResponseDelta] = []
    for path in sorted(set(stable_flat) | set(candidate_flat)):
        in_stable, in_candidate = path in stable_flat, path in candidate_flat
        stable_value = stable_flat.get(path)
        candidate_value = candidate_flat.get(path)

        if in_stable and not in_candidate:
            kind = "field_removed"
        elif in_candidate and not in_stable:
            kind = "field_added"
        elif _type_name(stable_value) != _type_name(candidate_value):
            kind = "type_changed"
        elif stable_value != candidate_value:
            kind = "value_changed"
        else:
            continue

        deltas.append(
            ResponseDelta(
                path=path,
                kind=kind,
                stable_value=_truncate(stable_value),
                candidate_value=_truncate(candidate_value),
                stable_type=_type_name(stable_value) if in_stable else None,
                candidate_type=_type_name(candidate_value) if in_candidate else None,
            )
        )
    return deltas[:MAX_DELTAS]


def _truncate(value: Any, limit: int = 120) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fallback_classification(change: ChangeInput, deltas: list[ResponseDelta]) -> list[DeltaClassification]:
    """Offline classifier used when Vertex is disabled or unreachable.

    Deliberately conservative: it recognises only well-known non-deterministic
    field names as noise and whether a leaf name is literally mentioned in the
    diff. Everything else stays unexplained, so disabling the model can never
    turn a blocking regression into a pass.
    """
    text = f"{change.summary}\n{change.diff}".lower()
    results: list[DeltaClassification] = []
    for delta in deltas:
        leaf = delta.path.split(".")[-1].split("[")[0]
        if _NOISE_NAME_PATTERN.search(leaf) and delta.kind == "value_changed":
            results.append(
                DeltaClassification(
                    path=delta.path,
                    label=DeltaLabel.BENIGN_NOISE,
                    rationale=f"'{leaf}' is a conventionally non-deterministic field name.",
                    diff_evidence=None,
                )
            )
        elif leaf.lower() in text:
            results.append(
                DeltaClassification(
                    path=delta.path,
                    label=DeltaLabel.EXPLAINED,
                    rationale=f"'{leaf}' is named in the supplied change text.",
                    diff_evidence=leaf,
                )
            )
        else:
            results.append(
                DeltaClassification(
                    path=delta.path,
                    label=DeltaLabel.UNEXPLAINED,
                    rationale=f"'{leaf}' changed but is not referenced by the change description or diff.",
                    diff_evidence=None,
                )
            )
    return results


def classify_deltas(change: ChangeInput, deltas: list[ResponseDelta]) -> tuple[list[DeltaClassification], str, str | None]:
    """Label each delta. Returns (classifications, classifier_name, note)."""
    if not deltas:
        return [], "none_required", None

    if os.getenv("RELEASEPROOF_USE_VERTEX", "false").lower() != "true":
        return (
            _fallback_classification(change, deltas),
            "deterministic_fallback",
            "Vertex adjudicator disabled; conservative local classifier used.",
        )

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        return (
            _fallback_classification(change, deltas),
            "deterministic_fallback",
            "GOOGLE_CLOUD_PROJECT is missing; conservative local classifier used.",
        )

    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel

        class _ClassificationList(BaseModel):
            classifications: list[DeltaClassification]

        client = genai.Client(
            vertexai=True,
            project=project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
        prompt = {
            "task": (
                "A release candidate was compared against the current stable revision using "
                "identical requests. Decide, for each observed response difference, whether "
                "the supplied change actually accounts for it."
            ),
            "labels": {
                "explained": "The diff or summary directly accounts for this difference.",
                "benign_noise": (
                    "The field is inherently non-deterministic (identifiers, timestamps, "
                    "durations) and would differ between two calls to the same revision."
                ),
                "unexplained": (
                    "A real behavioural difference that nothing in the change accounts for. "
                    "Use this whenever you are not confident the change explains it."
                ),
            },
            "rules": [
                "Return exactly one classification per supplied delta path.",
                "For 'explained', diff_evidence must quote the specific diff line or phrase.",
                "If you cannot quote supporting evidence, the label must be 'unexplained'.",
                "Do not assume a change is safe because it looks reasonable or intentional.",
                "Judge only what the supplied change text actually says.",
            ],
            "change": {
                "service": change.service_name,
                "summary": change.summary,
                "diff": change.diff,
            },
            "deltas": [delta.model_dump(mode="json") for delta in deltas],
        }
        response = client.models.generate_content(
            model=os.getenv("RELEASEPROOF_GEMINI_MODEL", "gemini-2.5-flash"),
            contents=json.dumps(prompt),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_ClassificationList,
                temperature=0.0,
            ),
        )
        parsed = _ClassificationList.model_validate_json(response.text)
        return _reconcile(deltas, parsed.classifications), "vertex_gemini", None
    except Exception as exc:
        return (
            _fallback_classification(change, deltas),
            "deterministic_fallback",
            f"Vertex adjudicator failed ({type(exc).__name__}); conservative local classifier used.",
        )


def _reconcile(
    deltas: list[ResponseDelta], classifications: list[DeltaClassification]
) -> list[DeltaClassification]:
    """Force exactly one classification per observed delta.

    The model cannot drop an inconvenient delta, invent a path that was never
    measured, or mark something explained without quoting evidence. Anything
    missing or unsupported falls back to 'unexplained'.
    """
    by_path = {item.path: item for item in classifications}
    reconciled: list[DeltaClassification] = []
    for delta in deltas:
        item = by_path.get(delta.path)
        if item is None:
            reconciled.append(
                DeltaClassification(
                    path=delta.path,
                    label=DeltaLabel.UNEXPLAINED,
                    rationale="The planner returned no classification for this measured difference.",
                    diff_evidence=None,
                )
            )
            continue
        if item.label == DeltaLabel.EXPLAINED and not (item.diff_evidence or "").strip():
            reconciled.append(
                DeltaClassification(
                    path=delta.path,
                    label=DeltaLabel.UNEXPLAINED,
                    rationale="Marked explained without citing supporting diff evidence.",
                    diff_evidence=None,
                )
            )
            continue
        reconciled.append(item)
    return reconciled


def adjudicate(change: ChangeInput, stable_body: Any, candidate_body: Any) -> Adjudication:
    """Full reconciliation: measure deltas, classify them, apply fixed policy."""
    deltas = response_deltas(stable_body, candidate_body)
    classifications, classifier, note = classify_deltas(change, deltas)

    unexplained = [item for item in classifications if item.label == DeltaLabel.UNEXPLAINED]
    # Fixed policy, owned entirely by this function: any behavioural difference
    # the change does not account for blocks the release.
    if unexplained:
        summary = "Candidate changed behaviour the supplied change does not account for: " + ", ".join(
            f"{item.path} ({item.rationale})" for item in unexplained[:3]
        )
    elif deltas:
        summary = f"All {len(deltas)} observed difference(s) are accounted for by the change or are known non-determinism."
    else:
        summary = "Stable and candidate responses were identical."

    return Adjudication(
        deltas=deltas,
        classifications=classifications,
        unexplained_paths=[item.path for item in unexplained],
        passed=not unexplained,
        summary=summary,
        classifier=classifier,
        classifier_note=note,
    )
