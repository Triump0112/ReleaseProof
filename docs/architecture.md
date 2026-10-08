# ReleaseProof architecture

## Decision boundary

ReleaseProof separates probabilistic planning from deterministic execution:

| Layer | Responsibility | May decide release outcome? |
|---|---|---|
| Gemini planner | Interpret the diff, identify risk, choose allowlisted experiments, explain the hypothesis | No |
| Experiment runner | Execute bounded paired probes against stable and candidate | No |
| Policy evaluator | Compare measured evidence with fixed thresholds | Yes |
| Evidence ledger | Preserve inputs, plan, measurements, thresholds, and verdict | No |

## Analysis sequence

1. The user supplies a service name, summary, diff, stable URL, candidate URL, request path, expected contract, and execution budget.
2. Baseline checks are fixed: health and smoke.
3. Gemini returns a schema-constrained plan containing up to two adaptive experiments.
4. The server rejects unknown experiment identifiers and reapplies the budget.
5. Stable and candidate receive the same warmups, requests, and trials.
6. The evaluator applies fixed compatibility, latency, and error-rate policies.
7. Any blocking failure yields `BLOCK`; missing/invalid evidence yields `INCONCLUSIVE`; otherwise the result is `PASS`.
8. The complete record is stored under a unique run identifier.

## Bounded experiment catalog

- Contract compatibility
- Edge inputs
- Bounded concurrency/load
- Payload size
- Retry/idempotency
- Dependency timeout

Only health, smoke, contract, and bounded load are fully demonstrated in the first prototype. Unsupported evidence remains `INCONCLUSIVE`; the system never silently treats a skipped test as a pass.

## Production path

- Deploy the UI to Firebase Hosting or Cloud Run.
- Deploy the API and runner to Cloud Run using a dedicated service account.
- Use Vertex AI Gemini structured output for experiment planning.
- Read candidate revision metadata from the Cloud Run Admin API.
- Store evidence in Firestore and raw measurements in Cloud Storage.
- Export execution logs and custom metrics to Cloud Logging and Monitoring.
- Require authenticated tagged revision URLs and per-project allowlists.
- Integrate the final decision as a Cloud Deploy verification task rather than replacing Cloud Deploy.

