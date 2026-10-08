# ReleaseProof

### ▶ [Live demo](https://releaseproof-ui-owsl25a4sa-el.a.run.app) · running on Cloud Run with Gemini on Vertex AI

**Every automated deployment gate in production use today needs real users to be exposed to the candidate first.** Canary analysis, progressive delivery, and telemetry-based rollback all begin working *after* traffic reaches the new revision. ReleaseProof decides before a single real request does.

It reads a change, probes a zero-traffic Cloud Run candidate against the current stable revision with identical requests, and returns a deterministic `PASS`, `BLOCK`, or `INCONCLUSIVE` with replayable evidence.

```
AI plans the investigation and explains the evidence.
Measured evidence makes the release decision.
```

## Two investigation modes

| Mode | What Gemini can do | Decision authority |
|---|---|---|
| **Guarded Gate** (default) | Select up to two server-owned experiments | Fixed policies may block the release |
| **AI Explorer** (optional) | Do everything in Guarded Gate, then author constrained GET/query probe specifications using fixed assertion operators | Findings are review-only and cannot change the guarded verdict |

Explorer does **not** execute model-authored Python, JavaScript or shell commands. Gemini supplies declarative data — query parameters, hypotheses, response paths and assertion names — and the server-owned runner interprets it. It cannot choose a URL, method, header, credential, threshold or verdict. This gives the prototype broader discovery without treating probabilistic test generation as a trusted deployment controller.

## What it catches that a passing test suite does not

| Scenario | Candidate behaviour | What conventional checks report |
|---|---|---|
| Concurrency regression | Tail latency collapses only when requests overlap | Health 200, smoke 200, single requests fast |
| API contract break | Required field renamed, number becomes string | Health 200, smoke 200, endpoint available |
| **Undeclared side effect** | Declared tax change applied **plus** an undeclared 15% discount | Health 200, smoke 200, identical shape, identical types, flat latency |

The third case is the one no shape-based check can reach. The response keeps every field name, every type, its status code and its latency profile. The only way to catch it is to reconcile what the candidate *actually does* against what its change *said it would do*.

## How the decision is made

```text
         change (summary + diff)
                  |
    ┌─────────────┴─────────────┐
    │  Gemini: risk hypothesis  │   plans, never decides
    │  + bounded experiment plan│
    └─────────────┬─────────────┘
                  |
      identical paired probes
      ┌───────────┴───────────┐
   stable revision      candidate revision (0% traffic)
      └───────────┬───────────┘
                  |
    ┌─────────────┴──────────────┐
    │ deterministic delta extract│   no model involved
    └─────────────┬──────────────┘
                  |
    ┌─────────────┴──────────────┐
    │ Gemini: explained / noise /│   classifies, must cite the diff
    │          unexplained       │
    └─────────────┬──────────────┘
                  |
    ┌─────────────┴──────────────┐
    │ fixed policy → PASS/BLOCK  │   owns the verdict
    └─────────────┬──────────────┘
                  |
          evidence ledger
```

**Gemini may** interpret the change, choose allowlisted experiments, classify an observed difference, explain the evidence, and—only in AI Explorer—author a constrained declarative probe.
**Gemini may not** invent a measurement, supply executable source code, select an arbitrary target or HTTP method, choose a threshold, suppress a failed result, or override the verdict.

Classification requires a citation. A delta the model calls "explained" without quoting supporting diff evidence is downgraded to *unexplained*, and a delta it fails to classify at all is treated as *unexplained*. The failure direction is a blocked release, never a silently shipped regression. With Vertex disabled the system still runs, using a deliberately conservative offline classifier.

## Intent reconciliation

For every release, the orchestrator enumerates field-level differences between the paired responses deterministically, then asks Gemini to account for each one:

| Field | Stable | Candidate | Assessment |
|---|---|---|---|
| `total` | `499.0` | `500.5` | Declared — diff adds `tax_rate = 0.18` |
| `tax_rate` | `0.0` | `0.18` | Declared — diff adds `tax_rate = 0.18` |
| `quote_id` | `7f3a9c21…` | `c08e55a1…` | Non-deterministic — differs between any two calls |
| `issued_at` | `09:14:02` | `09:14:05` | Non-deterministic — differs between any two calls |
| **`discount_applied`** | **`0.0`** | **`0.15`** | **Undeclared — nothing in the change mentions discounts** |

`BLOCK`. Note that the net total still looks plausible: the declared tax raises it, the undeclared discount lowers it, and the result lands within two rupees of the original. That is precisely why code review and threshold alerts miss this class of bug.

Distinguishing a real regression from ordinary non-determinism is the hard part of differential testing — Twitter's Diffy needed a third live instance to subtract noise. Here it is a language problem, which is what makes it a good fit for a model rather than a heuristic.

## What is deployed, and what is only scaffolding

The demo runs ten Cloud Run services, and they are not all the same kind of thing.

**ReleaseProof itself is two services:** the dashboard and the orchestrator API. The API calls Gemini on Vertex AI — no model is self-hosted.

**The other eight are the application under test**, not part of the product: four stable/candidate pairs, one per scenario, each candidate carrying a single planted regression. They exist so the demo has something to point at and a bug that is guaranteed to be there every run.

```
          releaseproof-ui ──► releaseproof-api ──► Vertex AI (Gemini)
                                     │              plans the investigation
                                     │
                         identical paired probes
                         ┌───────────┴───────────┐
                         ▼                       ▼
                 stable revision         candidate revision
               (serving production)        (0% traffic)
```

In real use those eight disappear. A team deploys the two ReleaseProof services once and points them at their own revisions — their live service and their tagged candidate holding zero traffic. That is what the `stable_url` and `candidate_url` fields on `/api/analyze` are for; the demo simply pre-fills them.

## Run it

### Deployed (Cloud Run)

No local Docker required; builds happen in Cloud Build. Runs as-is from Cloud Shell.

```bash
./scripts/deploy_cloud_run.sh YOUR_PROJECT_ID asia-south1
```

Deploys all ten services, discovering and wiring revision URLs automatically. Vertex AI planning is enabled, probing of private addresses is disabled, and everything scales to zero so an idle deployment costs nothing. The script prints the UI URL when it finishes.

Set `MIN_INSTANCES=1` to pin instances warm while recording a demo, and `./scripts/teardown_cloud_run.sh` removes the whole stack afterwards.

Verify the deployment actually blocks a bad candidate:

```bash
./scripts/smoke_deployed.sh "$API_URL" "$STABLE_URL" "$CANDIDATE_URL"
```

### Locally (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:3000`; API docs at `http://localhost:8000/docs`. This path sends **real paired HTTP probes** to the demo revisions — it does not replay fixtures. Set `RELEASEPROOF_USE_VERTEX=true` with Application Default Credentials to enable Gemini; otherwise the offline planner and classifier are used.

### Without Docker

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

Without `VITE_USE_LIVE_TARGETS=true` the API serves repeatable fixtures, which is useful for UI work. Compose is the real paired-service path.

## API

- `GET  /health` — service health
- `GET  /api/catalog` — bounded experiment catalog
- `GET  /api/risk-classes` — honest coverage map (`implemented`, `partial`, `planned`)
- `GET  /api/scenarios` — demonstration fixtures
- `POST /api/analyze` — plan, execute, and decide
- `GET  /api/runs/{id}` — immutable run record

Health and smoke always execute. Intent reconciliation runs on the smoke baseline, so every release is checked for undeclared behaviour even when the planner selects no adaptive experiment. `analysis_mode` defaults to `guarded`; setting it to `explorer` adds up to two review-only declarative probes within the same request and time budget.

## Verification

```bash
cd backend       && python -m pytest        # 54 tests
cd demo-services && python -m pytest        # 24 tests
cd frontend      && npm run build
python scripts/verify_live_stack.py         # real HTTP, all four scenarios
```

`verify_live_stack.py` starts genuine stable/candidate processes and checks the properties the demo's claims depend on:

- Scenarios claiming a baseline blind spot must show health and smoke **passing**. A regression ordinary verification would have caught demonstrates nothing, so that fails the check rather than quietly weakening the story.
- Randomly generated `quote_id` and `issued_at` values must not be mistaken for regressions.
- The same change run through both modes must genuinely disagree — guarded finding nothing, explorer surfacing the difference.

The generated-probe tests are mutation-verified: making the runner discard the model's authored input fails them. Without that, a stored fixture that merely happens to differ would make a probe look effective even if its inputs were ignored.

## How this relates to existing tools

ReleaseProof does not claim deployment verification is an unsolved problem. Cloud Deploy already supports verification jobs, canary phases, and rollback. The contribution is narrower and stated plainly:

| | Established tooling | ReleaseProof |
|---|---|---|
| Kayenta, Flagger, Argo Rollouts | Statistical baseline-vs-canary analysis **after traffic** | Decides **before** traffic |
| Diffy, GoReplay | Response diffing, but driven by **captured real traffic** | Synthetic probes, works on a **zero-traffic** candidate |
| Pact, oasdiff, Schemathesis | **Spec-level** breaking-change detection | **Runtime** behaviour of the deployed candidate |
| CloudBees Smart Tests | LLM picks which **existing tests** to run | LLM reconciles **observed behaviour** against declared intent |

The long-term shape of this is a Cloud Deploy verification task, not a replacement for Cloud Deploy.

## Prototype boundaries

A hackathon prototype, not a production release controller. The experiment catalog and thresholds are intentionally narrow. The risk-classes endpoint explicitly separates implemented, partial and planned coverage; it is a taxonomy, not a claim that all failures are known. Targets are restricted to HTTP(S), execution is request-bounded, and private targets are disabled unless explicitly enabled for the local Compose network. Explorer is GET-only and review-only. Production use would additionally need a hardened workload sandbox before allowing model-authored source code, authenticated revision discovery, Firestore-backed immutable evidence, Cloud Logging and Monitoring integration, stronger statistical policies, and organization-specific calibration.

## Repository map

```text
ReleaseProof/
├── backend/app/adjudicator.py   intent reconciliation (deltas → classification → policy)
├── backend/app/planner.py       Gemini experiment planning, schema-constrained
├── backend/app/executor.py      guarded runner + fixed interpreter for Explorer specs
├── backend/app/ledger.py        replayable evidence records
├── frontend/                    React dashboard
├── demo-services/               controlled stable/candidate revisions
├── scripts/deploy_cloud_run.sh  one-command deployment
└── scripts/verify_live_stack.py real-HTTP end-to-end verification
```
