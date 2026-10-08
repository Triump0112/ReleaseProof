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

echo "==> Health"
curl -fsS "${API_URL}/health" && echo

echo "==> Catalog"
curl -fsS "${API_URL}/api/catalog" | head -c 200 && echo

echo "==> Paired analysis (concurrency regression)"
RESPONSE=$(curl -fsS -X POST "${API_URL}/api/analyze" \
  -H 'Content-Type: application/json' \
  -d "{
    \"service_name\": \"checkout-api\",
    \"summary\": \"Increase Cloud Run concurrency from 4 to 32\",
    \"diff\": \"- containerConcurrency: 4\\n+ containerConcurrency: 32\",
    \"stable_url\": \"${STABLE_URL}\",
    \"candidate_url\": \"${CANDIDATE_URL}\",
    \"request_path\": \"/api/v1/quote\"
  }")

echo "${RESPONSE}" | python3 -c '
import json, sys
record = json.load(sys.stdin)
ledger = record["ledger"]
print(f"  run_id : {ledger[\"run_id\"]}")
print(f"  planner: {ledger[\"plan\"][\"planner\"]}")
print(f"  verdict: {ledger[\"verdict\"]}")
for item in ledger["evidence"]:
    state = {True: "PASS", False: "FAIL", None: "INCONCLUSIVE"}[item["passed"]]
    print(f"    [{state:12}] {item[\"title\"]}: {item[\"explanation\"]}")
if ledger["verdict"] != "BLOCK":
    sys.exit(f"EXPECTED BLOCK, GOT {ledger[\"verdict\"]}")
if ledger["plan"]["planner"] != "vertex_gemini":
    print(f"  WARNING: planner was {ledger[\"plan\"][\"planner\"]}, not vertex_gemini.")
    print("           Check Vertex AI permissions on the API service account.")
print("  OK: deployed stack blocked the regressed candidate.")
'
