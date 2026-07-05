# Deployment Guide - Streamer Metrics Advisor

This guide outlines the steps to run and host the application locally, prepare prerequisite GCP services, configure required secrets (including key rotation and external API integration), build container images, and deploy/manage the multi-container architecture (FastAPI app + Nginx sidecar) on Google Cloud Run.

---

## 1. Local Running & Hosting

You can run and host the application locally on your machine for development, testing, or private usage.

### Prerequisites
Ensure you have Python 3.11+ and Poetry installed, then configure your environment:
* Run `poetry install` to install dependencies and compile local packages.

### Environment Configuration
To supply a default API key for your local instance, copy the `.env.example` template to `.env`:
* Run `cp .env.example .env` to create your local environment file.

Open `.env` and configure the values:
```env
PORT=8000
HOST=0.0.0.0
# Primary and backup keys for the LLM rotation pool
GEMINI_API_KEY="your-api-key-here"
GEMINI_API_KEY_BACKUP="your-backup-key-1"
GEMINI_API_KEY_TERTIARY="your-backup-key-2"
GEMINI_API_KEY_QUATERNARY="your-backup-key-3"
GEMINI_API_KEY_QUINARY="your-backup-key-4"

# Twitch Helix API credentials
TWITCH_CLIENT_ID="your-twitch-client-id"
TWITCH_CLIENT_SECRET="your-twitch-client-secret"

# YouTube API key
YOUTUBE_API_KEY="your-youtube-api-key"
```

> [!NOTE]
> * **Bring-Your-Own-Key (BYOK) mode**: If you leave `GEMINI_API_KEY` blank or omit the `.env` file, the local application operates in pure BYOK mode, prompting you to enter your key on the web dashboard landing page.
> * **Steam Integration**: All Steam Data (resolving game AppIDs and retrieving active player counts to compute spectator-to-player ratios) is queried **keylessly** using Steam's public store search and user stats APIs. Therefore, **no Steam API key is required**.

### Running the Server
Launch the local FastAPI server using:
* Run `poetry run start` to boot up the FastAPI app locally.

By default, the server starts at `http://localhost:8000`. If you need to bind to a different address or port, pass them as CLI options:
* Run `poetry run start --host 127.0.0.1 --port 8080` to run on a custom host and port.

### Running Scheduled Tasks Locally (Cron Refresh)
If you want to manually trigger the full scraping and playbook generation tasks locally:
* Run `poetry run cron-refresh` to execute the hourly refresh sequentially to completion.
* To seed the local Firestore database cache, run: `poetry run cron-refresh seed`

---

## 2. GCP Prerequisite Configuration

Prior to executing the deployment wizard or deploying manually, you must configure the following prerequisite GCP resources.

### A. Enable Google APIs
Enable the Google Cloud APIs required for storage, computation, security, and machine learning:
* Run `gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    firestore.googleapis.com \
    bigquery.googleapis.com \
    aiplatform.googleapis.com \
    cloudscheduler.googleapis.com`

### B. Configure Cloud Firestore (Native Mode)
The application stores profiles, playbooks, articles, and cache values in Firestore.
1. Navigate to the **Cloud Firestore Console** at [console.cloud.google.com/firestore](https://console.cloud.google.com/firestore).
2. Click **Create Database**.
3. Select **Native Mode** (do not select Datastore mode).
4. Set the Database ID to `(default)`.
5. Select your preferred database region and click **Create**.

### C. Create and Authorize Service Account
Create a dedicated IAM service account for the application and grant it the minimum required permissions to read secrets and access databases:

1. **Create the Service Account**:
   * Run `gcloud iam service-accounts create streamer-app-sa --display-name="Streamer Crossover App Service Account"`

2. **Grant Required Roles**:
   * **Firestore Access**: Grant `roles/datastore.user` to allow reading/writing Firestore documents.
     * Run `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/datastore.user"`
   * **BigQuery Access**: Grant `roles/bigquery.dataEditor` and `roles/bigquery.jobUser` to allow recording daily stats and sentiment history.
     * Run `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/bigquery.dataEditor"`
     * Run `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/bigquery.jobUser"`
   * **Secret Manager Access**: Grant `roles/secretmanager.secretAccessor` so the app container can read API keys at startup.
     * Run `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"`
   * **Vertex AI Access**: Grant `roles/aiplatform.user` to allow executing query streams against the remote Reasoning Engine agent runtime.
     * Run `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/aiplatform.user"`

---

## 3. Required Secrets Setup (Secret Manager)

For security, credentials must not be stored in plaintext. Upload them to GCP Secret Manager before launching the deployment wizard. 

### Secrets List

| Secret Name | Description |
|---|---|
| `gemini-api-key` | Primary Gemini API Key for model calls. |
| `gemini-api-key-backup` | Backup Gemini API Key. |
| `gemini-api-key-tertiary` | Third Gemini API Key in the rotation pool. |
| `gemini-api-key-quaternary` | Fourth Gemini API Key in the rotation pool. |
| `gemini-api-key-quinary` | Fifth Gemini API Key in the rotation pool. |
| `twitch-client-secret` | Twitch App Client Secret for Helix API access. |
| `youtube-api-key` | YouTube Data API v3 Developer Key. |
| `docs-username` | Basic Auth Username for Swagger FastAPI `/docs` path protection. |
| `docs-password` | Basic Auth Password for Swagger FastAPI `/docs` path protection. |

> [!IMPORTANT]
> **API Key Rotation Pool**: The application balances its request load across a pool of up to 5 Gemini keys (stored under the names `gemini-api-key`, `gemini-api-key-backup`, `gemini-api-key-tertiary`, `gemini-api-key-quaternary`, and `gemini-api-key-quinary` in GCP Secret Manager). This rotation mechanism (configured in `src/ag_kaggle_5day/agents/scraper/gemini.py` and `src/ag_kaggle_5day/agents/gcp_storage/embeddings.py`) mitigates quota limits and triggers automatic fallbacks on API transient errors (429 rate limits or 5xx server errors). All 5 keys must be created in Secret Manager to enable the rotation logic, although they can reuse duplicate keys if you do not have 5 separate keys.

### Creating Secrets (CLI)
Run these commands in your terminal (or Cloud Shell) to securely create the secrets:
* Run `echo -n "YOUR_PRIMARY_GEMINI_KEY" | gcloud secrets create gemini-api-key --data-file=-`
* Run `echo -n "YOUR_BACKUP_GEMINI_KEY" | gcloud secrets create gemini-api-key-backup --data-file=-`
* Run `echo -n "YOUR_TERTIARY_GEMINI_KEY" | gcloud secrets create gemini-api-key-tertiary --data-file=-`
* Run `echo -n "YOUR_QUATERNARY_GEMINI_KEY" | gcloud secrets create gemini-api-key-quaternary --data-file=-`
* Run `echo -n "YOUR_QUINARY_GEMINI_KEY" | gcloud secrets create gemini-api-key-quinary --data-file=-`
* Run `echo -n "YOUR_TWITCH_SECRET" | gcloud secrets create twitch-client-secret --data-file=-`
* Run `echo -n "YOUR_YOUTUBE_KEY" | gcloud secrets create youtube-api-key --data-file=-`
* Run `echo -n "YOUR_DOCS_USERNAME" | gcloud secrets create docs-username --data-file=-`
* Run `echo -n "YOUR_DOCS_PASSWORD" | gcloud secrets create docs-password --data-file=-`

---

## 4. Production Cloud Run Deployment Wizard (Recommended)

Our production architecture uses a **multi-container (sidecar)** setup:
1. **`nginx` container**: Serves as the public ingress point, terminates TLS, and proxies traffic to localhost.
2. **`app` container**: Runs the python FastAPI/Uvicorn backend.

To simplify the deployment process, we use an interactive deployment wizard script (`scripts/deploy_wizard.sh`) that automates container building, manifest templating, and service updates.

### Step 1: Create a Docker Registry
Create a repository in GCP Artifact Registry to host the docker images:
* Run `gcloud artifacts repositories create streamer-advisor-repo --repository-format=docker --location=us-central1` to create a Docker registry named `streamer-advisor-repo`.
* Run `gcloud auth configure-docker us-central1-docker.pkg.dev` to authenticate your local Docker daemon with the GCP registry.

### Step 2: Configure `deploy.env`
Copy the template configuration file `deploy.env.template` to `deploy.env`:
* Run `cp deploy.env.template deploy.env` to create your local config.

Open `deploy.env` and populate your GCP details, Twitch Client ID, and Vertex Reasoning Engine path:
```env
GCP_PROJECT=your-gcp-project-id
GCP_PROJECT_NUMBER=your-gcp-project-number
REGION=us-central1
TWITCH_CLIENT_ID=your-twitch-client-id
VERTEX_REASONING_ENGINE_PATH=projects/your-gcp-project-id/locations/us-central1/reasoningEngines/your-engine-id
```
*(Note: 'deploy.env' and the generated 'service.yaml' are git-ignored to prevent credential leaks).*

### Step 3: Run the Deployment Wizard
Execute the interactive wizard script:
* Run `./scripts/deploy_wizard.sh` to execute the deployment pipeline.

The script compiles the Knative manifest `service.yaml` dynamically from the template (mapping the 5 Gemini API key secrets from GCP Secret Manager to the container's environment variables), builds/pushes the images using Docker, and deploys updates to Cloud Run.

---

## 5. Database Initialization & Manual Firestore Indices

### Database Creation
* **BigQuery**: BigQuery datasets and tables are designed with self-healing creation checks. They auto-provision on first write.
* **Firestore Seed**: To populate your default configurations and staple games, execute the `seed` task on the Cloud Run Job:
  ```bash
  gcloud run jobs execute hourly-metrics-refresh --args="seed" --region us-central1
  ```

### Manual Firestore Vector Indices (CRITICAL)
Firestore nearest neighbor (kNN) vector search queries require composite vector indices. If these indices are missing, search queries will fail, logging a `FAILED_PRECONDITION` warning. 

You **must** manually create these three composite vector indices using the Google Cloud SDK CLI:

1. **Playbooks Vector Index**:
   ```bash
   gcloud alpha firestore indexes composite create \
     --collection-group=playbooks --query-scope=COLLECTION \
     --field-config=vector-config='{"dimension":"768","flat":{}}',field-path=embedding
   ```

2. **News Articles Vector Index**:
   ```bash
   gcloud alpha firestore indexes composite create \
     --collection-group=news_articles --query-scope=COLLECTION \
     --field-config=vector-config='{"dimension":"768","flat":{}}',field-path=embedding
   ```

3. **Spotlight/Exposé Articles Vector Index**:
   ```bash
   gcloud alpha firestore indexes composite create \
     --collection-group=spotlight_expose_articles --query-scope=COLLECTION \
     --field-config=vector-config='{"dimension":"768","flat":{}}',field-path=embedding
   ```

---

## 6. Manual / Granular Deployment (Alternative)

If you prefer to run the deployment commands manually rather than using the wizard:

### A. Rebuild and Push the App Container Image
Compile and push the backend container image to GCP Artifact Registry:
* Run `docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/streamer-advisor-repo/app:latest .`
* Run `docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/streamer-advisor-repo/app:latest`

### B. Rebuild and Push Nginx Sidecar Image
Nginx requires a custom configuration file (`nginx.cloudrun.conf`) copied directly inside the image:
* Run `docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/streamer-advisor-repo/nginx:latest -f Dockerfile.nginx .`
* Run `docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/streamer-advisor-repo/nginx:latest`

### C. Compile the Service Manifest
Generate `service.yaml` by replacing the `${VAR}` placeholders in `service.yaml.template` with your configuration values. Note that the manifest maps the rotation keys from Secret Manager:
```yaml
        - name: GEMINI_API_KEY
          valueFrom:
            secretKeyRef:
              name: gemini-api-key
              key: latest
        - name: GEMINI_API_KEY_BACKUP
          valueFrom:
            secretKeyRef:
              name: gemini-api-key-backup
              key: latest
        - name: GEMINI_API_KEY_TERTIARY
          valueFrom:
            secretKeyRef:
              name: gemini-api-key-tertiary
              key: latest
        - name: GEMINI_API_KEY_QUATERNARY
          valueFrom:
            secretKeyRef:
              name: gemini-api-key-quaternary
              key: latest
        - name: GEMINI_API_KEY_QUINARY
          valueFrom:
            secretKeyRef:
              name: gemini-api-key-quinary
              key: latest
```

### D. Update the FastAPI Web Service
* Run `gcloud run services replace service.yaml --region=us-central1 --project=YOUR_PROJECT_ID`

### E. Update the Scheduled Cloud Run Job (Cron)
Redeploy the Cloud Run Job using the deployment helper script (which binds environment variables and sets Secret Manager keys):
* Run `./scripts/deploy_job.sh [PROJECT_ID] [REGION] [TWITCH_CLIENT_ID] [SERVICE_ACCOUNT] [VERTEX_REASONING_ENGINE_PATH]`
* Alternatively, run the raw gcloud CLI command:
  * Run `gcloud run jobs deploy hourly-metrics-refresh \
      --image=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/streamer-advisor-repo/app:latest \
      --command=cron-refresh \
      --region=us-central1 \
      --task-timeout=45m \
      --set-env-vars="PYTHONUNBUFFERED=1,TWITCH_CLIENT_ID=YOUR_TWITCH_CLIENT_ID,VERTEX_REASONING_ENGINE_PATH=YOUR_RE_PATH" \
      --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,GEMINI_API_KEY_BACKUP=gemini-api-key-backup:latest,GEMINI_API_KEY_TERTIARY=gemini-api-key-tertiary:latest,GEMINI_API_KEY_QUATERNARY=gemini-api-key-quaternary:latest,GEMINI_API_KEY_QUINARY=gemini-api-key-quinary:latest,TWITCH_CLIENT_SECRET=twitch-client-secret:latest,YOUTUBE_API_KEY=youtube-api-key:latest" \
      --service-account="streamer-app-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"`

### F. Update the Vertex AI Reasoning Engine (Advisor Agent)
If you made changes to the advisor agent tools or agent definition (`src/ag_kaggle_5day/advisor_agent/agent.py`), update the deployed agent instance in place:
* Run `poetry run adk deploy agent_engine --project=YOUR_PROJECT_ID --region=YOUR_REGION --agent_engine_id=YOUR_AGENT_ENGINE_ID --display_name="advisor_agent" src`

---

## 7. Cloud Run Job (Scheduled Cron Tasks)

To run the long-running hourly scraping and database updates without hitting HTTP timeouts, package and run the task as a **Cloud Run Job**:

### Execute the Job Manually (Validation & CLI Tasks)
To trigger the job execution manually with specific tasks, run `gcloud run jobs execute` with the `--args` flag:

* **Run default hourly scrape and sentinel tasks**:
  ```bash
  gcloud run jobs execute hourly-metrics-refresh --region us-central1 --wait
  ```
* **Run database cache seeding**:
  ```bash
  gcloud run jobs execute hourly-metrics-refresh --region us-central1 --args="seed" --wait
  ```
* **Run daily streamer analytics aggregation**:
  ```bash
  gcloud run jobs execute hourly-metrics-refresh --region us-central1 --args="daily-analytics" --wait
  ```
* **Run daily selection and longform expose write**:
  ```bash
  gcloud run jobs execute hourly-metrics-refresh --region us-central1 --args="daily-expose" --wait
  ```

### Configure Cloud Scheduler Trigger
To trigger the job automatically on a schedule (e.g. hourly):
1. In Cloud Scheduler, create or edit the scheduler job `hourly-metrics-refresh`.
2. Set the **Target type** to **Cloud Run Job**.
3. Select the job name `hourly-metrics-refresh` and specify the action as **Execute**.

---

## 8. Troubleshooting & Expected Initial Warnings

When deploying the application for the first time or starting a fresh database environment, you will see a few warnings in the logs. **This is normal and expected behavior** while the cloud databases and indices warm up. The application is designed to handle these gracefully and fall back to safe mocks rather than crashing:

### 1. Vector Index Omission (`FAILED_PRECONDITION`)
* **Symptom**: Logs show `FAILED_PRECONDITION: Vector index on collection playbooks is not ready or missing.`
* **Why**: Firestore composite vector indices (RAG indices) are built asynchronously and can take 5–10 minutes to become active after you run the `gcloud` commands.
* **Impact**: During the build phase, similarity searches will gracefully fall back to default/heuristic matches, and a warning log is printed with the exact command to create the index. Once the index is ready, RAG search begins working automatically.

### 2. "Cache Stale" or Empty Dashboard List
* **Symptom**: Dashboard header shows `⏱ Cache: stale` or metrics lists are empty.
* **Why**: On initial boot, the Firestore cache collections are empty. The application immediately spins up a background scraper job.
* **Impact**: Until the scraper finishes its first run (takes ~1-3 minutes) or the database is seeded (`gcloud run jobs execute hourly-metrics-refresh --args="seed"`), the UI will show stale status. It resolves itself immediately upon scraper completion.

### 3. Remote Reasoning Engine Unreachable Warnings
* **Symptom**: Chat console displays `⚠️ [Environment Configuration Warning: GEMINI_API_KEY is not set]` or logs show `Vertex AI Agent Engine is unreachable, falling back to local InMemoryRunner`.
* **Why**: The app is checking for a remote ADK agent on Vertex AI. If the engine is not yet deployed, or the credentials are unset, the app falls back to local execution.
* **Impact**: Chat functions still work completely in BYOK mode using a local instance of the Gemini Flash runner on the FastAPI container.

### 4. BigQuery Auto-Creation Warnings
* **Symptom**: Logs show warnings like `dataset streamer_metrics not found, creating...` or `table hourly_stats not found`.
* **Why**: BigQuery tables are created dynamically on the first data insertion to simplify deployment.
* **Impact**: This warning appears only on the very first run and disappears on subsequent hourly updates once the tables have been auto-created.
