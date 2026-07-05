#!/usr/bin/env bash
# scripts/deploy_wizard.sh - Interactive deployment wizard for WOR-ACLE app, jobs, and agent engine.

set -euo pipefail

echo "========================================================"
echo "          WOR-ACLE Deployment Wizard                    "
echo "========================================================"

# --- 1. Load Configurations from deploy.env ---
ENV_FILE="deploy.env"
ENV_TEMPLATE="deploy.env.template"

if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_TEMPLATE" ]; then
        echo "Creating '$ENV_FILE' from template..."
        cp "$ENV_TEMPLATE" "$ENV_FILE"
    else
        echo "Error: $ENV_TEMPLATE not found. Please run this script from the project root." >&2
        exit 1
    fi
fi

# Source configurations
# shellcheck disable=SC1090
source "$ENV_FILE"

# Provide defaults from gcloud configuration if empty in deploy.env
GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || echo "")}"
REGION="${REGION:-"us-central1"}"
GCP_PROJECT_NUMBER="${GCP_PROJECT_NUMBER:-}"
TWITCH_CLIENT_ID="${TWITCH_CLIENT_ID:-}"
VERTEX_REASONING_ENGINE_PATH="${VERTEX_REASONING_ENGINE_PATH:-}"

# Check for empty variables
MISSING_VARS=()
[ -z "$GCP_PROJECT" ] && MISSING_VARS+=("GCP_PROJECT")
[ -z "$GCP_PROJECT_NUMBER" ] && MISSING_VARS+=("GCP_PROJECT_NUMBER")
[ -z "$REGION" ] && MISSING_VARS+=("REGION")
[ -z "$TWITCH_CLIENT_ID" ] && MISSING_VARS+=("TWITCH_CLIENT_ID")
[ -z "$VERTEX_REASONING_ENGINE_PATH" ] && MISSING_VARS+=("VERTEX_REASONING_ENGINE_PATH")

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo -e "\nError: The following required parameters are missing in '$ENV_FILE':" >&2
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" >&2
    done
    echo -e "\nPlease configure '$ENV_FILE' with your local environment values before deploying." >&2
    exit 1
fi

SERVICE_ACCOUNT="streamer-app-sa@${GCP_PROJECT}.iam.gserviceaccount.com"
# Extract the engine ID from the path (e.g. projects/.../reasoningEngines/123456 -> 123456)
REASONING_ENGINE="${VERTEX_REASONING_ENGINE_PATH##*/}"

echo "========================================================"
echo "Project ID:      ${GCP_PROJECT}"
echo "Project Number:  ${GCP_PROJECT_NUMBER}"
echo "Region:          ${REGION}"
echo "Twitch ID:       ${TWITCH_CLIENT_ID}"
echo "Service Account: ${SERVICE_ACCOUNT}"
echo "Agent Engine ID: ${REASONING_ENGINE}"
echo "========================================================"

# --- 2. Prompt for Stages ---
prompt_yn() {
    local prompt="$1"
    local default="$2"
    local reply
    read -p "$prompt [$default]: " reply
    reply="${reply:-$default}"
    case "$reply" in
        [Yy]*) echo "yes" ;;
        *) echo "no" ;;
    esac
}

echo -e "\nSelect deployment stages to execute:"
DEPLOY_APP=$(prompt_yn "1. Build and Push APP container image?" "y")
DEPLOY_NGINX=$(prompt_yn "2. Build and Push NGINX container image?" "n")
DEPLOY_WEB=$(prompt_yn "3. Deploy/Update Cloud Run Web Service (streamer-advisor)?" "y")
DEPLOY_JOB=$(prompt_yn "4. Deploy/Update Cloud Run Cron Job (hourly-metrics-refresh)?" "y")
DEPLOY_RE=$(prompt_yn "5. Deploy/Update Vertex AI Reasoning Engine (ADK)?" "y")

echo -e "\n========================================================"
echo "          Starting Deployment Execution                 "
echo "========================================================"

# Pre-checks
if [ "$DEPLOY_APP" = "yes" ] || [ "$DEPLOY_NGINX" = "yes" ]; then
    if ! docker info >/dev/null 2>&1; then
        echo "Error: Docker daemon is not running. Please start Docker and retry." >&2
        exit 1
    fi
fi

# Always compile service.yaml from template at the start of execution
# because it is copied into the App Docker image during build.
DEPLOY_NONCE="deploy-$(date +%Y%m%d-%H%M)"
echo "Compiling service.yaml from template..."
python3 -c "
import os
with open('service.yaml.template', 'r') as f:
    template = f.read()

# Safe variable substitution
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

# Stage 1: Build & Push App Image
if [ "$DEPLOY_APP" = "yes" ]; then
    IMAGE_APP="${REGION}-docker.pkg.dev/${GCP_PROJECT}/streamer-advisor-repo/app:latest"
    echo -e "\n--- [Stage 1] Building and pushing App image: ${IMAGE_APP} ---"
    docker build --platform linux/amd64 -t "${IMAGE_APP}" .
    docker push "${IMAGE_APP}"
fi

# Stage 2: Build & Push Nginx Image
if [ "$DEPLOY_NGINX" = "yes" ]; then
    IMAGE_NGINX="${REGION}-docker.pkg.dev/${GCP_PROJECT}/streamer-advisor-repo/nginx:latest"
    echo -e "\n--- [Stage 2] Building and pushing Nginx image: ${IMAGE_NGINX} ---"
    docker build --platform linux/amd64 -t "${IMAGE_NGINX}" -f Dockerfile.nginx .
    docker push "${IMAGE_NGINX}"
fi

# Stage 3: Deploy/Update Web Service
if [ "$DEPLOY_WEB" = "yes" ]; then
    echo -e "\n--- [Stage 3] Deploying Cloud Run Web Service ---"
    gcloud run services replace service.yaml --region="${REGION}" --project="${GCP_PROJECT}"
fi

# Stage 4: Deploy/Update Cron Job
if [ "$DEPLOY_JOB" = "yes" ]; then
    echo -e "\n--- [Stage 4] Deploying Cloud Run Cron Job ---"
    ./scripts/deploy_job.sh "${GCP_PROJECT}" "${REGION}" "${TWITCH_CLIENT_ID}" "${SERVICE_ACCOUNT}" "${VERTEX_REASONING_ENGINE_PATH}"
fi

# Stage 5: Deploy/Update Agent Engine
if [ "$DEPLOY_RE" = "yes" ]; then
    echo -e "\n--- [Stage 5] Deploying Agent to Vertex AI Agent Runtime ---"
    poetry run adk deploy agent_engine \
        --project="${GCP_PROJECT}" \
        --region="${REGION}" \
        --agent_engine_id="${REASONING_ENGINE}" \
        --display_name="advisor_agent" \
        src
fi

echo -e "\n========================================================"
echo "🎉 All requested deployment stages completed successfully!"
echo "========================================================"
