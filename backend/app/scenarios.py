from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import AnalysisMode, Budget, ChangeInput, ExpectedContract, ScenarioSummary


SCENARIO_PROFILES: dict[str, dict[str, Any]] = {
    "concurrency-regression": {
        "summary": ScenarioSummary(
            id="concurrency-regression",
            title="Concurrency regression",
            description="Both revisions are healthy, but the candidate develops high tail latency and errors under concurrency.",
            suggested_change=ChangeInput(
                service_name="checkout-api",
                summary="Increase Cloud Run concurrency from 4 to 32",
                diff="- containerConcurrency: 4\n+ containerConcurrency: 32",
                scenario_id="concurrency-regression",
                request_path="/checkout",
                budget=Budget(),
            ),
        ),
        "results": {
            "health_check": {
                "stable": {"status": 200, "latencies": [42, 45, 43], "errors": 0, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [43, 44, 46], "errors": 0, "body": {"status": "ok"}},
            },
            "api_smoke": {
                "stable": {"status": 200, "latencies": [78, 82, 80], "errors": 0, "body": {"total": 499, "currency": "INR"}},
                "candidate": {"status": 200, "latencies": [81, 86, 83], "errors": 0, "body": {"total": 499, "currency": "INR"}},
            },
            "bounded_load": {
                "stable": {"status": 200, "latencies": [171, 180, 185], "errors": 1, "requests": 480, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [560, 590, 615], "errors": 19, "requests": 480, "body": {"status": "degraded"}},
            },
            "ai_explorer": {
                "stable": {"status": 200, "latencies": [80, 84, 82], "errors": 0, "body": {"total": 499, "currency": "INR"}},
                "candidate": {"status": 200, "latencies": [82, 86, 84], "errors": 0, "body": {"total": 499, "currency": "INR"}},
            },
        },
    },
    "api-contract-break": {
        "summary": ScenarioSummary(
            id="api-contract-break",
            title="API contract break",
            description="The candidate is healthy but renames a required numeric response field and returns it as a string.",
            suggested_change=ChangeInput(
                service_name="pricing-api",
                summary="Rename total to amount in the checkout response",
                diff='- "total": 499\n+ "amount": "499"',
                scenario_id="api-contract-break",
                request_path="/price",
                expected_contract=ExpectedContract(required_fields={"total": "number", "currency": "string"}),
                budget=Budget(),
            ),
        ),
        "results": {
            "health_check": {
                "stable": {"status": 200, "latencies": [39, 41, 40], "errors": 0, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [40, 42, 41], "errors": 0, "body": {"status": "ok"}},
            },
            "api_smoke": {
                "stable": {"status": 200, "latencies": [70, 73, 71], "errors": 0, "body": {"total": 499, "currency": "INR"}},
                "candidate": {"status": 200, "latencies": [72, 75, 73], "errors": 0, "body": {"amount": "499", "currency": "INR"}},
            },
            "contract_compatibility": {
                "stable": {"status": 200, "latencies": [70, 73, 71], "errors": 0, "body": {"total": 499, "currency": "INR"}},
                "candidate": {"status": 200, "latencies": [72, 75, 73], "errors": 0, "body": {"amount": "499", "currency": "INR"}},
            },
            "ai_explorer": {
                "stable": {"status": 200, "latencies": [71, 74, 72], "errors": 0, "body": {"total": 499, "currency": "INR"}},
                "candidate": {"status": 200, "latencies": [73, 76, 74], "errors": 0, "body": {"amount": "499", "currency": "INR"}},
            },
        },
    },
    "undeclared-side-effect": {
        "summary": ScenarioSummary(
            id="undeclared-side-effect",
            title="Undeclared side effect",
            description=(
                "The candidate implements the declared tax change correctly and also applies "
                "an undeclared discount. Shape, types, status and latency are all unchanged."
            ),
            suggested_change=ChangeInput(
                service_name="pricing-api",
                summary="Apply 18% GST to the quote total",
                diff=(
                    "-    total = subtotal\n"
                    "+    tax_rate = 0.18\n"
                    "+    total = subtotal * (1 + tax_rate)"
                ),
                scenario_id="undeclared-side-effect",
                request_path="/api/v1/quote",
                budget=Budget(),
            ),
        ),
        "results": {
            "health_check": {
                "stable": {"status": 200, "latencies": [38, 40, 39], "errors": 0, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [39, 41, 40], "errors": 0, "body": {"status": "ok"}},
            },
            # Identical shape, identical types, no removed fields, comparable
            # latency. Every conventional check passes; only reconciling the
            # observed deltas against the declared change finds the discount.
            "api_smoke": {
                "stable": {
                    "status": 200,
                    "latencies": [68, 71, 70],
                    "errors": 0,
                    "body": {
                        "total": 499.0,
                        "currency": "INR",
                        "tax_rate": 0.0,
                        "discount_applied": 0.0,
                        "quote_id": "7f3a9c21d4b8",
                        "issued_at": "2026-10-08T09:14:02+00:00",
                    },
                },
                "candidate": {
                    "status": 200,
                    "latencies": [69, 72, 71],
                    "errors": 0,
                    "body": {
                        "total": 500.5,
                        "currency": "INR",
                        "tax_rate": 0.18,
                        "discount_applied": 0.15,
                        "quote_id": "c08e55a1b7f2",
                        "issued_at": "2026-10-08T09:14:05+00:00",
                    },
                },
            },
            "ai_explorer": {
                "stable": {
                    "status": 200, "latencies": [68, 71, 70], "errors": 0,
                    "body": {"total": 499.0, "currency": "INR", "tax_rate": 0.0, "discount_applied": 0.0},
                },
                "candidate": {
                    "status": 200, "latencies": [69, 72, 71], "errors": 0,
                    "body": {"total": 500.5, "currency": "INR", "tax_rate": 0.18, "discount_applied": 0.15},
                },
            },
        },
    },
    "currency-rounding": {
        "summary": ScenarioSummary(
            id="currency-rounding",
            title="Only a generated input finds it",
            description=(
                "The candidate rounds every currency to two decimal places. Every catalog experiment "
                "sends the default currency and sees two identical responses, so guarded mode passes. "
                "Only a probe that asks for a zero-decimal currency separates the revisions."
            ),
            suggested_change=ChangeInput(
                service_name="pricing-api",
                summary="Centralise money rounding and drop the per-currency decimal table",
                diff=(
                    "-    exponent = CURRENCY_DECIMALS[code]\n"
                    "-    total = round(charged, exponent)\n"
                    "+    # one rounding helper for every currency\n"
                    "+    total = round(charged, 2)"
                ),
                scenario_id="currency-rounding",
                request_path="/api/v1/quote",
                analysis_mode=AnalysisMode.EXPLORER,
                budget=Budget(),
            ),
        ),
        "results": {
            "health_check": {
                "stable": {"status": 200, "latencies": [37, 39, 38], "errors": 0, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [38, 40, 39], "errors": 0, "body": {"status": "ok"}},
            },
            # Every fixed experiment sends the endpoint's default currency, so
            # stable and candidate agree exactly. This is what makes guarded
            # mode pass: the evidence genuinely shows no difference.
            "api_smoke": {
                "stable": {
                    "status": 200, "latencies": [66, 69, 68], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
                "candidate": {
                    "status": 200, "latencies": [67, 70, 69], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
            },
            "contract_compatibility": {
                "stable": {
                    "status": 200, "latencies": [66, 69, 68], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
                "candidate": {
                    "status": 200, "latencies": [67, 70, 69], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
            },
            "edge_inputs": {
                # The edge probe varies its own reserved parameter, never the
                # currency, so it also compares INR against INR.
                "stable": {
                    "status": 200, "latencies": [70, 73, 72], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
                "candidate": {
                    "status": 200, "latencies": [71, 74, 73], "errors": 0,
                    "body": {"total": 536.42, "currency": "INR", "fee_rate": 0.075},
                },
            },
            # The generated probe asks for JPY, which has no minor unit. The
            # stable revision rounds to whole yen; the candidate does not.
            "ai_explorer": {
                "stable": {
                    "status": 200, "latencies": [67, 70, 69], "errors": 0,
                    "body": {"total": 536.0, "currency": "JPY", "fee_rate": 0.075},
                },
                "candidate": {
                    "status": 200, "latencies": [68, 71, 70], "errors": 0,
                    "body": {"total": 536.42, "currency": "JPY", "fee_rate": 0.075},
                },
            },
        },
    },
    "healthy-release": {
        "summary": ScenarioSummary(
            id="healthy-release",
            title="Healthy release",
            description="A safe implementation-only change with equivalent behaviour.",
            suggested_change=ChangeInput(
                service_name="catalog-api",
                summary="Refactor response serialization without changing the API",
                diff="- legacy_serializer(item)\n+ typed_serializer(item)",
                scenario_id="healthy-release",
                request_path="/items",
                budget=Budget(),
            ),
        ),
        "results": {
            "health_check": {
                "stable": {"status": 200, "latencies": [40, 42, 41], "errors": 0, "body": {"status": "ok"}},
                "candidate": {"status": 200, "latencies": [40, 43, 41], "errors": 0, "body": {"status": "ok"}},
            },
            "api_smoke": {
                "stable": {"status": 200, "latencies": [75, 78, 77], "errors": 0, "body": {"items": [1, 2]}},
                "candidate": {"status": 200, "latencies": [76, 79, 77], "errors": 0, "body": {"items": [1, 2]}},
            },
            "contract_compatibility": {
                "stable": {"status": 200, "latencies": [75, 78, 77], "errors": 0, "body": {"items": [1, 2]}},
                "candidate": {"status": 200, "latencies": [76, 79, 77], "errors": 0, "body": {"items": [1, 2]}},
            },
            "edge_inputs": {
                "stable": {"status": 200, "latencies": [82, 85, 84], "errors": 0, "body": {"items": []}},
                "candidate": {"status": 200, "latencies": [83, 86, 85], "errors": 0, "body": {"items": []}},
            },
            "ai_explorer": {
                "stable": {"status": 200, "latencies": [82, 85, 84], "errors": 0, "body": {"items": []}},
                "candidate": {"status": 200, "latencies": [83, 86, 85], "errors": 0, "body": {"items": []}},
            },
        },
    },
}


def scenario_summaries() -> list[ScenarioSummary]:
    return [profile["summary"] for profile in SCENARIO_PROFILES.values()]


def scenario_results(scenario_id: str) -> dict[str, Any] | None:
    profile = SCENARIO_PROFILES.get(scenario_id)
    return deepcopy(profile["results"]) if profile else None
