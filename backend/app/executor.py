from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import socket
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .adjudicator import adjudicate
from .catalog import CATALOG
from .models import (
    ChangeInput,
    ExplorerAssertion,
    ExplorerExperimentSpec,
    ExperimentEvidence,
    ExperimentId,
    ExperimentPlan,
    SideMeasurement,
    Verdict,
)
from .scenarios import scenario_results


LATENCY_REGRESSION_LIMIT = 0.30
ERROR_RATE_INCREASE_LIMIT = 0.02
LIVE_REQUEST_CAP = 300

# Below this many timed requests per side, a 95th percentile is dominated by
# the slowest one or two samples. The delta is still measured and reported, but
# it is not strong enough evidence to block a release on, so the latency policy
# stands down rather than blocking on noise.
MIN_LATENCY_SAMPLES = 20


def _requests_per_trial(experiment_id: "ExperimentId") -> int:
    """Timed requests per trial, purely to size the sample."""
    return 10 if experiment_id == ExperimentId.LOAD else 7


def _probe_concurrency(experiment_id: "ExperimentId") -> int:
    """How many of those requests are in flight at once.

    Only the load experiment overlaps them, because contention is the thing it
    measures. Every other experiment stays strictly sequential: collecting more
    samples must not quietly turn the smoke baseline into a load test, which is
    what makes it blind to contention in the first place.
    """
    return 10 if experiment_id == ExperimentId.LOAD else 1


MISSING = object()


def _p95(values: list[float]) -> float | None:
    """Linearly interpolated 95th percentile.

    The previous nearest-rank form returned the maximum for any sample under
    twenty, so a three-trial run reported its slowest request as a "p95". That
    is not a percentile, and a release policy should not be stated in terms of
    one that cannot be computed from the evidence collected.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = 0.95 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def _response_signature(value: Any, prefix: str = "$") -> dict[str, str]:
    """Return a deterministic shape/type signature for nested JSON."""
    signature = {prefix: _json_type(value)}
    if isinstance(value, dict):
        for key in sorted(value):
            signature.update(_response_signature(value[key], f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            signature.update(_response_signature(item, f"{prefix}[{index}]"))
    return signature


def _response_value(body: Any, path: str) -> Any:
    """Resolve a conservative dot path; list traversal is intentionally unsupported."""
    current = body
    for segment in path.removeprefix("$.").split("."):
        if not segment or not isinstance(current, dict) or segment not in current:
            return MISSING
        current = current[segment]
    return current


def _side_from_profile(raw: dict[str, Any], warmups: int, trials: int) -> SideMeasurement:
    requests = int(raw.get("requests", trials))
    errors = int(raw.get("errors", 0))
    latencies = [float(value) for value in raw.get("latencies", [])]
    return SideMeasurement(
        success=200 <= int(raw.get("status", 0)) < 400 and errors / max(requests, 1) <= ERROR_RATE_INCREASE_LIMIT,
        trials_completed=trials,
        warmups_completed=warmups,
        requests=requests,
        error_rate=round(errors / max(requests, 1), 4),
        p95_latency_ms=_p95(latencies),
        latency_samples=len(latencies),
        response_status=int(raw.get("status", 0)),
        response_sample=raw.get("body"),
    )


def _contract_issues(candidate_body: Any, change: ChangeInput) -> list[str]:
    if not change.expected_contract or not change.expected_contract.required_fields:
        return []
    if not isinstance(candidate_body, dict):
        return ["Candidate response is not a JSON object."]
    issues: list[str] = []
    for field, expected_type in change.expected_contract.required_fields.items():
        if field not in candidate_body:
            issues.append(f"Required field '{field}' is missing.")
            continue
        actual = _json_type(candidate_body[field])
        compatible = actual == expected_type or (expected_type == "number" and actual == "integer")
        if not compatible:
            issues.append(f"Field '{field}' expected {expected_type}, received {actual}.")
    return issues


def _evaluate(
    experiment_id: ExperimentId,
    stable: SideMeasurement,
    candidate: SideMeasurement,
    change: ChangeInput,
) -> tuple[bool | None, str, dict[str, float | int | str]]:
    if stable.trials_completed < change.budget.trials or candidate.trials_completed < change.budget.trials:
        return None, "Not enough repeated trials completed for a reliable comparison.", {"required_trials": change.budget.trials}
    if not stable.success:
        return None, "Stable revision failed; candidate comparison is not a valid release signal.", {}
    if not candidate.success:
        return False, "Candidate produced unsuccessful responses or excessive errors.", {}

    if experiment_id == ExperimentId.CONTRACT:
        issues = _contract_issues(candidate.response_sample, change)
        if issues:
            return False, " ".join(issues), {"policy": "required fields and types must be preserved"}
        if isinstance(stable.response_sample, dict) and isinstance(candidate.response_sample, dict):
            removed = sorted(set(stable.response_sample) - set(candidate.response_sample))
            if removed:
                return False, f"Candidate removed stable response fields: {', '.join(removed)}.", {"policy": "no removed stable fields"}

    stable_latency = stable.p95_latency_ms
    candidate_latency = candidate.p95_latency_ms
    samples = min(stable.latency_samples, candidate.latency_samples)
    if stable_latency and candidate_latency and samples >= MIN_LATENCY_SAMPLES:
        regression = (candidate_latency - stable_latency) / stable_latency
        if regression > LATENCY_REGRESSION_LIMIT:
            return False, (
                f"Candidate p95 latency regressed by {regression:.1%} "
                f"over {samples} timed requests per revision."
            ), {
                "max_p95_regression": LATENCY_REGRESSION_LIMIT,
                "latency_samples_per_side": samples,
            }

    stable_errors = stable.error_rate or 0.0
    candidate_errors = candidate.error_rate or 0.0
    if candidate_errors - stable_errors > ERROR_RATE_INCREASE_LIMIT:
        return False, "Candidate error-rate increase exceeded the allowed bound.", {"max_error_rate_increase": ERROR_RATE_INCREASE_LIMIT}

    return True, "Candidate remained within deterministic compatibility, error and latency policies.", {
        "max_p95_regression": LATENCY_REGRESSION_LIMIT,
        "max_error_rate_increase": ERROR_RATE_INCREASE_LIMIT,
    }


def _evaluate_explorer(
    spec: ExplorerExperimentSpec,
    stable: SideMeasurement,
    candidate: SideMeasurement,
) -> tuple[bool | None, str, dict[str, float | int | str]]:
    """Interpret an AI-authored spec using fixed, server-owned operators."""
    if not stable.success:
        return None, "Explorer could not establish a valid stable baseline.", {"decision": "review_only"}

    findings: list[str] = []
    assertions = set(spec.assertions)
    # Availability and status parity are mandatory guardrails for every
    # generated probe; the model cannot opt out by omitting an assertion.
    if not candidate.success:
        findings.append("candidate did not respond successfully")
    if stable.response_status != candidate.response_status:
        findings.append(
            f"status changed from {stable.response_status} to {candidate.response_status}"
        )

    stable_signature = _response_signature(stable.response_sample)
    candidate_signature = _response_signature(candidate.response_sample)
    if ExplorerAssertion.RESPONSE_SHAPE_MATCH in assertions:
        if set(stable_signature) != set(candidate_signature):
            findings.append("response field shape differs from stable")
    if ExplorerAssertion.RESPONSE_TYPES_MATCH in assertions:
        shared = set(stable_signature) & set(candidate_signature)
        changed_types = sorted(
            path for path in shared if stable_signature[path] != candidate_signature[path]
        )
        if changed_types:
            findings.append("response types changed at " + ", ".join(changed_types[:5]))

    if ExplorerAssertion.REQUIRED_PATHS_PRESENT in assertions:
        missing = [
            path
            for path in spec.required_response_paths
            if _response_value(candidate.response_sample, path) is MISSING
        ]
        if missing:
            findings.append("candidate is missing required paths: " + ", ".join(missing))

    if ExplorerAssertion.COMPARE_PATHS in assertions:
        changed = []
        for path in spec.compare_response_paths:
            stable_value = _response_value(stable.response_sample, path)
            candidate_value = _response_value(candidate.response_sample, path)
            if stable_value is MISSING or candidate_value is MISSING or stable_value != candidate_value:
                changed.append(path)
        if changed:
            findings.append("selected invariant paths differ: " + ", ".join(changed))

    if ExplorerAssertion.LATENCY_WITHIN_POLICY in assertions:
        stable_latency = stable.p95_latency_ms
        candidate_latency = candidate.p95_latency_ms
        samples = min(stable.latency_samples, candidate.latency_samples)
        if stable_latency and candidate_latency and samples >= MIN_LATENCY_SAMPLES:
            regression = (candidate_latency - stable_latency) / stable_latency
            if regression > LATENCY_REGRESSION_LIMIT:
                findings.append(f"p95 latency regressed by {regression:.1%} over {samples} samples")

    thresholds: dict[str, float | int | str] = {
        "decision": "review_only",
        "execution": "fixed declarative DSL; no model-authored code",
        "mandatory_assertions": "candidate_success,status_match",
        "max_p95_regression": LATENCY_REGRESSION_LIMIT,
    }
    if findings:
        return False, "Explorer finding: " + "; ".join(findings) + ". Human review required.", thresholds
    return True, "The generated probe found no difference under its declared assertions.", thresholds


async def _assert_safe_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) revision URLs are supported")
    if parsed.hostname in {"metadata.google.internal", "metadata"}:
        raise ValueError("Metadata endpoints are never valid test targets")
    allow_private = os.getenv("RELEASEPROOF_ALLOW_PRIVATE_TARGETS", "false").lower() == "true"
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
            raise ValueError("Private targets require RELEASEPROOF_ALLOW_PRIVATE_TARGETS=true")


async def _live_side(url: str, path: str, experiment_id: ExperimentId, warmups: int, trials: int) -> SideMeasurement:
    await _assert_safe_target(url)
    experiment_path = "/health" if experiment_id == ExperimentId.HEALTH else path
    target = urljoin(url.rstrip("/") + "/", experiment_path.lstrip("/"))
    latencies: list[float] = []
    errors = 0
    response_status: int | None = None
    sample: Any = None
    requests_per_trial = _requests_per_trial(experiment_id)
    request_count = min(trials * requests_per_trial, LIVE_REQUEST_CAP)

    async def probe(client: httpx.AsyncClient, index: int) -> tuple[float, int | None, Any, bool]:
        params: dict[str, str] | None = None
        if experiment_id == ExperimentId.EDGE:
            values = ("", " ", "नमस्ते", "0", "-1")
            params = {"releaseproof_edge": values[index % len(values)]}
        elif experiment_id == ExperimentId.PAYLOAD:
            sizes = (1, 256, 1024)
            params = {"releaseproof_payload": "x" * sizes[index % len(sizes)]}
        headers = {"User-Agent": "ReleaseProof/0.1", "X-ReleaseProof-Probe": experiment_id.value}
        started = time.perf_counter()
        try:
            response = await client.get(target, params=params, headers=headers)
            latency = (time.perf_counter() - started) * 1000
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text[:500]
            return latency, response.status_code, body, not 200 <= response.status_code < 400
        except httpx.HTTPError as exc:
            return (time.perf_counter() - started) * 1000, None, type(exc).__name__, True

    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        for _ in range(warmups):
            try:
                await client.get(target, headers={"User-Agent": "ReleaseProof/0.1"})
            except httpx.HTTPError:
                pass
        completed = 0
        concurrency = _probe_concurrency(experiment_id)
        while completed < request_count:
            batch_size = min(concurrency, request_count - completed)
            results = await asyncio.gather(*(probe(client, completed + offset) for offset in range(batch_size)))
            for latency, status, body, failed in results:
                latencies.append(latency)
                response_status = status
                sample = body
                errors += int(failed)
            completed += batch_size
    return SideMeasurement(
        success=errors == 0,
        trials_completed=trials,
        warmups_completed=warmups,
        requests=request_count,
        error_rate=round(errors / max(request_count, 1), 4),
        p95_latency_ms=_p95(latencies),
        latency_samples=len(latencies),
        response_status=response_status,
        response_sample=sample,
        notes=[
            f"Bounded live HTTP probe for {experiment_id.value}; no arbitrary commands executed.",
            f"Executed {request_count} timed request(s), {concurrency} in flight at a time.",
        ],
    )


async def _live_explorer_side(
    url: str,
    path: str,
    spec: ExplorerExperimentSpec,
    warmups: int,
    trials: int,
) -> SideMeasurement:
    """Execute only the constrained GET/query DSL against the already-approved target."""
    await _assert_safe_target(url)
    target = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
    latencies: list[float] = []
    errors = 0
    response_status: int | None = None
    sample: Any = None
    headers = {
        "User-Agent": "ReleaseProof/0.1",
        "X-ReleaseProof-Probe": ExperimentId.AI_EXPLORER.value,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        for _ in range(warmups):
            try:
                await client.get(target, params=spec.query_parameters, headers=headers)
            except httpx.HTTPError:
                pass
        for _ in range(trials * _requests_per_trial(ExperimentId.AI_EXPLORER)):
            started = time.perf_counter()
            try:
                response = await client.get(target, params=spec.query_parameters, headers=headers)
                latencies.append((time.perf_counter() - started) * 1000)
                response_status = response.status_code
                errors += int(not 200 <= response.status_code < 400)
                try:
                    sample = response.json()
                except ValueError:
                    sample = response.text[:500]
            except httpx.HTTPError as exc:
                latencies.append((time.perf_counter() - started) * 1000)
                errors += 1
                sample = type(exc).__name__
    return SideMeasurement(
        success=errors == 0,
        trials_completed=trials,
        warmups_completed=warmups,
        requests=len(latencies),
        error_rate=round(errors / max(len(latencies), 1), 4),
        p95_latency_ms=_p95(latencies),
        latency_samples=len(latencies),
        response_status=response_status,
        response_sample=sample,
        notes=[
            "AI-authored declarative probe; fixed runner executed GET only.",
            "No generated source code, headers, credentials, shell commands, or arbitrary target URL were accepted.",
        ],
    )


async def execute_plan(change: ChangeInput, plan: ExperimentPlan) -> list[ExperimentEvidence]:
    experiment_ids = list(plan.baseline_experiments) + [item.experiment_id for item in plan.adaptive_experiments]
    total_requests = 0
    evidence: list[ExperimentEvidence] = []
    profiles = scenario_results(change.scenario_id) if change.scenario_id else None

    for experiment_id in experiment_ids:
        definition = CATALOG[experiment_id]
        profile = profiles.get(experiment_id.value) if profiles is not None else None
        if profile is not None:
            estimated = (
                int(profile["stable"].get("requests", change.budget.trials))
                + int(profile["candidate"].get("requests", change.budget.trials))
                + change.budget.warmups * 2
            )
        else:
            requests_per_trial = _requests_per_trial(experiment_id)
            estimated = (change.budget.warmups + change.budget.trials * requests_per_trial) * 2
        if total_requests + estimated > change.budget.max_requests:
            inconclusive = SideMeasurement(success=False, trials_completed=0, warmups_completed=0, requests=0, notes=["Request budget exhausted."])
            evidence.append(ExperimentEvidence(
                experiment_id=experiment_id,
                title=definition.title,
                blocking=definition.blocking,
                stable=inconclusive,
                candidate=inconclusive,
                passed=None,
                explanation="Experiment was not executed because the bounded request budget was exhausted.",
            ))
            continue

        if profiles is not None:
            if profile is None:
                inconclusive = SideMeasurement(success=False, trials_completed=0, warmups_completed=0, requests=0, notes=["Scenario has no fixture for this experiment."])
                evidence.append(ExperimentEvidence(
                    experiment_id=experiment_id,
                    title=definition.title,
                    blocking=definition.blocking,
                    stable=inconclusive,
                    candidate=inconclusive,
                    passed=None,
                    explanation="The demonstration scenario does not contain evidence for this selected experiment.",
                ))
                continue
            stable = _side_from_profile(profile["stable"], change.budget.warmups, change.budget.trials)
            candidate = _side_from_profile(profile["candidate"], change.budget.warmups, change.budget.trials)
        else:
            stable, candidate = await asyncio.gather(
                _live_side(str(change.stable_url), change.request_path, experiment_id, change.budget.warmups, change.budget.trials),
                _live_side(str(change.candidate_url), change.request_path, experiment_id, change.budget.warmups, change.budget.trials),
            )
        total_requests += estimated
        passed, explanation, thresholds = _evaluate(experiment_id, stable, candidate, change)

        # Intent reconciliation runs on the representative request path, as part
        # of the mandatory baseline rather than the adaptive plan — so every
        # release is checked for effects its change never declared, even when
        # the planner selects nothing.
        adjudication = None
        if experiment_id == ExperimentId.SMOKE and passed is not None:
            adjudication = await asyncio.to_thread(
                adjudicate, change, stable.response_sample, candidate.response_sample
            )
            if not adjudication.passed:
                passed = False
                explanation = adjudication.summary
                thresholds = {**thresholds, "policy": "every observed change must be explained by the diff"}

        evidence.append(ExperimentEvidence(
            experiment_id=experiment_id,
            title=definition.title,
            blocking=definition.blocking,
            stable=stable,
            candidate=candidate,
            passed=passed,
            explanation=explanation,
            thresholds=thresholds,
            adjudication=adjudication,
        ))

    explorer_definition = CATALOG[ExperimentId.AI_EXPLORER]
    for spec in plan.exploratory_experiments:
        estimated = (change.budget.warmups + change.budget.trials * _requests_per_trial(ExperimentId.AI_EXPLORER)) * 2
        if total_requests + estimated > change.budget.max_requests:
            inconclusive = SideMeasurement(
                success=False,
                trials_completed=0,
                warmups_completed=0,
                requests=0,
                notes=["Request budget exhausted."],
            )
            evidence.append(ExperimentEvidence(
                experiment_id=ExperimentId.AI_EXPLORER,
                title=f"AI Explorer: {spec.name}",
                blocking=False,
                stable=inconclusive,
                candidate=inconclusive,
                passed=None,
                explanation="Generated probe was not executed because the bounded request budget was exhausted.",
                review_only=True,
                exploratory_spec=spec,
            ))
            continue

        profile = profiles.get(ExperimentId.AI_EXPLORER.value) if profiles is not None else None
        if profiles is not None:
            if profile is None:
                inconclusive = SideMeasurement(
                    success=False,
                    trials_completed=0,
                    warmups_completed=0,
                    requests=0,
                    notes=["Scenario has no AI Explorer fixture."],
                )
                evidence.append(ExperimentEvidence(
                    experiment_id=ExperimentId.AI_EXPLORER,
                    title=f"AI Explorer: {spec.name}",
                    blocking=False,
                    stable=inconclusive,
                    candidate=inconclusive,
                    passed=None,
                    explanation="This prepared scenario has no evidence for the generated probe.",
                    review_only=True,
                    exploratory_spec=spec,
                ))
                continue
            stable = _side_from_profile(profile["stable"], change.budget.warmups, change.budget.trials)
            candidate = _side_from_profile(profile["candidate"], change.budget.warmups, change.budget.trials)
        else:
            stable, candidate = await asyncio.gather(
                _live_explorer_side(
                    str(change.stable_url), change.request_path, spec,
                    change.budget.warmups, change.budget.trials,
                ),
                _live_explorer_side(
                    str(change.candidate_url), change.request_path, spec,
                    change.budget.warmups, change.budget.trials,
                ),
            )
        total_requests += estimated
        passed, explanation, thresholds = _evaluate_explorer(spec, stable, candidate)
        evidence.append(ExperimentEvidence(
            experiment_id=ExperimentId.AI_EXPLORER,
            title=f"{explorer_definition.title}: {spec.name}",
            blocking=False,
            stable=stable,
            candidate=candidate,
            passed=passed,
            explanation=explanation,
            thresholds=thresholds,
            review_only=True,
            exploratory_spec=spec,
        ))
    return evidence


def determine_verdict(evidence: list[ExperimentEvidence]) -> tuple[Verdict, list[str]]:
    failures = [item for item in evidence if item.blocking and item.passed is False]
    inconclusive = [item for item in evidence if item.blocking and item.passed is None]
    if failures:
        return Verdict.BLOCK, [f"{item.title}: {item.explanation}" for item in failures]
    if inconclusive or not evidence:
        reasons = [f"{item.title}: {item.explanation}" for item in inconclusive]
        return Verdict.INCONCLUSIVE, reasons or ["No evidence was produced."]
    return Verdict.PASS, ["All executed blocking experiments passed deterministic policies."]
