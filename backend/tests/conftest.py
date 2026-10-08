import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASEPROOF_LEDGER_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("RELEASEPROOF_USE_VERTEX", "false")

    from app import main
    from app.ledger import JsonLedgerStore

    main.store = JsonLedgerStore()
    with TestClient(main.app) as test_client:
        yield test_client

