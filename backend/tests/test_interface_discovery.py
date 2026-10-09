"""A generated probe can only vary inputs the service actually accepts.

The planner reads a diff, and a diff names internal variables. Observed on the
deployed stack: a diff containing `CURRENCY_DECIMALS[code]` produced a probe
sending `code=JPY`, which the endpoint ignored — so it compared two default
responses and reported no difference while appearing to have tested something.
"""

from __future__ import annotations

import httpx
import pytest

from app import interface
from app.interface import _operation_parameters, discover_query_parameters
from app.models import AnalysisMode, ExplorerAssertion
from app.planner import _coerce_explorer_spec, _ExplorerSpecResponse


SPEC = {
    "paths": {
        "/api/v1/quote": {
            "get": {
                "parameters": [
                    {"name": "quantity", "in": "query"},
                    {"name": "unit_price", "in": "query"},
                    {"name": "currency", "in": "query"},
                    {"name": "X-Trace", "in": "header"},
                ]
            },
            "post": {"parameters": [{"name": "ignored_on_post", "in": "query"}]},
        },
        "/items/{item_id}": {"get": {"parameters": [{"name": "expand", "in": "query"}]}},
    }
}


def test_only_get_query_parameters_are_offered():
    names = _operation_parameters(SPEC, "/api/v1/quote")
    assert names == ["quantity", "unit_price", "currency"]
    # Probes are GET-only and cannot set headers.
    assert "X-Trace" not in names
    assert "ignored_on_post" not in names


def test_templated_paths_resolve_for_a_concrete_request():
    assert _operation_parameters(SPEC, "/items/42") == ["expand"]


def test_unknown_path_yields_nothing_rather_than_guessing():
    assert _operation_parameters(SPEC, "/nowhere") == []


@pytest.mark.asyncio
async def test_discovery_degrades_quietly_when_no_schema_is_published(monkeypatch):
    """A gate must not fall over because a service publishes no schema."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        interface.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **{k: v for k, v in kwargs.items() if k != "transport"}),
    )
    assert await discover_query_parameters("https://service.example", "/api/v1/quote") == []


@pytest.mark.asyncio
async def test_discovery_reads_the_published_interface(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=SPEC)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        interface.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **{k: v for k, v in kwargs.items() if k != "transport"}),
    )
    names = await discover_query_parameters("https://service.example", "/api/v1/quote")
    assert names == ["quantity", "unit_price", "currency"]


def _raw(**overrides) -> _ExplorerSpecResponse:
    base = dict(
        name="probe",
        rationale="rationale text",
        hypothesis="hypothesis text",
        query_parameters=[],
        assertions=["candidate_success"],
    )
    base.update(overrides)
    return _ExplorerSpecResponse(**base)


def test_parameters_outside_the_published_interface_are_dropped():
    """The exact failure seen on the deployed stack."""
    spec = _coerce_explorer_spec(
        _raw(query_parameters={"code": "JPY", "charged": "100.50", "currency": "JPY"}),
        available_parameters=["quantity", "unit_price", "currency"],
    )
    # `code` and `charged` are the diff's internal names; the endpoint ignores them.
    assert spec.query_parameters == {"currency": "JPY"}


def test_parameters_are_kept_when_the_interface_is_unknown():
    """Without a published schema, the planner's inference is all there is."""
    spec = _coerce_explorer_spec(
        _raw(query_parameters={"code": "JPY"}),
        available_parameters=[],
    )
    assert spec.query_parameters == {"code": "JPY"}


def test_dropping_every_parameter_leaves_an_honestly_empty_probe():
    spec = _coerce_explorer_spec(
        _raw(query_parameters={"code": "JPY"}),
        available_parameters=["currency"],
    )
    assert spec.query_parameters == {}
    # Still a valid probe: it just compares the default request on both sides.
    assert ExplorerAssertion.CANDIDATE_SUCCESS in spec.assertions
