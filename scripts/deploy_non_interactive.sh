#!/usr/bin/env bash
# scripts/deploy_non_interactive.sh - Non-interactive deployment runner for app, service, and job.

set -euo pipefail

ENV_FILE="deploy.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: deploy.env not found!" >&2
    exit 1
fi

source "$ENV_FILE"

GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || echo "")}"
REGION="${REGION:-"us-central1"}"

SERVICE_ACCOUNT="streamer-app-sa@${GCP_PROJECT}.iam.gserviceaccount.com"
DEPLOY_NONCE="deploy-$(date +%Y%m%d-%H%M)"

echo "Compiling service.yaml..."
python3 -c "
import os
with open('service.yaml.template', 'r') as f:
    template = f.read()

replacements = {
    '\${GCP_PROJECT}': '${GCP_PROJECT}',
    '\${GCP_PROJECT_NUMBER}': '${GCP_PROJECT_NUMBER}',
    '\${REGION}': '${REGION}',
    '\${TWITCH_CLIENT_ID}': '${TWITCH_CLIENT_ID}',
    '\${VERTEX_REASONING_ENGINE_PATH}': '${VERTEX_REASONING_ENGINE_PATH}',
    '\${DEPLOY_NONCE}': '${DEPLOY_NONCE}'
}

for placeholder, val in replacements.items():
    template = template.replace(placeholder, val)

with open('service.yaml', 'w') as f:
    f.write(template)
"

IMAGE_APP="${REGION}-docker.pkg.dev/${GCP_PROJECT}/streamer-advisor-repo/app:latest"

echo "Building App image: ${IMAGE_APP}..."
docker build --platform linux/amd64 -t "${IMAGE_APP}" .

echo "Pushing App image..."
docker push "${IMAGE_APP}"

echo "Deploying Web Service..."
gcloud run services replace service.yaml --region="${REGION}" --project="${GCP_PROJECT}"

echo "Deploying Cron Job..."
./scripts/deploy_job.sh "${GCP_PROJECT}" "${REGION}" "${TWITCH_CLIENT_ID}" "${SERVICE_ACCOUNT}" "${VERTEX_REASONING_ENGINE_PATH}"

echo "🎉 Non-interactive deployment completed successfully!"
