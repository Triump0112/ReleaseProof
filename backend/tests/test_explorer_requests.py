"""Does the AI path actually issue a different request than the fixed path?

The scenario tests elsewhere compare *outcomes*, and in fixture mode those
outcomes are stored data — so they would still pass if the generated probe's
inputs were ignored entirely. These tests close that gap by recording the real
HTTP requests both paths make against a faithful stand-in revision, and by
showing the finding disappears when the model's chosen input is removed.
"""

from __future__ import annotations

import httpx
import pytest

from app import executor
from app.executor import _live_explorer_side, _live_side
from app.models import ExperimentId, ExplorerAssertion, ExplorerExperimentSpec


STABLE_URL = "http://127.0.0.1:9101"
CANDIDATE_URL = "http://127.0.0.1:9102"
REQUEST_PATH = "/api/v1/quote"

ZERO_DECIMAL = {"JPY", "KRW", "VND"}
SERVICE_FEE_RATE = 0.075


def _quote(role: str, currency: str) -> dict[str, object]:
    """Mirror of the demo revisions' money logic.

    Stable honours the currency's decimal exponent. The candidate hardcodes two
    decimal places, which is the seeded regression.
    """
    charged = 499.0 * (1 + SERVICE_FEE_RATE)
    decimals = 2 if role == "candidate" else (0 if currency in ZERO_DECIMAL else 2)
    return {"total": round(charged, decimals), "currency": currency, "fee_rate": SERVICE_FEE_RATE}


@pytest.fixture
def recorded(monkeypatch):
    """Serve both revisions in-process and record every request made."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        role = "candidate" if request.url.port == 9102 else "stable"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        currency = request.url.params.get("currency", "INR").upper()
        return httpx.Response(200, json=_quote(role, currency))

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setenv("RELEASEPROOF_ALLOW_PRIVATE_TARGETS", "true")
    monkeypatch.setattr(executor.httpx, "AsyncClient", client_factory)
    return seen


def _probe_spec(**overrides) -> ExplorerExperimentSpec:
    base = dict(
        name="generated-zero-decimal-currency-probe",
        rationale="Rounding changed and no catalog experiment varies the currency.",
        hypothesis="A zero-decimal currency will separate the revisions.",
        query_parameters={"currency": "JPY"},
        assertions=[ExplorerAssertion.CANDIDATE_SUCCESS, ExplorerAssertion.COMPARE_PATHS],
        compare_response_paths=["total"],
    )
    base.update(overrides)
    return ExplorerExperimentSpec(**base)


@pytest.mark.asyncio
async def test_generated_probe_sends_an_input_the_fixed_path_never_sends(recorded):
    """The two paths must differ in the request itself, not just the verdict."""
    await _live_side(STABLE_URL, REQUEST_PATH, ExperimentId.SMOKE, warmups=0, trials=1)
    catalog_requests = [url for url in recorded if url.path == REQUEST_PATH]
    recorded.clear()

    await _live_explorer_side(STABLE_URL, REQUEST_PATH, _probe_spec(), warmups=0, trials=1)
    explorer_requests = [url for url in recorded if url.path == REQUEST_PATH]

    assert catalog_requests and explorer_requests
    # The fixed smoke probe never sets a currency; the generated probe does.
    assert all("currency" not in url.params for url in catalog_requests)
    assert all(url.params.get("currency") == "JPY" for url in explorer_requests)
    assert {str(u) for u in catalog_requests}.isdisjoint({str(u) for u in explorer_requests})


@pytest.mark.asyncio
async def test_fixed_path_sees_identical_revisions_but_generated_probe_does_not(recorded):
    """Same revisions, same assertions — only the chosen input differs."""
    stable_smoke = await _live_side(STABLE_URL, REQUEST_PATH, ExperimentId.SMOKE, 0, 1)
    candidate_smoke = await _live_side(CANDIDATE_URL, REQUEST_PATH, ExperimentId.SMOKE, 0, 1)
    assert stable_smoke.response_sample == candidate_smoke.response_sample

    spec = _probe_spec()
    stable_probe = await _live_explorer_side(STABLE_URL, REQUEST_PATH, spec, 0, 1)
    candidate_probe = await _live_explorer_side(CANDIDATE_URL, REQUEST_PATH, spec, 0, 1)
    assert stable_probe.response_sample != candidate_probe.response_sample
    assert stable_probe.response_sample["total"] == 536.0
    assert candidate_probe.response_sample["total"] == 536.42

    passed, explanation, _ = executor._evaluate_explorer(spec, stable_probe, candidate_probe)
    assert passed is False
    assert "total" in explanation


@pytest.mark.asyncio
async def test_removing_the_models_chosen_input_removes_the_finding(recorded):
    """Causation, not correlation: the finding depends on the authored input.

    Without this, a stored fixture that merely happens to differ would make the
    probe look effective even if its inputs were discarded.
    """
    spec = _probe_spec(query_parameters={})

    stable = await _live_explorer_side(STABLE_URL, REQUEST_PATH, spec, 0, 1)
    candidate = await _live_explorer_side(CANDIDATE_URL, REQUEST_PATH, spec, 0, 1)

    assert stable.response_sample == candidate.response_sample
    passed, _, _ = executor._evaluate_explorer(spec, stable, candidate)
    assert passed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("currency,finds", [("INR", False), ("USD", False), ("JPY", True), ("KRW", True)])
async def test_only_a_zero_decimal_currency_separates_the_revisions(recorded, currency, finds):
    """Pins which inputs are actually informative, so the scenario can't drift."""
    spec = _probe_spec(query_parameters={"currency": currency})
    stable = await _live_explorer_side(STABLE_URL, REQUEST_PATH, spec, 0, 1)
    candidate = await _live_explorer_side(CANDIDATE_URL, REQUEST_PATH, spec, 0, 1)

    passed, _, _ = executor._evaluate_explorer(spec, stable, candidate)
    assert passed is (not finds)
