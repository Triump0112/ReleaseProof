# ReleaseProof API

FastAPI prototype for evidence-locked, pre-traffic differential release verification. It compares stable and candidate revisions with a fixed baseline plus at most two adaptively selected experiments, then computes a deterministic `PASS`, `BLOCK`, or `INCONCLUSIVE` verdict. Optional AI Explorer probes are recorded as review-only evidence and cannot change that verdict.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the generated API documentation.

## Demonstration flow

1. `GET /api/scenarios`
2. Take a scenario's `suggested_change` object.
3. `POST /api/analyze` with that object.
4. Inspect the structured plan, paired evidence, deterministic verdict, and `run_id`.
5. Replay the stored record with `GET /api/runs/{run_id}`.

The included scenarios demonstrate:

- `concurrency-regression`: selects bounded load and returns `BLOCK`.
- `api-contract-break`: selects contract compatibility and returns `BLOCK`.
- `healthy-release`: returns `PASS`.

## Optional Vertex AI Gemini planner

The API works offline with a deterministic planner. To enable the Gemini planner using Application Default Credentials:

```bash
export RELEASEPROOF_USE_VERTEX=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export RELEASEPROOF_GEMINI_MODEL=gemini-2.5-flash
```

In default `guarded` mode, Gemini may select only experiments from the server-owned catalogue. With `analysis_mode: "explorer"`, it may also author constrained declarative GET/query probes from fixed assertion operators. Its JSON output is schema-validated and clamped to the supplied budget. If planning fails, the service records the reason and safely falls back to deterministic planning. Gemini never chooses target URLs, HTTP methods, headers, credentials, executable code, thresholds or verdicts.

## Safety and evidence

- No shell commands or submitted code are executed.
- Live mode only makes bounded HTTP GET probes.
- AI Explorer evidence is always non-blocking and explicitly marked `review_only`.
- Private and metadata targets are denied unless local development explicitly sets `RELEASEPROOF_ALLOW_PRIVATE_TARGETS=true`.
- Evidence is written atomically as versioned JSON under `data/runs` (override with `RELEASEPROOF_LEDGER_DIR`).
- The prototype caps adaptive experiments, duration, trials and requests through validated input fields.

## Test

```bash
pytest
```
