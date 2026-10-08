from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .models import RunRecord


class JsonLedgerStore:
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

