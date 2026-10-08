# ReleaseProof demo services

Controlled HTTP services for demonstrating why a passing health check is not
enough to approve a release. The same FastAPI application is configured with:

- `ROLE=stable|candidate`
- `SCENARIO=latency|contract`

Every service exposes:

- `GET /health` — always returns HTTP 200 for a valid configuration.
- `GET /metadata` — reports the configured role and scenario.
- `POST /api/v1/quote` — accepts `quantity`, `unit_price`, and `currency`.
- `GET /docs` — interactive OpenAPI documentation.

## Seeded scenarios

### A. Concurrent tail-latency regression

The stable and candidate services return the same response contract. Stable
requests complete concurrently after about 30 ms. The candidate has only two
processing slots and takes about 120 ms per wave. A single request succeeds,
but a burst creates predictable queuing and a much higher p95 latency.

| Revision | Local URL | Expected result |
| --- | --- | --- |
| Stable | `http://localhost:8101` | Low concurrent latency |
| Candidate | `http://localhost:8102` | High concurrent tail latency |

### B. Response-contract regression

Both revisions return HTTP 200, but the candidate renames the numeric `total`
field to `amount` and changes its type to a string.

| Revision | Local URL | Response shape |
| --- | --- | --- |
| Stable | `http://localhost:8201` | `{"total": 499.0, "currency": "INR"}` |
| Candidate | `http://localhost:8202` | `{"amount": "499.00", "currency": "INR"}` |

## Run with Docker Compose

```bash
docker compose up --build
```

Check that every revision is nominally healthy:

```bash
curl http://localhost:8101/health
curl http://localhost:8102/health
curl http://localhost:8201/health
curl http://localhost:8202/health
```

Compare the contract scenario:

```bash
curl -s -X POST http://localhost:8201/api/v1/quote \
  -H 'content-type: application/json' \
  -d '{"quantity":2,"unit_price":499,"currency":"INR"}'

curl -s -X POST http://localhost:8202/api/v1/quote \
  -H 'content-type: application/json' \
  -d '{"quantity":2,"unit_price":499,"currency":"INR"}'
```

Stop the services with `docker compose down`.

## Run directly

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ROLE=stable SCENARIO=latency uvicorn app.main:app --port 8101
```

Run the automated checks:

```bash
pytest -q
```

The latency test intentionally sends 12 simultaneous in-process requests and
checks that the candidate is at least five times slower than the stable
revision. Its absolute lower bound is deliberately broad to tolerate CI jitter.
