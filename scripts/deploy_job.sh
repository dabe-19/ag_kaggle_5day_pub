#!/usr/bin/env bash
# scripts/deploy_job.sh - Deploy or update the hourly metrics refresh Cloud Run Job.

set -euo pipefail

# Configuration arguments (no hardcoded defaults)
PROJECT_ID="${1:-}"
REGION="${2:-us-central1}"
TWITCH_CLIENT_ID="${3:-}"
SERVICE_ACCOUNT="${4:-}"
VERTEX_REASONING_ENGINE_PATH="${5:-}"

if [ -z "$PROJECT_ID" ] || [ -z "$TWITCH_CLIENT_ID" ] || [ -z "$SERVICE_ACCOUNT" ]; then
    echo "Error: Missing required arguments for deploy_job.sh." >&2
    echo "Usage: $0 <project_id> [region] <twitch_client_id> <service_account> [reasoning_engine_path]" >&2
    exit 1
fi

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/streamer-advisor-repo/app:latest"

echo "=== Deploying Cloud Run Job 'hourly-metrics-refresh' ==="
echo "Project ID:      ${PROJECT_ID}"
echo "Region:          ${REGION}"
echo "Image:           ${IMAGE}"
echo "Service Account: ${SERVICE_ACCOUNT}"
echo "========================================================"

# Run gcloud jobs deploy command
gcloud run jobs deploy hourly-metrics-refresh \
    --image="${IMAGE}" \
    --command="cron-refresh" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --cpu="2" \
    --memory="2Gi" \
    --task-timeout="45m" \
    --set-env-vars="PYTHONUNBUFFERED=1,TWITCH_CLIENT_ID=${TWITCH_CLIENT_ID},VERTEX_REASONING_ENGINE_PATH=${VERTEX_REASONING_ENGINE_PATH}" \
    --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,GEMINI_API_KEY_BACKUP=gemini-api-key-backup:latest,GEMINI_API_KEY_TERTIARY=gemini-api-key-tertiary:latest,GEMINI_API_KEY_QUATERNARY=gemini-api-key-quaternary:latest,GEMINI_API_KEY_QUINARY=gemini-api-key-quinary:latest,TWITCH_CLIENT_SECRET=twitch-client-secret:latest,YOUTUBE_API_KEY=youtube-api-key:latest" \
    --service-account="${SERVICE_ACCOUNT}"

echo "=== Cloud Run Job deployed successfully! ==="
