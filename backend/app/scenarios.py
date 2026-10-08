from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Budget, ChangeInput, ExpectedContract, ScenarioSummary


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
        },
    },
}


def scenario_summaries() -> list[ScenarioSummary]:
    return [profile["summary"] for profile in SCENARIO_PROFILES.values()]


def scenario_results(scenario_id: str) -> dict[str, Any] | None:
    profile = SCENARIO_PROFILES.get(scenario_id)
    return deepcopy(profile["results"]) if profile else None
