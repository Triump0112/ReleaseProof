#!/usr/bin/env bash
# Deploy the complete ReleaseProof stack to Cloud Run.
#
# Builds from source with Cloud Build, so no local Docker is required.
# Runs fine from Cloud Shell, where gcloud and credentials already exist.
#
#   ./scripts/deploy_cloud_run.sh YOUR_PROJECT_ID [REGION]
#
# Deploys six services: four demo revisions (stable/candidate x latency/contract),
# the orchestrator API, and the UI. Demo URLs are discovered and injected
# automatically, so nothing needs editing by hand.

set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-asia-south1}"
GEMINI_MODEL="${RELEASEPROOF_GEMINI_MODEL:-gemini-2.5-flash}"
# Vertex location is deliberately separate from the Cloud Run region: not every
# region serves Gemini. Override only if you know your region has the model.
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"

if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no project. Usage: $0 PROJECT_ID [REGION]" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "==> Project: ${PROJECT}   Region: ${REGION}"
gcloud config set project "${PROJECT}" >/dev/null

echo "==> Enabling required APIs (idempotent)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  --project "${PROJECT}" >/dev/null

# ---------------------------------------------------------------------------
# 1. Demo revisions. Public so the orchestrator can probe them over HTTPS;
#    they serve only synthetic demo data.
# ---------------------------------------------------------------------------
deploy_demo() {
  local name="$1" role="$2" scenario="$3"
  echo "==> Deploying demo service: ${name} (role=${role}, scenario=${scenario})"
  gcloud run deploy "${name}" \
    --source ./demo-services \
    --region "${REGION}" \
    --platform managed \
    --allow-unauthenticated \
    --set-env-vars "ROLE=${role},SCENARIO=${scenario}" \
    --cpu 1 --memory 512Mi \
    --min-instances 1 \
    --max-instances 4 \
    --quiet >/dev/null
}

url_of() {
  gcloud run services describe "$1" --region "${REGION}" --format='value(status.url)'
}

deploy_demo releaseproof-stable-latency    stable    latency
deploy_demo releaseproof-candidate-latency candidate latency
deploy_demo releaseproof-stable-contract   stable    contract
deploy_demo releaseproof-candidate-contract candidate contract
deploy_demo releaseproof-stable-sideeffect stable    sideeffect
deploy_demo releaseproof-candidate-sideeffect candidate sideeffect
deploy_demo releaseproof-stable-money      stable    money
deploy_demo releaseproof-candidate-money   candidate money

STABLE_LATENCY_URL="$(url_of releaseproof-stable-latency)"
CANDIDATE_LATENCY_URL="$(url_of releaseproof-candidate-latency)"
STABLE_CONTRACT_URL="$(url_of releaseproof-stable-contract)"
CANDIDATE_CONTRACT_URL="$(url_of releaseproof-candidate-contract)"
STABLE_SIDEEFFECT_URL="$(url_of releaseproof-stable-sideeffect)"
CANDIDATE_SIDEEFFECT_URL="$(url_of releaseproof-candidate-sideeffect)"
STABLE_MONEY_URL="$(url_of releaseproof-stable-money)"
CANDIDATE_MONEY_URL="$(url_of releaseproof-candidate-money)"

# ---------------------------------------------------------------------------
# 2. Orchestrator. Vertex AI planning is ON here; private targets stay OFF so
#    the runner cannot be pointed at internal addresses.
# ---------------------------------------------------------------------------
echo "==> Deploying orchestrator API"
# Revision URLs are runtime configuration on this service, and the UI reads them
# from /api/demo-targets. Keeping them out of the UI build means the frontend
# image does not depend on build arguments reaching a Docker build.
gcloud run deploy releaseproof-api \
  --source ./backend \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "^@^RELEASEPROOF_USE_VERTEX=true@GOOGLE_CLOUD_PROJECT=${PROJECT}@GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}@RELEASEPROOF_GEMINI_MODEL=${GEMINI_MODEL}@RELEASEPROOF_ALLOW_PRIVATE_TARGETS=false@RELEASEPROOF_STABLE_LATENCY_URL=${STABLE_LATENCY_URL}@RELEASEPROOF_CANDIDATE_LATENCY_URL=${CANDIDATE_LATENCY_URL}@RELEASEPROOF_STABLE_CONTRACT_URL=${STABLE_CONTRACT_URL}@RELEASEPROOF_CANDIDATE_CONTRACT_URL=${CANDIDATE_CONTRACT_URL}@RELEASEPROOF_STABLE_SIDEEFFECT_URL=${STABLE_SIDEEFFECT_URL}@RELEASEPROOF_CANDIDATE_SIDEEFFECT_URL=${CANDIDATE_SIDEEFFECT_URL}@RELEASEPROOF_STABLE_MONEY_URL=${STABLE_MONEY_URL}@RELEASEPROOF_CANDIDATE_MONEY_URL=${CANDIDATE_MONEY_URL}" \
  --cpu 2 --memory 1Gi \
  --timeout 300 \
  --min-instances 1 \
  --max-instances 4 \
  --quiet >/dev/null

API_URL="$(url_of releaseproof-api)"

# ---------------------------------------------------------------------------
# 3. UI. Target URLs are inlined by Vite at build time; the API origin is read
#    at container start.
# ---------------------------------------------------------------------------
echo "==> Deploying UI"
# No build arguments: the UI resolves everything it needs at runtime from
# BACKEND_ORIGIN and the API's /api/demo-targets endpoint.
gcloud run deploy releaseproof-ui \
  --source ./frontend \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BACKEND_ORIGIN=${API_URL}" \
  --cpu 1 --memory 512Mi \
  --min-instances 1 \
  --quiet >/dev/null

UI_URL="$(url_of releaseproof-ui)"

# Allow direct browser calls to the API too (the UI proxies same-origin, but this
# keeps /docs usable from the deployed origin).
gcloud run services update releaseproof-api \
  --region "${REGION}" \
  --update-env-vars "RELEASEPROOF_ALLOWED_ORIGINS=${UI_URL}" \
  --quiet >/dev/null

cat <<EOF

========================================================================
ReleaseProof is deployed.

  UI (submit this as the working deployed link):
    ${UI_URL}

  API docs:
    ${API_URL}/docs

  Demo revisions:
    stable/latency        ${STABLE_LATENCY_URL}
    candidate/latency     ${CANDIDATE_LATENCY_URL}
    stable/contract       ${STABLE_CONTRACT_URL}
    candidate/contract    ${CANDIDATE_CONTRACT_URL}
    stable/sideeffect     ${STABLE_SIDEEFFECT_URL}
    candidate/sideeffect  ${CANDIDATE_SIDEEFFECT_URL}
    stable/money          ${STABLE_MONEY_URL}
    candidate/money       ${CANDIDATE_MONEY_URL}

Verify the live stack end to end:
    ./scripts/smoke_deployed.sh ${API_URL} ${STABLE_LATENCY_URL} ${CANDIDATE_LATENCY_URL}
========================================================================
EOF
