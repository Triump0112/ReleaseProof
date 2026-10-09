"""Evidence must outlive the instance that produced it.

The system claims every verdict is replayable from its record. On Cloud Run the
container filesystem is ephemeral and per instance, so a JSON ledger loses
everything on redeploy — observed in practice, where a run referenced by a CI
summary returned 404 after the next deploy.

These tests pin the two properties that matter: durability is selected by
configuration, and no storage failure can take down the gate.
"""

from __future__ import annotations

import app.ledger as ledger_module
from app.ledger import FirestoreLedgerStore, JsonLedgerStore, build_ledger_store
from app.models import ChangeInput, EvidenceLedger, ExperimentPlan, RunRecord, utc_now


def _record() -> RunRecord:
    change = ChangeInput(
        service_name="pricing-api",
        summary="Apply 18% GST to the quote total",
        diff="+ tax_rate = 0.18",
        scenario_id="undeclared-side-effect",
        request_path="/api/v1/quote",
    )
    plan = ExperimentPlan(
        detected_change="tax change",
        risk_summary="undeclared behaviour",
        adaptive_experiments=[],
        planner="vertex_gemini",
    )
    record = RunRecord(ledger=EvidenceLedger(run_id="pending", created_at=utc_now(), change=change, plan=plan))
    record.ledger.run_id = record.id
    return record


def test_json_store_round_trips_a_record(tmp_path):
    store = JsonLedgerStore(directory=str(tmp_path))
    record = _record()
    store.save(record)
    assert store.get(record.id).ledger.change.service_name == "pricing-api"


def test_json_store_rejects_a_traversal_style_run_id(tmp_path):
    store = JsonLedgerStore(directory=str(tmp_path))
    assert store.get("../../etc/passwd") is None


def test_unknown_run_id_returns_none_rather_than_raising(tmp_path):
    assert JsonLedgerStore(directory=str(tmp_path)).get("ffffffff-0000-0000-0000-000000000000") is None


def test_factory_defaults_to_the_local_store(monkeypatch):
    monkeypatch.delenv("RELEASEPROOF_USE_FIRESTORE", raising=False)
    assert build_ledger_store().backend == "json"


def test_factory_falls_back_when_firestore_cannot_be_constructed(monkeypatch):
    """Misconfiguration must not stop the gate from issuing verdicts."""
    monkeypatch.setenv("RELEASEPROOF_USE_FIRESTORE", "true")

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no credentials")

    monkeypatch.setattr(ledger_module, "FirestoreLedgerStore", Boom)
    assert build_ledger_store().backend == "json"


def test_a_firestore_write_failure_does_not_lose_the_record(monkeypatch, tmp_path):
    """The verdict is already decided; archiving must not become a release problem."""
    store = FirestoreLedgerStore.__new__(FirestoreLedgerStore)
    store.collection_name = "runs"
    store._mirror = JsonLedgerStore(directory=str(tmp_path))

    class BrokenClient:
        def collection(self, _name):
            raise RuntimeError("firestore unavailable")

    store._client = BrokenClient()

    record = _record()
    store.save(record)  # must not raise
    # The local mirror still has it, so the record is not simply gone.
    assert store.get(record.id).id == record.id


def test_firestore_read_failure_falls_back_to_the_mirror(monkeypatch, tmp_path):
    store = FirestoreLedgerStore.__new__(FirestoreLedgerStore)
    store.collection_name = "runs"
    store._mirror = JsonLedgerStore(directory=str(tmp_path))
    record = _record()
    store._mirror.save(record)

    class BrokenClient:
        def collection(self, _name):
            raise RuntimeError("firestore unavailable")

    store._client = BrokenClient()
    assert store.get(record.id).id == record.id
