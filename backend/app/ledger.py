"""Storage for run records.

The system's claim is that any verdict can be replayed from the evidence that
produced it. On Cloud Run the container filesystem is ephemeral and per
instance, so a JSON ledger loses every record on redeploy, on scale to zero,
and whenever a request lands on a different instance than the one that wrote
it. Evidence that disappears before anyone looks at it does not support the
claim.

Firestore is used when configured, with the JSON store kept for local work and
as a fallback when Firestore cannot be reached — a gate that stops issuing
verdicts because its archive is unavailable would be a worse failure than one
whose archive is temporarily incomplete.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .models import RunRecord


class JsonLedgerStore:
    """Local, single-instance storage. Durable only for the life of the disk."""

    backend = "json"

    def __init__(self, directory: str | None = None) -> None:
        default = Path(__file__).resolve().parent.parent / "data" / "runs"
        self.directory = Path(directory or os.getenv("RELEASEPROOF_LEDGER_DIR", str(default)))
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        if not run_id or any(char not in "0123456789abcdef-" for char in run_id.lower()):
            raise ValueError("Invalid run id")
        return self.directory / f"{run_id}.json"

    def save(self, record: RunRecord) -> None:
        destination = self._path(record.id)
        temporary = destination.with_suffix(".tmp")
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True)
        with self._lock:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(destination)

    def get(self, run_id: str) -> RunRecord | None:
        try:
            path = self._path(run_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))


class FirestoreLedgerStore:
    """Durable storage that outlives the instance that produced the record.

    Writes also go to a local store so a Firestore outage degrades to the old
    behaviour rather than losing the record outright, and reads fall back to it.
    """

    backend = "firestore"

    def __init__(self, collection: str | None = None, project: str | None = None) -> None:
        from google.cloud import firestore  # imported here so local runs need no dependency

        self.collection_name = collection or os.getenv("RELEASEPROOF_LEDGER_COLLECTION", "releaseproof_runs")
        self._client = firestore.Client(project=project or os.getenv("GOOGLE_CLOUD_PROJECT"))
        self._mirror = JsonLedgerStore()

    def save(self, record: RunRecord) -> None:
        self._mirror.save(record)
        try:
            self._client.collection(self.collection_name).document(record.id).set(
                record.model_dump(mode="json")
            )
        except Exception:
            # The verdict has already been decided and returned; failing the
            # request now would turn an archiving problem into a release
            # problem.
            pass

    def get(self, run_id: str) -> RunRecord | None:
        try:
            snapshot = self._client.collection(self.collection_name).document(run_id).get()
            if snapshot.exists:
                return RunRecord.model_validate(snapshot.to_dict())
        except Exception:
            pass
        return self._mirror.get(run_id)


def build_ledger_store():
    """Pick a store from the environment, preferring durability when available."""
    if os.getenv("RELEASEPROOF_USE_FIRESTORE", "false").lower() != "true":
        return JsonLedgerStore()
    try:
        return FirestoreLedgerStore()
    except Exception:
        # Misconfiguration must not stop the gate from issuing verdicts.
        return JsonLedgerStore()
