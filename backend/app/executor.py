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
    ExperimentEvidence,
    ExperimentId,
    ExperimentPlan,
    SideMeasurement,
    Verdict,
)
from .scenarios import scenario_results


LATENCY_REGRESSION_LIMIT = 0.30
ERROR_RATE_INCREASE_LIMIT = 0.02
LIVE_REQUEST_CAP = 100


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 2)


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


def _side_from_profile(raw: dict[str, Any], warmups: int, trials: int) -> SideMeasurement:
    requests = int(raw.get("requests", trials))
    errors = int(raw.get("errors", 0))
    latencies = [float(value) for value in raw.get("latencies", [])][:trials]
    return SideMeasurement(
        success=200 <= int(raw.get("status", 0)) < 400 and errors / max(requests, 1) <= ERROR_RATE_INCREASE_LIMIT,
        trials_completed=min(trials, len(latencies)) if latencies else trials,
        warmups_completed=warmups,
        requests=requests,
        error_rate=round(errors / max(requests, 1), 4),
        p95_latency_ms=_p95(latencies),
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
    if stable_latency and candidate_latency:
        regression = (candidate_latency - stable_latency) / stable_latency
        if regression > LATENCY_REGRESSION_LIMIT:
            return False, f"Candidate p95 latency regressed by {regression:.1%}.", {"max_p95_regression": LATENCY_REGRESSION_LIMIT}

    stable_errors = stable.error_rate or 0.0
    candidate_errors = candidate.error_rate or 0.0
    if candidate_errors - stable_errors > ERROR_RATE_INCREASE_LIMIT:
        return False, "Candidate error-rate increase exceeded the allowed bound.", {"max_error_rate_increase": ERROR_RATE_INCREASE_LIMIT}

    return True, "Candidate remained within deterministic compatibility, error and latency policies.", {
        "max_p95_regression": LATENCY_REGRESSION_LIMIT,
        "max_error_rate_increase": ERROR_RATE_INCREASE_LIMIT,
    }


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
    requests_per_trial = 10 if experiment_id == ExperimentId.LOAD else 1
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
        while completed < request_count:
            batch_size = min(requests_per_trial, request_count - completed)
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
        response_status=response_status,
        response_sample=sample,
        notes=[
            f"Bounded live HTTP probe for {experiment_id.value}; no arbitrary commands executed.",
            f"Executed {requests_per_trial} request(s) per trial.",
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
            requests_per_trial = 10 if experiment_id == ExperimentId.LOAD else 1
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
