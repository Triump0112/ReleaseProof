from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .catalog import CATALOG, RISK_TAXONOMY
from .executor import determine_verdict, execute_plan
from .ledger import JsonLedgerStore
from .models import ChangeInput, EvidenceLedger, RunRecord, RunStatus, Verdict, utc_now
from .planner import build_plan
from .scenarios import SCENARIO_PROFILES, scenario_summaries


app = FastAPI(
    title="ReleaseProof API",
    version="0.1.0",
    description="Evidence-locked, pre-traffic differential release verification for Cloud Run.",
)
# The deployed UI proxies /api/ same-origin, so CORS is only needed for local
# development and any explicitly allowlisted hosted origin.
_extra_origins = [
    origin.strip()
    for origin in os.getenv("RELEASEPROOF_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", *_extra_origins],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
store = JsonLedgerStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "releaseproof-api"}


@app.get("/api/catalog")
def catalog():
    return list(CATALOG.values())


@app.get("/api/risk-classes")
def risk_classes():
    """Coverage map: implemented, partial and planned are deliberately distinct."""
    return RISK_TAXONOMY


#: UI scenario id -> the pair of environment variables naming its revisions.
_DEMO_TARGET_ENV = {
    "concurrency": ("RELEASEPROOF_STABLE_LATENCY_URL", "RELEASEPROOF_CANDIDATE_LATENCY_URL"),
    "contract": ("RELEASEPROOF_STABLE_CONTRACT_URL", "RELEASEPROOF_CANDIDATE_CONTRACT_URL"),
    "sideeffect": ("RELEASEPROOF_STABLE_SIDEEFFECT_URL", "RELEASEPROOF_CANDIDATE_SIDEEFFECT_URL"),
    "currency": ("RELEASEPROOF_STABLE_MONEY_URL", "RELEASEPROOF_CANDIDATE_MONEY_URL"),
}


@app.get("/api/demo-targets")
def demo_targets():
    """Revision URLs for the prepared scenarios, resolved at runtime.

    Deliberately not baked into the UI bundle: the frontend builds from a
    Dockerfile, and build-time variables do not reliably reach a Docker build.
    Reading them here means one image works in Compose and on Cloud Run, and a
    URL change is a redeploy of this service rather than a rebuild of the UI.
    """
    targets: dict[str, dict[str, str]] = {}
    for scenario_id, (stable_var, candidate_var) in _DEMO_TARGET_ENV.items():
        stable, candidate = os.getenv(stable_var, ""), os.getenv(candidate_var, "")
        # Only advertise a pair when both sides are configured; a half-configured
        # scenario would otherwise fail mid-run with a confusing error.
        if stable and candidate:
            targets[scenario_id] = {"stable": stable, "candidate": candidate}
    return {"live": bool(targets), "targets": targets}


@app.get("/api/scenarios")
def scenarios():
    return scenario_summaries()


@app.post("/api/analyze", response_model=RunRecord)
async def analyze(change: ChangeInput) -> RunRecord:
    if change.scenario_id and change.scenario_id not in SCENARIO_PROFILES:
        raise HTTPException(status_code=422, detail="Unknown scenario_id")

    plan = build_plan(change)
    record = RunRecord(
        ledger=EvidenceLedger(run_id="pending", created_at=utc_now(), change=change, plan=plan)
    )
    record.ledger.run_id = record.id
    store.save(record)
    try:
        try:
            record.ledger.evidence = await asyncio.wait_for(
                execute_plan(change, plan), timeout=change.budget.max_duration_seconds
            )
            verdict, reasons = determine_verdict(record.ledger.evidence)
            record.ledger.verdict = verdict
            record.ledger.verdict_reasons = reasons
            record.ledger.review_findings = [
                item.explanation
                for item in record.ledger.evidence
                if item.review_only and item.passed is False
            ]
        except TimeoutError:
            record.ledger.verdict = Verdict.INCONCLUSIVE
            record.ledger.verdict_reasons = [
                f"The run exceeded its {change.budget.max_duration_seconds}-second execution budget."
            ]
        record.ledger.completed_at = utc_now()
        record.status = RunStatus.COMPLETE
    except Exception as exc:
        record.status = RunStatus.FAILED
        record.error = str(exc)
        record.ledger.completed_at = utc_now()
    store.save(record)
    return record


@app.get("/api/runs/{run_id}", response_model=RunRecord)
def get_run(run_id: str) -> RunRecord:
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return record
