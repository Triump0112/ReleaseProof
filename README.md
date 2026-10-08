# ReleaseProof

ReleaseProof is a pre-traffic differential release gate for Cloud Run. It reads a code or configuration change, selects a bounded change-relevant experiment, compares a stable revision with a zero-traffic candidate, and produces a deterministic `PASS`, `BLOCK`, or `INCONCLUSIVE` verdict with replayable evidence.

The prototype demonstrates two regressions that ordinary health checks miss:

1. A concurrency change that causes repeatable candidate tail-latency degradation.
2. An API response change that removes a required field and changes its type.

The one-page project abstract is in [`output/pdf/ReleaseProof_Abstract.pdf`](output/pdf/ReleaseProof_Abstract.pdf).

## Core principle

Gemini may interpret the change, form a falsifiable hypothesis, and select experiments from an allowlisted catalog. It cannot set release thresholds, fabricate measurements, execute arbitrary commands, or override the verdict. The experiment runner and policy evaluator remain deterministic.

## Architecture

```text
React/Firebase-ready UI
        |
        v
Cloud Run FastAPI orchestrator
        |---- Vertex AI Gemini planner (optional locally)
        |---- bounded paired HTTP experiment runner
        |---- deterministic policy evaluator
        `---- JSON evidence ledger (Firestore-ready)
                    |
                    +---- stable Cloud Run revision
                    `---- tagged candidate revision, 0% traffic
```

## Run the complete live prototype

Docker Compose launches the frontend, API, and four controlled stable/candidate targets. In this mode the backend sends real paired HTTP probes; it does not use fixture measurements.

```bash
cd /Users/sdivyam/ReleaseProof
cp .env.example .env
docker compose up --build
```

Open `http://localhost:3000` and run both prepared changes. The API is also available at `http://localhost:8000/docs`.

The local stack defaults to the deterministic planner so it runs without cloud credentials. To enable Gemini, set `RELEASEPROOF_USE_VERTEX=true`, configure the Google Cloud variables, and provide Application Default Credentials to the backend environment. For a Cloud Run deployment, use a minimally privileged service account with Vertex AI access.

## Run without Docker

### API

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite development server proxies `/api` to port 8000. Without `VITE_USE_LIVE_TARGETS=true`, the API uses repeatable demonstration fixtures. This is useful for UI development; the Compose workflow is the real paired-service path.

### Demo targets

The services can be started individually from `demo-services` using the same image with different environment variables:

```bash
ROLE=stable SCENARIO=latency uvicorn app.main:app --port 8101
ROLE=candidate SCENARIO=latency uvicorn app.main:app --port 8102
```

See [`demo-services/README.md`](demo-services/README.md) for all four variants.

## API surface

- `GET /health` - service health
- `GET /api/catalog` - bounded experiment catalog
- `GET /api/scenarios` - deterministic UI/demo fixtures
- `POST /api/analyze` - plan and execute a release proof
- `GET /api/runs/{id}` - retrieve the immutable run record

The baseline always includes availability and a smoke probe. Gemini or the local fallback may add no more than two adaptive experiments within the configured request and time budgets.

## Verification

```bash
cd backend && python -m pytest
cd demo-services && python -m pytest
cd frontend && npm run build
```

Current verification status:

- Backend: 8 tests passing
- Demo services: 8 tests passing
- Frontend: production build passing
- PDF: one A4 page, rendered and visually inspected

For a real HTTP end-to-end check without Docker, run the script with an environment containing the backend requirements:

```bash
backend/.venv/bin/python scripts/verify_live_stack.py
```

It launches local stable/candidate processes, verifies both adaptive experiment choices, and requires both releases to be blocked from measured live evidence.

## Repository map

```text
ReleaseProof/
├── backend/           FastAPI planner, runner, evaluator, and evidence API
├── frontend/          React/Vite demonstration dashboard
├── demo-services/     Controlled stable and candidate HTTP revisions
├── docs/              Architecture, demo script, and PDF source
├── output/pdf/        Final one-page abstract
└── docker-compose.yml Complete local live stack
```

## Prototype boundaries

This is a hackathon prototype, not a production release controller. Its experiment catalog and thresholds are intentionally narrow. Live targets are restricted to HTTP(S), execution is request-bounded, and private targets are disabled unless explicitly enabled for the local Compose network. Production deployment would additionally require authenticated revision URLs, Firestore-backed immutable evidence, Cloud Logging/Monitoring integration, stronger statistical policies, and organization-specific release controls.
