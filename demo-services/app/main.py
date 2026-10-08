"""Small deterministic services used by the ReleaseProof prototype.

The same image can represent a stable or candidate Cloud Run revision.  Its
behaviour is controlled by ``ROLE`` and ``SCENARIO`` so the verifier always
compares identical routes while observing one intentional regression.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

Role = Literal["stable", "candidate"]
Scenario = Literal["latency", "contract", "sideeffect", "money"]

# ISO 4217 currencies with no minor unit. Amounts in these are whole numbers,
# so rounding to two decimal places is wrong rather than merely redundant.
ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "XAF", "XOF"})

# A fixed service fee, present on both revisions. Its only purpose is to make
# the pre-rounding total fractional, so that the currency's decimal exponent
# actually changes the answer.
SERVICE_FEE_RATE = 0.075

# Per-request work in the latency scenario, identical on both revisions.
SERVICE_WORK_SECONDS = 0.05


class QuoteRequest(BaseModel):
    """Input shared by every revision and scenario."""

    quantity: int = Field(default=1, ge=1, le=100)
    unit_price: float = Field(default=499.0, gt=0, le=1_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)


def _validated_setting(name: str, supplied: str, allowed: set[str]) -> str:
    value = supplied.strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}; got {supplied!r}")
    return value


def create_app(
    role: str | None = None,
    scenario: str | None = None,
) -> FastAPI:
    """Create a configured demo service.

    Passing values explicitly keeps tests independent of process-level
    environment variables. Deployments normally use ROLE and SCENARIO.
    """

    configured_role: Role = _validated_setting(
        "ROLE", role or os.getenv("ROLE", "stable"), {"stable", "candidate"}
    )  # type: ignore[assignment]
    configured_scenario: Scenario = _validated_setting(
        "SCENARIO",
        scenario or os.getenv("SCENARIO", "latency"),
        {"latency", "contract", "sideeffect", "money"},
    )  # type: ignore[assignment]

    application = FastAPI(
        title="ReleaseProof demo service",
        version="1.0.0",
        description="A controlled stable/candidate target for ReleaseProof experiments.",
    )
    # The intentional bottleneck is local to one app instance. With two slots,
    # concurrent candidate requests queue in predictable waves.
    candidate_capacity = asyncio.Semaphore(2)

    @application.get("/health")
    async def health() -> dict[str, str]:
        # All demo revisions are deliberately healthy. A health check alone
        # therefore cannot discover either seeded regression.
        return {"status": "ok", "role": configured_role, "scenario": configured_scenario}

    @application.get("/metadata")
    async def metadata() -> dict[str, str]:
        return {"role": configured_role, "scenario": configured_scenario}

    async def build_quote(payload: QuoteRequest) -> dict[str, object]:
        total = round(payload.quantity * payload.unit_price, 2)

        if configured_scenario == "latency":
            # Both revisions do identical per-request work, so one request at a
            # time is indistinguishable between them and the smoke baseline
            # genuinely passes. The candidate differs only in how many requests
            # it can serve at once: raising concurrency gave it more work than
            # its resources can overlap, so requests queue. That contention is
            # invisible until requests actually overlap, which is the entire
            # reason a sequential smoke test cannot find this class of bug.
            started = time.perf_counter()
            if configured_role == "candidate":
                async with candidate_capacity:
                    await asyncio.sleep(SERVICE_WORK_SECONDS)
            else:
                await asyncio.sleep(SERVICE_WORK_SECONDS)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            return {
                "total": total,
                "currency": payload.currency.upper(),
                "processing_ms": elapsed_ms,
            }

        if configured_scenario == "contract":
            await asyncio.sleep(0.01)
            if configured_role == "candidate":
                # Seeded breaking change: field renamed and number converted to
                # a string. The endpoint remains available and healthy.
                return {
                    "amount": f"{total:.2f}",
                    "currency": payload.currency.upper(),
                }
            return {"total": total, "currency": payload.currency.upper()}

        if configured_scenario == "sideeffect":
            # The hardest class of regression. The response keeps its exact
            # shape and types, stays HTTP 200, and stays fast, so availability,
            # smoke, contract and latency checks all pass.
            #
            # The declared change is "apply 18% GST to the quote total", and the
            # candidate does that. It also applies an undeclared 15% discount
            # that no part of the diff mentions. Because GST raises the total
            # and the discount lowers it, the resulting total still looks about
            # right to a human reviewer; only `discount_applied` reveals the
            # undeclared behaviour.
            await asyncio.sleep(0.01)
            if configured_role == "candidate":
                tax_rate, discount = 0.18, 0.15
            else:
                tax_rate, discount = 0.0, 0.0
            return {
                "total": round(total * (1 + tax_rate) * (1 - discount), 2),
                "currency": payload.currency.upper(),
                "tax_rate": tax_rate,
                "discount_applied": discount,
                # Genuinely non-deterministic on every request from both roles.
                # A naive differ flags these; the adjudicator must not.
                "quote_id": uuid4().hex,
                "issued_at": datetime.now(timezone.utc).isoformat(),
            }

        if configured_scenario == "money":
            # Declared change: drop the currency table and round money in one
            # place. The candidate hardcodes two decimal places, which is right
            # for INR, USD and EUR — and wrong for every zero-decimal currency.
            #
            # Nothing in the fixed catalog varies `currency`: smoke, contract
            # and load all send the default, and the edge-input and payload
            # probes vary their own reserved parameter names. So every catalog
            # experiment compares INR against INR and sees two identical
            # responses. The regression is only reachable by a probe that
            # thinks to ask for a different currency.
            await asyncio.sleep(0.01)
            code = payload.currency.upper()
            charged = total * (1 + SERVICE_FEE_RATE)
            if configured_role == "candidate":
                decimals = 2
            else:
                decimals = 0 if code in ZERO_DECIMAL_CURRENCIES else 2
            return {
                "total": round(charged, decimals),
                "currency": code,
                "fee_rate": SERVICE_FEE_RATE,
            }

        # The setting validator makes this unreachable, but keeping an explicit
        # failure is safer if more scenarios are added later.
        raise HTTPException(status_code=500, detail="Unsupported scenario")

    @application.post("/api/v1/quote")
    async def quote(payload: QuoteRequest) -> dict[str, object]:
        return await build_quote(payload)

    @application.get("/api/v1/quote")
    async def quote_probe(
        quantity: int = 1,
        unit_price: float = 499.0,
        currency: str = "INR",
    ) -> dict[str, object]:
        """GET form used by the bounded ReleaseProof HTTP experiment runner."""
        payload = QuoteRequest(quantity=quantity, unit_price=unit_price, currency=currency)
        return await build_quote(payload)

    return application


app = create_app()
