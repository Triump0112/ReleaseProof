"""Discover the request interface a generated probe is allowed to vary.

Without this, the planner infers parameter names from the diff — which contains
the service's *internal* names, not its API. Observed on the deployed stack: a
diff reading `CURRENCY_DECIMALS[code]` produced a probe sending `code=JPY`,
which the service ignored, so the probe compared two default responses and
reported no difference. The reasoning was right and the request was wrong.

The stable revision is the authority on its own interface, so ask it. Anything
unavailable here degrades to an empty list, and the planner falls back to
inferring names as before.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

MAX_PARAMETERS = 25


def _operation_parameters(spec: dict[str, Any], request_path: str) -> list[str]:
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

    # Prefer the exact path, then any path whose templated form matches its
    # shape, so /items/{id} still resolves for a request to /items/42.
    candidates = [request_path]
    segments = request_path.strip("/").split("/")
    for declared in paths:
        declared_segments = declared.strip("/").split("/")
        if len(declared_segments) != len(segments):
            continue
        if all(
            d == s or (d.startswith("{") and d.endswith("}"))
            for d, s in zip(declared_segments, segments)
        ):
            candidates.append(declared)

    names: list[str] = []
    for candidate in candidates:
        operation = paths.get(candidate)
        if not isinstance(operation, dict):
            continue
        # Probes are GET-only, so only GET parameters are usable.
        get_operation = operation.get("get")
        if not isinstance(get_operation, dict):
            continue
        for parameter in get_operation.get("parameters") or []:
            if not isinstance(parameter, dict):
                continue
            if parameter.get("in") != "query":
                continue
            name = parameter.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        if names:
            break
    return names[:MAX_PARAMETERS]


async def discover_query_parameters(base_url: str, request_path: str) -> list[str]:
    """Best-effort query parameter names for `request_path` on `base_url`.

    Never raises: a probe without this is weaker, but a release gate that falls
    over because a service does not publish a schema is worse.
    """
    for document in ("/openapi.json", "/.well-known/openapi.json"):
        target = base_url.rstrip("/") + document
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False) as client:
                response = await client.get(target, headers={"User-Agent": "ReleaseProof/0.1"})
            if not response.is_success:
                continue
            names = _operation_parameters(response.json(), request_path)
            if names:
                return names
        except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
            continue
    return []
