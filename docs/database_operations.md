# Database Operations Guide: Resets, Backups, and Restores

This guide explains how to safely reset, back up, and restore the databases used in the Streaming Crossover Matchmaker application. It is written to be easily followed by both developers and system administrators using either the **Google Cloud Web Console** or the **Command Line (CLI)**.

---

## 1. System Overview

The application utilizes two primary storage services in Google Cloud Platform (GCP):
1. **Cloud Firestore (NoSQL Document Database)**: Holds live configuration caches (`system_cache`), streamer profiles (`streamer_profiles`), AI-generated playbooks (`playbooks`), and resolved game genres (`resolved_game_categories`).
2. **Cloud BigQuery (Data Warehouse)**: Holds historical records, including hourly metrics logs (`hourly_stats`), long-term sentiment trackers (`sentiment_history`), and security logs (`user_activity`).

---

## 2. Resetting the Databases (Fresh Start)

A reset deletes old test data and junk records, allowing the system to start over with clean, validated schemas.

> [!WARNING]
> Resetting the database will permanently delete all historical metrics, sentiment logs, and stream playbooks. Perform a backup (see Section 3) first if you want to preserve past data.

### Step A: Clear BigQuery Metrics
To start metrics collection from scratch, drop the `streamer_metrics` dataset. The application will automatically recreate the dataset and tables on the next scheduler run.

#### Option 1: Web Console
1. Open the [Google Cloud BigQuery Console](https://console.cloud.google.com/bigquery).
2. In the explorer pane on the left, locate your project and click on the **streamer_metrics** dataset.
3. On the right side of the screen, click **Delete** (trash can icon).
4. Type `delete` in the confirmation dialog to confirm.

#### Option 2: Command Line (gcloud CLI)
Run the following command in your terminal:
```bash
bq rm -r -f -d streamer_metrics
```

---

### Step B: Clear Firestore Documents
To wipe streamer profiles, playbooks, and cached states, delete the Firestore collections.

#### Option 1: Web Console (Recreate Default Database)
The easiest way to clear all Firestore data at once is to delete and recreate the default database instance:
1. Open the [Google Cloud Firestore Console](https://console.cloud.google.com/firestore).
2. Click **Databases** in the left sidebar menu.
3. Click the vertical ellipsis (three dots) next to the **(default)** database, and select **Delete**.
4. Confirm deletion by entering the database ID `(default)`.
5. Once deleted, click **Create Database**.
6. Set the database ID to `(default)` and select **Native Mode** (do not select Datastore mode). Select your region and click **Create**.

#### Option 2: Command Line (Firebase CLI)
If you have the Firebase CLI tools installed and logged in, run:
```bash
firebase firestore:delete --all-collections
```

---

### Step C: Re-seed and Re-populate the System (Time: ~5 minutes)
Once the databases are empty, initialize and bootstrap fresh data securely using **Cloud Run Jobs** instead of exposing HTTP endpoints to the web.

1. **Trigger Base Seeding**:
   Execute the `seed` task on the Cloud Run Job. This securely seeds the Firestore `system_cache` with default staple games and configuration details:
   ```bash
   gcloud run jobs execute hourly-metrics-refresh --args="seed" --region us-central1
   ```
   *(For local development, you can run: `poetry run cron-refresh seed`)*

2. **Trigger Scraper Pipeline**:
   Execute the standard scraping and analytics metrics pipeline. This fetches live Twitch/YouTube metrics, resolves categories, aggregates telemetry, and recreates BigQuery tables:
   ```bash
   gcloud run jobs execute hourly-metrics-refresh --region us-central1
   ```

---

## 3. Backups (Firestore & BigQuery)

Setting up regular backups ensures you can recover quickly from corruption or accidental deletion. Under GCP's **free tier**, you can maintain backups at zero cost.

### Firestore Backup Strategy (Exports to Cloud Storage)
Firestore exports are stored in Google Cloud Storage. Standard storage offers a **5 GB free tier**, which is more than enough space for our dataset.

#### Step 1: Create a Cloud Storage Bucket for Backups
1. Open the [Google Cloud Storage Console](https://console.cloud.google.com/storage).
2. Click **Create** at the top.
3. Name your bucket (e.g., `your-project-id-firestore-backups`).
4. Select a **Single Region** close to your Firestore location.
5. Set storage class to **Standard**.
6. Keep other defaults and click **Create**.

#### Step 2: Perform a Manual Backup

##### Option 1: Web Console
Firestore does not support manual export directly from the console GUI, but you can easily trigger it via the Google Cloud Shell:
1. Open the **Cloud Shell** (terminal icon in the top right corner of the Google Cloud console).
2. Run the export command:
   ```bash
   gcloud firestore export gs://your-bucket-name
   ```

##### Option 2: Local CLI
```bash
gcloud firestore export gs://your-bucket-name --project=your-project-id
```

#### Step 3: Configure Regular Automated Backups
To automate daily backups using Cloud Scheduler:

##### Option 1: Web Console
1. Open the [Cloud Scheduler Console](https://console.cloud.google.com/cloudscheduler).
2. Click **Create Job**.
3. **Define the schedule**:
   * Name: `daily-firestore-backup`
   * Frequency: `0 2 * * *` (Runs every day at 2:00 AM UTC)
   * Timezone: `UTC`
4. **Configure execution**:
   * Target type: `HTTP`
   * URL: `https://firestore.googleapis.com/v1/projects/YOUR_PROJECT_ID/databases/(default):exportDocuments`
   * HTTP Method: `POST`
   * Auth header: `Add OAuth token`
   * Service Account: Select your default App Engine/Compute service account.
5. **Body**: Place the following JSON in the Body text box:
   ```json
   {
     "outputUriPrefix": "gs://your-bucket-name"
   }
   ```
6. Click **Create**.

##### Option 2: Command Line (gcloud CLI)
Create the automated daily backup scheduler job using:
```bash
gcloud scheduler jobs create http daily-firestore-backup \
    --schedule="0 2 * * *" \
    --uri="https://firestore.googleapis.com/v1/projects/YOUR_PROJECT_ID/databases/(default):exportDocuments" \
    --http-method=POST \
    --oauth-service-account-email="YOUR_SERVICE_ACCOUNT_EMAIL" \
    --headers="Content-Type=application/json" \
    --message-body='{"outputUriPrefix": "gs://your-bucket-name"}'
```

---

### BigQuery Backup Strategy (Time Travel & Snapshots)

BigQuery features built-in protection mechanisms that require zero manual scheduler configuration.

#### 1. Time Travel (Free & Automatic)
BigQuery keeps a complete record of all data modifications for the past **7 days**. If a table was accidentally wiped or broken, you can recover the data using standard SQL in the BigQuery console:
```sql
-- Query the state of the table exactly 2 hours ago
SELECT * 
FROM `streamer_metrics.hourly_stats`
FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
```

#### 2. Table Snapshots (Point-in-Time Backups)
To freeze a table before a release or manual database modification:

##### Option 1: Web Console
1. Open the BigQuery console, select the table (e.g. `hourly_stats`).
2. Click **Copy** at the top.
3. In the dialog, set **Target Table Type** to **Snapshot**.
4. Select the destination dataset and table name (e.g. `hourly_stats_backup_jul2026`).
5. Click **Copy**.

##### Option 2: Command Line (gcloud CLI)
```bash
bq cp --snapshot streamer_metrics.hourly_stats streamer_metrics.hourly_stats_snapshot
```

---

## 4. Restoring Data

If you need to recover Firestore from a backup bucket:

### Option 1: Command Line / Cloud Shell
1. Run the import command, targeting the specific folder generated inside your backup bucket:
   ```bash
   gcloud firestore import gs://your-bucket-name/2026-07-01T21:40:00_12345/
   ```
2. The import runs as a background operation. You can monitor the operation status using:
   ```bash
   gcloud firestore operations list
   ```

### Option 2: REST API / Web Trigger
If you do not have command-line access, you can trigger a restore by making a `POST` request to the Google API endpoint with OAuth authorization:
* **POST URL**: `https://firestore.googleapis.com/v1/projects/YOUR_PROJECT_ID/databases/(default):importDocuments`
* **JSON Body**:
  ```json
  {
    "inputUriPrefix": "gs://your-bucket-name/2026-07-01T21:40:00_12345/"
  }
  ```
