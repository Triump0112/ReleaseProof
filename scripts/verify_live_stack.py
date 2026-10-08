"""Exercise ReleaseProof against real local stable/candidate HTTP processes.

This is intentionally separate from the fast fixture tests. It proves that the
orchestrator can plan and execute paired probes against running services.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEMOS = ROOT / "demo-services"
HOST = "127.0.0.1"
API_PORT = 8390
STABLE_PORT = 8391
CANDIDATE_PORT = 8392


def start(cwd: Path, module: str, port: int, extra_env: dict[str, str]) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            HOST,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for(url: str, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=0.8)
            if response.is_success:
                return
        except Exception as exc:  # startup connection failures are expected
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"Service did not become ready: {url}; last error: {last_error}")


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def start_pair(scenario: str) -> list[subprocess.Popen[str]]:
    pair = [
        start(DEMOS, "app.main:app", STABLE_PORT, {"ROLE": "stable", "SCENARIO": scenario}),
        start(DEMOS, "app.main:app", CANDIDATE_PORT, {"ROLE": "candidate", "SCENARIO": scenario}),
    ]
    wait_for(f"http://{HOST}:{STABLE_PORT}/health")
    wait_for(f"http://{HOST}:{CANDIDATE_PORT}/health")
    return pair


def analyze(payload: dict[str, object], expected_experiment: str) -> None:
    response = httpx.post(f"http://{HOST}:{API_PORT}/api/analyze", json=payload, timeout=45)
    response.raise_for_status()
    record = response.json()
    assert record["status"] == "COMPLETE", record
    ledger = record["ledger"]
    assert ledger["verdict"] == "BLOCK", ledger
    selected = ledger["plan"]["adaptive_experiments"]
    assert selected and selected[0]["experiment_id"] == expected_experiment, selected
    adaptive_evidence = next(item for item in ledger["evidence"] if item["experiment_id"] == expected_experiment)
    assert adaptive_evidence["passed"] is False, adaptive_evidence
    print(
        f"{expected_experiment}: {ledger['verdict']} - "
        f"{adaptive_evidence['explanation']}"
    )


def analyze_side_effect(payload: dict[str, object]) -> None:
    """Assert the gate blocks on behaviour the change never declared.

    Every conventional signal here is clean, so this also guards against the
    adjudicator being bypassed: the smoke experiment must be what fails, and it
    must fail on the undeclared field rather than on shape or latency.
    """
    response = httpx.post(f"http://{HOST}:{API_PORT}/api/analyze", json=payload, timeout=45)
    response.raise_for_status()
    record = response.json()
    assert record["status"] == "COMPLETE", record
    ledger = record["ledger"]
    assert ledger["verdict"] == "BLOCK", ledger

    smoke = next(item for item in ledger["evidence"] if item["experiment_id"] == "api_smoke")
    adjudication = smoke["adjudication"]
    assert adjudication is not None, smoke
    assert adjudication["passed"] is False, adjudication
    assert adjudication["unexplained_paths"] == ["discount_applied"], adjudication

    labels = {item["path"]: item["label"] for item in adjudication["classifications"]}
    assert labels["total"] == "explained", labels
    assert labels["tax_rate"] == "explained", labels
    # Non-determinism present on both revisions must not be mistaken for a regression.
    assert labels["quote_id"] == "benign_noise", labels
    assert labels["issued_at"] == "benign_noise", labels

    health = next(item for item in ledger["evidence"] if item["experiment_id"] == "health_check")
    assert health["passed"] is True, health

    explorer = next(item for item in ledger["evidence"] if item["experiment_id"] == "ai_explorer")
    assert explorer["review_only"] is True, explorer
    assert explorer["blocking"] is False, explorer
    assert explorer["exploratory_spec"]["name"] == "generated-boundary-probe", explorer

    print(f"intent_reconciliation: {ledger['verdict']} - {smoke['explanation']}")


def main() -> None:
    api = start(
        BACKEND,
        "app.main:app",
        API_PORT,
        {
            "RELEASEPROOF_ALLOW_PRIVATE_TARGETS": "true",
            "RELEASEPROOF_USE_VERTEX": "false",
            "RELEASEPROOF_LEDGER_DIR": str(ROOT / "tmp" / "live-runs"),
        },
    )
    processes = [api]
    try:
        wait_for(f"http://{HOST}:{API_PORT}/health")

        latency_pair = start_pair("latency")
        processes.extend(latency_pair)
        analyze(
            {
                "service_name": "checkout-api",
                "summary": "Increase Cloud Run concurrency from 4 to 32",
                "diff": "- containerConcurrency: 4\n+ containerConcurrency: 32",
                "stable_url": f"http://{HOST}:{STABLE_PORT}",
                "candidate_url": f"http://{HOST}:{CANDIDATE_PORT}",
                "request_path": "/api/v1/quote",
            },
            "bounded_load",
        )
        for process in latency_pair:
            stop(process)
            processes.remove(process)

        contract_pair = start_pair("contract")
        processes.extend(contract_pair)
        analyze(
            {
                "service_name": "pricing-api",
                "summary": "Rename total to amount in the checkout response",
                "diff": '- "total": 499\n+ "amount": "499"',
                "stable_url": f"http://{HOST}:{STABLE_PORT}",
                "candidate_url": f"http://{HOST}:{CANDIDATE_PORT}",
                "request_path": "/api/v1/quote",
                "expected_contract": {
                    "required_fields": {"total": "number", "currency": "string"}
                },
            },
            "contract_compatibility",
        )
        for process in contract_pair:
            stop(process)
            processes.remove(process)

        side_effect_pair = start_pair("sideeffect")
        processes.extend(side_effect_pair)
        analyze_side_effect(
            {
                "service_name": "pricing-api",
                "summary": "Apply 18% GST to the quote total",
                "diff": (
                    "-    total = subtotal\n"
                    "+    tax_rate = 0.18\n"
                    "+    total = subtotal * (1 + tax_rate)"
                ),
                "stable_url": f"http://{HOST}:{STABLE_PORT}",
                "candidate_url": f"http://{HOST}:{CANDIDATE_PORT}",
                "request_path": "/api/v1/quote",
                "analysis_mode": "explorer",
            }
        )
        print("Live paired-service verification passed.")
    finally:
        for process in reversed(processes):
            stop(process)


if __name__ == "__main__":
    main()
