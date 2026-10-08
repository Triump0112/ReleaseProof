from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.main import create_app


async def _client(role: str, scenario: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(role=role, scenario=scenario))
    return httpx.AsyncClient(transport=transport, base_url="http://demo")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["stable", "candidate"])
@pytest.mark.parametrize("scenario", ["latency", "contract"])
async def test_all_revisions_pass_health(role: str, scenario: str) -> None:
    async with await _client(role, scenario) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "role": role, "scenario": scenario}


@pytest.mark.asyncio
async def test_candidate_breaks_contract_without_breaking_endpoint() -> None:
    payload = {"quantity": 2, "unit_price": 499, "currency": "inr"}
    async with await _client("stable", "contract") as stable:
        stable_response = await stable.post("/api/v1/quote", json=payload)
    async with await _client("candidate", "contract") as candidate:
        candidate_response = await candidate.post("/api/v1/quote", json=payload)

    assert stable_response.status_code == candidate_response.status_code == 200
    assert stable_response.json() == {"total": 998.0, "currency": "INR"}
    assert candidate_response.json() == {"amount": "998.00", "currency": "INR"}


@pytest.mark.asyncio
async def test_get_probe_exposes_the_same_contract_difference() -> None:
    async with await _client("stable", "contract") as stable:
        stable_response = await stable.get("/api/v1/quote?quantity=2")
    async with await _client("candidate", "contract") as candidate:
        candidate_response = await candidate.get("/api/v1/quote?quantity=2")

    assert stable_response.json() == {"total": 998.0, "currency": "INR"}
    assert candidate_response.json() == {"amount": "998.00", "currency": "INR"}


async def _burst(client: httpx.AsyncClient, requests: int = 12) -> float:
    started = time.perf_counter()
    responses = await asyncio.gather(
        *(client.post("/api/v1/quote", json={"quantity": 1}) for _ in range(requests))
    )
    assert all(response.status_code == 200 for response in responses)
    return time.perf_counter() - started


@pytest.mark.asyncio
async def test_candidate_has_repeatable_concurrent_latency_regression() -> None:
    async with await _client("stable", "latency") as stable:
        stable_elapsed = await _burst(stable)
    async with await _client("candidate", "latency") as candidate:
        candidate_elapsed = await _burst(candidate)

    # Stable completes one parallel wave (~30 ms); the candidate needs six
    # semaphore-limited waves (~720 ms). The broad threshold avoids CI jitter.
    assert candidate_elapsed > stable_elapsed * 5
    assert candidate_elapsed > 0.60


def test_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="ROLE must be one of"):
        create_app(role="unknown", scenario="latency")
