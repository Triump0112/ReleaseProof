# ReleaseProof architecture

## Decision boundary

ReleaseProof separates probabilistic planning from deterministic execution:

| Layer | Responsibility | May decide release outcome? |
|---|---|---|
| Gemini planner | Interpret the diff, identify risk, choose allowlisted experiments, explain the hypothesis | No |
| Gemini Explorer author | Produce declarative GET/query probe specs using fixed assertion names | No |
| Experiment runner | Execute bounded paired probes against stable and candidate | No |
| Policy evaluator | Compare measured evidence with fixed thresholds | Yes |
| Evidence ledger | Preserve inputs, plan, measurements, thresholds, and verdict | No |

## Analysis sequence

1. The user supplies a service name, summary, diff, stable URL, candidate URL, request path, expected contract, and execution budget.
2. Baseline checks are fixed: health and smoke.
3. Gemini returns a schema-constrained plan containing up to two adaptive experiments.
4. In `explorer` mode, Gemini may additionally return up to two declarative probe specifications. In `guarded` mode the server discards them.
5. The server rejects unknown experiment identifiers and assertion operators, then reapplies the budget.
6. Stable and candidate receive the same warmups, requests, and trials.
7. The evaluator applies fixed compatibility, latency, and error-rate policies.
8. Any guarded blocking failure yields `BLOCK`; missing guarded evidence yields `INCONCLUSIVE`; otherwise the result is `PASS`.
9. Explorer findings are stored separately as `review_findings` and cannot alter that verdict.
10. The complete record is stored under a unique run identifier.

## Mode boundary

`Guarded Gate` is the default and the only release-blocking path. Gemini chooses from the approved experiment catalogue; fixed code executes the selection.

`AI Explorer` adds a declarative test DSL containing a name, rationale, hypothesis, query parameters, response paths and fixed assertion operators. The runner fixes the request method to `GET`, reuses the already-approved revision URL and request path, applies request/time limits, and owns every assertion implementation. Model-authored code, URLs, headers, credentials and thresholds are not representable in the schema. Explorer failures require review rather than blocking automatically.

## Bounded experiment catalog

- Contract compatibility
- Edge inputs
- Bounded concurrency/load
- Payload size
- Retry/idempotency
- Dependency timeout

Only health, smoke, contract, and bounded load are fully demonstrated in the first prototype. Unsupported evidence remains `INCONCLUSIVE`; the system never silently treats a skipped test as a pass.

`GET /api/risk-classes` exposes a broader, extensible taxonomy covering semantic behaviour, authentication, security, data integrity, external effects, rollback and observability. Every entry is marked `implemented`, `partial` or `planned`; listing a class does not claim the prototype can already test it.

## Production path

- Deploy the UI to Firebase Hosting or Cloud Run.
- Deploy the API and runner to Cloud Run using a dedicated service account.
- Use Vertex AI Gemini structured output for experiment planning.
- Read candidate revision metadata from the Cloud Run Admin API.
- Store evidence in Firestore and raw measurements in Cloud Storage.
- Export execution logs and custom metrics to Cloud Logging and Monitoring.
- Require authenticated tagged revision URLs and per-project allowlists.
- Integrate the final decision as a Cloud Deploy verification task rather than replacing Cloud Deploy.
