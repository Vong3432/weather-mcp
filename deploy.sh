#!/usr/bin/env bash
# Deploy (or redeploy) the weather MCP server to Google Cloud Run. Safe to re-run.
#
# Usage: ./deploy.sh   (reads PROJECT_ID and REGION from .env; see .env.example)
set -euo pipefail

# Load .env without overriding variables already set in the shell.
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value || [[ -n "$key" ]]; do
    key="${key//[[:space:]]/}"
    [[ -z "$key" || "$key" == \#* ]] && continue
    value="${value%$'\r'}"; value="${value%\"}"; value="${value#\"}"
    [[ -z "${!key:-}" ]] && export "$key=$value"
  done < "$ENV_FILE"
fi

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID in .env (copy .env.example) or in the environment}"
REGION="${REGION:-asia-southeast1}"
SERVICE="weather-mcp"
SECRET="weather-mcp-tokens"
RUNTIME_SA="weather-mcp-run@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="weather-mcp-build@${PROJECT_ID}.iam.gserviceaccount.com"

gc() { gcloud --project "$PROJECT_ID" --quiet "$@"; }

echo "==> Enabling APIs"
gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

echo "==> Token secret"
if ! gc secrets describe "$SECRET" >/dev/null 2>&1; then
  gc secrets create "$SECRET" --replication-policy=automatic
  printf '{}' | gc secrets versions add "$SECRET" --data-file=-
fi

echo "==> Runtime service account (can read the token secret, nothing else)"
if ! gc iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  gc iam service-accounts create weather-mcp-run --display-name="weather-mcp Cloud Run runtime"
fi
gc secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor >/dev/null

echo "==> Build service account (Cloud Run Builder only)"
# Newer projects no longer give the default Compute service account the permissions a source deploy needs
# (reading the uploaded source, pushing the image), so builds run as this dedicated account instead.
if ! gc iam service-accounts describe "$BUILD_SA" >/dev/null 2>&1; then
  gc iam service-accounts create weather-mcp-build --display-name="weather-mcp Cloud Build"
  NEW_BUILD_SA=1
fi
gc projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BUILD_SA}" --role=roles/run.builder --condition=None >/dev/null
if [[ -n "${NEW_BUILD_SA:-}" ]]; then
  echo "    Waiting 60s for the new IAM grant to propagate..."
  sleep 60
fi

echo "==> Keep token-bearing request URLs out of Cloud Logging"
# ChatGPT connects with /mcp/<token>; Cloud Run's request log would record that URL.
if ! gc logging sinks describe _Default --format='value(exclusions[].name)' | grep -q "${SERVICE}-request-urls"; then
  gc logging sinks update _Default \
    --add-exclusion="name=${SERVICE}-request-urls,filter=resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE}\" AND log_id(\"run.googleapis.com/requests\")"
fi

echo "==> Building and deploying (Cloud Build)"
gc run deploy "$SERVICE" \
  --source=app \
  --region="$REGION" \
  --service-account="$RUNTIME_SA" \
  --build-service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}" \
  --allow-unauthenticated \
  --set-env-vars="TOKENS_SECRET=projects/${PROJECT_ID}/secrets/${SECRET}/versions/latest" \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=2 \
  --concurrency=40 --timeout=60s

URL="$(gc run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
echo
echo "Deployed: $URL"
echo "Health:   $(curl -s "$URL/health")"
echo "Next:     python3 scripts/add_token.py <consumer-name>"
