#!/bin/sh
set -eu

# Cloud Run supplies PORT; Compose and local runs default to 8080.
RP_PORT="${PORT:-8080}"

# BACKEND_ORIGIN is the orchestrator the UI proxies /api/ to.
# Compose: http://backend:8080   Cloud Run: https://releaseproof-api-....run.app
RP_BACKEND_ORIGIN="${BACKEND_ORIGIN:-http://backend:8080}"

# Cloud Run routes by Host header, so it must match the backend host, not the UI host.
RP_BACKEND_HOST=$(printf '%s' "$RP_BACKEND_ORIGIN" | sed -e 's#^https\?://##' -e 's#/.*$##')

export RP_PORT RP_BACKEND_ORIGIN RP_BACKEND_HOST

# Explicit variable list so nginx runtime vars ($uri, $remote_addr) survive untouched.
envsubst '${RP_PORT} ${RP_BACKEND_ORIGIN} ${RP_BACKEND_HOST}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "ReleaseProof UI -> proxying /api/ to ${RP_BACKEND_ORIGIN} (Host: ${RP_BACKEND_HOST}) on :${RP_PORT}"
exec nginx -g 'daemon off;'
