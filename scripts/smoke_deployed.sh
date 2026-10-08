#!/usr/bin/env bash
# Verify a deployed ReleaseProof stack end to end.
#
#   ./scripts/smoke_deployed.sh API_URL STABLE_URL CANDIDATE_URL
#
# Runs a real paired analysis against the deployed demo revisions and asserts
# the orchestrator returns BLOCK. Exits non-zero if the gate fails to block,
# so this is safe to wire into CI.

set -euo pipefail

API_URL="${1:?usage: $0 API_URL STABLE_URL CANDIDATE_URL}"
STABLE_URL="${2:?usage: $0 API_URL STABLE_URL CANDIDATE_URL}"
CANDIDATE_URL="${3:?usage: $0 API_URL STABLE_URL CANDIDATE_URL}"

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "${RESPONSE_FILE}"' EXIT

echo "==> Health"
curl -fsS "${API_URL}/health" && echo

echo "==> Catalog"
curl -fsS "${API_URL}/api/catalog" | head -c 160 && echo "..."

echo "==> Demo targets configured on the API"
curl -fsS "${API_URL}/api/demo-targets" | head -c 400 && echo

echo "==> Paired analysis (concurrency regression) - this takes ~30s"
curl -fsS -X POST "${API_URL}/api/analyze" \
  -H 'Content-Type: application/json' \
  -d "{
    \"service_name\": \"checkout-api\",
    \"summary\": \"Increase Cloud Run concurrency from 4 to 32\",
    \"diff\": \"- containerConcurrency: 4\\n+ containerConcurrency: 32\",
    \"stable_url\": \"${STABLE_URL}\",
    \"candidate_url\": \"${CANDIDATE_URL}\",
    \"request_path\": \"/api/v1/quote\"
  }" > "${RESPONSE_FILE}"

# Quoted heredoc: the shell performs no substitution, so the Python source
# arrives exactly as written. The response is read from a file because stdin
# would otherwise be consumed by the JSON itself.
RESPONSE_FILE="${RESPONSE_FILE}" python3 <<'PY'
import json
import os
import sys

with open(os.environ["RESPONSE_FILE"]) as handle:
    record = json.load(handle)

ledger = record["ledger"]
plan = ledger["plan"]
planner = plan["planner"]

print(f"  run_id  : {ledger['run_id']}")
print(f"  planner : {planner}")
print(f"  verdict : {ledger['verdict']}")

states = {True: "PASS", False: "FAIL", None: "INCONCLUSIVE"}
for item in ledger["evidence"]:
    state = states[item["passed"]]
    print(f"    [{state:12}] {item['title']}: {item['explanation'][:110]}")

problems = []
if ledger["verdict"] != "BLOCK":
    problems.append(f"expected verdict BLOCK, got {ledger['verdict']}")

if planner != "vertex_gemini":
    note = plan.get("planner_note") or "no reason reported"
    problems.append(
        "planner fell back to "
        f"{planner} ({note}). Gemini is NOT in the loop; grant "
        "roles/aiplatform.user to the API service account and redeploy."
    )

print()
if problems:
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    sys.exit(1)

print("  OK: deployed stack blocked the regressed candidate, planned by Gemini.")
PY
