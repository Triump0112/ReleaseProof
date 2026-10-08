#!/usr/bin/env bash
# Delete every Cloud Run service this project deploys.
#
#   ./scripts/teardown_cloud_run.sh [PROJECT_ID] [REGION]
#
# Services scale to zero by default, so an idle deployment is already close to
# free. Use this once the submission is judged, or to reclaim a region.

set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-asia-south1}"

if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no project. Usage: $0 PROJECT_ID [REGION]" >&2
  exit 1
fi

SERVICES=(
  releaseproof-ui
  releaseproof-api
  releaseproof-stable-latency
  releaseproof-candidate-latency
  releaseproof-stable-contract
  releaseproof-candidate-contract
  releaseproof-stable-sideeffect
  releaseproof-candidate-sideeffect
  releaseproof-stable-money
  releaseproof-candidate-money
)

echo "This deletes ${#SERVICES[@]} Cloud Run services from ${PROJECT} (${REGION})."
read -r -p "Type the project id to confirm: " confirm
if [[ "${confirm}" != "${PROJECT}" ]]; then
  echo "Aborted." >&2
  exit 1
fi

for service in "${SERVICES[@]}"; do
  if gcloud run services describe "${service}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1; then
    echo "==> Deleting ${service}"
    gcloud run services delete "${service}" --region "${REGION}" --project "${PROJECT}" --quiet
  else
    echo "==> Skipping ${service} (not deployed)"
  fi
done

echo
echo "Cloud Run services removed."
echo "Container images remain in Artifact Registry and are billed by storage."
echo "To remove those too:"
echo "  gcloud artifacts repositories delete cloud-run-source-deploy \\"
echo "    --location=${REGION} --project=${PROJECT}"
