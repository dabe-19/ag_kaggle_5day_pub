# User's Guide - WOR-ACLE Streamer Metrics Advisor

This guide explains how to navigate, run, and use the features of the WOR-ACLE Streamer Metrics Advisor dashboard.

---

## 1. Local Setup & Startup

To run the web interface locally on your machine:

1. **Install Dependencies**:
   ```bash
   poetry install
   ```
2. **Configure Local Environment**:
   Copy `.env.example` to `.env` and enter your Twitch, YouTube, and Gemini API keys (optional; the app can run keyless in Bring-Your-Own-Key mode):
   ```bash
   cp .env.example .env
   ```
3. **Launch the Server**:
   ```bash
   poetry run start
   ```
   Open your browser and navigate to `http://localhost:8000`.

---

## 2. Dashboard Landing & Activation (BYOK Model)

When booting the app without a pre-configured server-side Gemini key, the interface operates in **Bring-Your-Own-Key (BYOK)** mode.

![Side Panel Landing](Gallery/TopMain.png)

* **Key Encryption**: Input your Google AI Studio API Key in the settings drawer. The key is securely encrypted on the backend and stored in a secure, `HttpOnly` session cookie (`gemini_session_key`) to prevent XSS leakage.
* **Disconnecting**: Click **Disconnect Key** in the header to instantly purge the session cookie and disconnect.

![Side Panel Landing](Gallery/BYOK_Entry.png)

---

## 3. Core Features & Interface Walkthrough

The dashboard is organized into four main operational views: **Market Monitor**, **3D Star Map**, **Playbook Planner**, and the **Community Orbit Console**.

### A. Market Monitor (Trending Games)
The main panel displays live viewership and competitor metrics for the top gaming categories.

![Market Monitor Dashboard](Gallery/TopRPG.png)

* **Data Pipeline**: The background scheduler runs every hour, scraping the **top 100 trending games** from Twitch. For each game:
  * It aggregates live Twitch and YouTube concurrent viewer counts.
  * It queries Steam active player counts keylessly to calculate spectator-to-player ratios.
  * It identifies the **top 3 live streamers** on Twitch and **top 3 live streamers** on YouTube playing that game.
* **Dashboard View**: Shows a curated list of active trending, staple, and custom games, along with local cache age status (`⏱ Cache: Xm ago`).
* **Sort Top Games by Category**: Click the **Category** drop menu to select a category and sort the top games by that category (screenshot above shows the RPG filter applied).
* **Custom Target Tracking**: Enter custom game titles to trigger on-demand scraping and append them to the current metrics list.

![Custom Game Entry](Gallery/CustomGames.png)

---

### B. Community Vibe Matchmaker & Orbit Console
Located at the bottom of the main tab, the **Community Matchmaker** allows you to sample live Twitch streams and match creators based on chat sentiments.

![Community Orbit Input](Gallery/BottomMain_Community.png)

* **Twitch Chat Crawl**: Enter any Twitch streamer's handle to initiate a real-time sampling job. The system connects keylessly to the streamer's IRC chat channel, displays a live heartbeat sparkline, and crawls messages for **30 seconds**.
* **Deduplication & Sentiment Analysis**: It filters out repeated chat spam, emotes, and copypastas, running a Gemini subagent pass to evaluate the channel's active sentiment polarity, messages-per-minute (MPM), and volatility.

![Live Chat Monitor Sampling](Gallery/TribeMatchmaking_RealTimeChatMon.png)

* **Tribe Alignment**: The system locates the closest **Vibe Tribe** cluster centroid matching the streamer's profile.
* **Match & Raid Campaigns**: It identifies peer micro-streamers orbiting the same centroid, displays their active game, and generates an LLM-authored, story-driven raid campaign recommendation to help you collaborate.

![Tribe Matchmaker Results](Gallery/RaidPlaybook1.png)

---

### C. 3D Interactive Star Map (Ecosystem Galaxy)
Clicking the **Star Map** tab opens an interactive 3D constellation map of the streamer ecosystem.

![Star Map Galaxy View](Gallery/StarMap_Galaxy.png)

* **PCA Projection**: Streamer correlation feature vectors (sentiment, volatility, active timeslot, category) are projected onto a 3D coordinate canvas via Principal Component Analysis (PCA). Creators with similar chat environments are plotted close together.
* **Vibe Tribes**: Streamers are automatically grouped into K-Means clusters (Vibe Tribes). Clicking on a Tribe centroid zooms you into a localized constellation view.
* **Micro-Streamer Projections**: Displays coordinate-stable representations for both major influencers and tracked micro-streamers.
* **Vibe Tribe Chat Interface**: Chat interface to the constellation analysis agent who has access to tools and has access to specific cluster and vibe analysis tools.

![Tribe Cluster View](Gallery/StarMapTribe1.png)
![Micro-Streamer Nebula](Gallery/MicroStreamerNebula.png)
![Vibe Tribe Chat Interface](Gallery/TribeChat2_Results.png)

---

### D. Interactive Advisor Agent
The right-hand panel contains an interactive chatbot interface with a retro arcade CRT aesthetic.

![Arcade Chatbot Interface](Gallery/ArcadeChatBot.png)

* **ADK Agent Engine**: Powered by the Google ADK framework running the `streamer_metrics_advisor_agent` definition. It delegates analysis to specialized sub-agents (`saturation_scout`, `strategy_planner`, `constellation_analyst`).
* **Dashboard Tool Sync**: You can ask the agent to add/remove tracked games (e.g. *"add Elden Ring"*). The agent automatically executes the tools, writes to `cache.json`, starts a background scrape, and reloads the frontend dashboard UI dynamically.
* **Streamer Profiles**: Clicking on any matched streamer opens a detailed profile drawer displaying historical sentiment charts, Vibe Radar coordinates, and active stream VOD links.

![Streamer Profile Drawer Details](Gallery/AspenStreamerDrawer.png)
![Streamer Profile Drawer Details 2](Gallery/AspenStreamerDrawer2.png)
![Streamer Profile Drawer Details 3](Gallery/AspenStreamerDrawer3.png)

---

### E. Stream Playbook Planner & Curation Hub
The **Playbook Planner** tab lets you compile strategic playbooks for your channel.

| 1. Select Vibe & Scale | 2. Generate Playbooks | 3. Pinned Curation Hub |
|---|---|---|
| ![Playbook Preferences](Gallery/PlaybookWizard1.png) | ![Generated Recommendations](Gallery/PlaybookWizard3.png) | ![Saved Curation](Gallery/SavedPlaybooks.png) |

* **Preference Alignment**: Select your stream style—**Vibe** (Chill, Competitive, Community, Story), **Channel Scale** (Starting Out, Affiliate, Partner), and **Target Duration**.
* **Parallel Generation**: Click **Generate Strategic Playbooks** to trigger parallel model runs (via `ThreadPoolExecutor`) evaluating the top 3 best-fit games. The system injects context from similar past playbooks using Gemini embedding similarity (RAG).
* **Strategy Cards**: Outlines target platforms, interactive hooks, and gear/pricing recommendations using Gemini Search Grounding. Pinned playbooks are saved client-side to `localStorage` for notes and Markdown exports.

![Raid Playbook Strategy Card](Gallery/PlaybookWizard5.png)

---

### F. Daily Exposes & Spotlights
The system regularly publishes editorial content analyzing top Twitch creators.

![Spotlight Entry Links](Gallery/SpotlightEntry1.png)
![Spotlight Example](Gallery/SpotlightEntry2.png)

* **Daily Expose**: Long-form expose articles containing 60-second chat logs, historical sentiments, and platform channel badges.
* **Spotlight Cabinet**: A historical catalog archive accessible via the sidebar, featuring retro CRT loading transitions.

---

## 4. Troubleshooting & Expected Initial Warnings

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

---

## 5. See Also

* [Data Pipeline Reference](data_pipeline.md) — Detailed breakdown of every external call, search performed, aggregation step, data provenance table, and known limitations.
* [Database Operations](database_operations.md) — Steps to reset, seed, backup, and restore Firestore and BigQuery databases.
