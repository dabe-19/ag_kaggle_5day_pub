# Data Pipeline Reference

This document describes every external endpoint hit, every search performed, and every
aggregation step the server executes when collecting and caching streaming metrics.
It is written from the source code, not from intention. Where a value is synthesised or
estimated rather than fetched from a live platform API, that is stated explicitly.

---

## Table of Contents

1. [Overview](#overview)
2. [API Clients](#api-clients)
   - [TwitchAPIClient](#twitchapiclient)
   - [YouTubeAPIClient](#youtubeapiclient)
3. [Hourly Refresh Pipeline](#hourly-refresh-pipeline)
   - [Step 1 — Trending Discovery (`discover_top_games`)](#step-1--trending-discovery)
   - [Step 2 — Sponsored Viewership (`scrape_viewership_for_games`)](#step-2--sponsored-viewership)
   - [Step 3 — De-duplication](#step-3--de-duplication)
   - [Step 4 — Comparison Report (`_generate_comparison_report`)](#step-4--comparison-report)
   - [Step 5 — Data Quality Rollup](#step-5--data-quality-rollup)
   - [Step 6 — Persistence](#step-6--persistence)
   - [Step 7 — Sentiment Sampling & Chat Summarizer](#step-7--sentiment-sampling--chat-summarizer)
4. [On-Demand Custom Scrape (`scrape_metrics`)](#on-demand-custom-scrape)
5. [Recommendation Query (`get_recommendation`)](#recommendation-query)
6. [Playbook Query (`generate_stream_playbook`)](#playbook-query)
7. [News Query (`get_game_news`)](#news-query)
8. [Data Provenance and Honest Limitations](#data-provenance-and-honest-limitations)
9. [Known Issues and Improvement Areas](#known-issues-and-improvement-areas)

---

## Overview

The scheduling of the metrics collection pipeline differs between local development and production environments:

*   **Local Development**: The server runs an async periodic agent scheduler task (`run_periodic_agent_scheduler`) managed by the FastAPI lifespan, which triggers on startup and every 3600 seconds thereafter.
*   **Production (Cloud Run)**: The internal periodic scheduler is disabled (to avoid cold start blocking and CPU throttling). Instead, the hourly update is orchestrated by **Google Cloud Scheduler**, which triggers a dedicated **Cloud Run Job** running the `cron-refresh` command. The job runs the scraping and playbook generation task to completion before terminating, persisting results directly to BigQuery and Firestore.

In both configurations:
*   Each cycle updates the cache, writes metrics history to Google BigQuery, and invokes the advisor agent to generate playbooks for standard gamer profiles to populate the Google Firestore vector database.
*   All visitors share the resulting Firestore cache; no per-visitor scraping occurs for trending or sponsored data.
*   To ensure fast startup and avoid process hangs, the pipeline runs all metrics collection queries (Twitch Helix and YouTube Data API) concurrently in parallel threads using a `ThreadPoolExecutor`.
*   Custom games (user-entered titles) are scraped on demand only when the user clicks **Refresh Custom Games**.

The pipeline has three resolution tiers, evaluated in order:

| Tier | Source | `data_quality` field |
|---|---|---|
| 1 (primary) | Twitch Helix API + YouTube Data API v3 | `"live"` |
| 2 (fallback) | Gemini + Google Search Grounding | `"estimated"` |
| 3 (last resort) | `SPONSORED_GAMES` hard-coded constants | `"no_live_data"` |

**Random simulation has been removed.** All viewer counts are either live API data,
Gemini-synthesised estimates from live search, or unmodified baseline constants. The
`data_quality` field is carried on every game dict and surfaced as a badge in the UI
(✓ Live, ~ Estimated, ✗ No Live Data).

---

## API Clients

### TwitchAPIClient

**Location:** `src/ag_kaggle_5day/agents/scraper/twitch.py`

Wraps the Twitch Helix API using the App Access Token (Client Credentials) flow.
No user login is required.

**Credentials required:** `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` (env vars or `.env`).
**`is_configured` property:** returns `False` when either credential is absent; the pipeline
skips this client gracefully.

#### Token Acquisition

| Property | Value |
|---|---|
| Endpoint | `POST https://id.twitch.tv/oauth2/token` |
| Body | `client_id=<id>&client_secret=<secret>&grant_type=client_credentials` |
| Token lifetime | `expires_in` seconds (typically ~60 days) |
| Caching | Token stored in-memory with `_token_expires_at`; re-fetched 60s before expiry |

The token is never logged or written to disk.

#### `get_top_games(n=100)`

| Property | Value |
|---|---|
| Endpoint | `GET https://api.twitch.tv/helix/games/top?first=N` |
| Auth | `Authorization: Bearer <token>`, `Client-Id: <id>` |
| Timeout | 10 seconds |
| Returns | List of `{id, name, box_art_url}` — games sorted by live viewer count |

This endpoint returns game rankings but **does not return viewer counts**. Viewer counts
are retrieved separately by `get_viewers_for_game`.

#### `get_game_id(game_name)`

| Property | Value |
|---|---|
| Endpoint | `GET https://api.twitch.tv/helix/games?name=<game_name>` |
| Returns | Twitch `game_id` string, or `None` if not found |

Used when a staple or custom game title needs to be resolved to an ID.

#### `get_viewers_for_game(game_id, game_name)`

| Property | Value |
|---|---|
| Endpoint | `GET https://api.twitch.tv/helix/streams?game_id=<id>&first=100` |
| Pagination | Up to 3 pages (300 streams max) using `pagination.cursor` |
| Aggregation | `sum(stream["viewer_count"])` across all returned streams |
| Returns | `{"twitch_viewers": int, "stream_count": int}` |

These are real concurrent Twitch viewer counts. The 3-page cap keeps the total request
count bounded while covering the vast majority of a game's audience (top-300 channels
cover virtually all viewers for any major game).

---

### YouTubeAPIClient

**Location:** `src/ag_kaggle_5day/agents/scraper/youtube.py`

Wraps YouTube Data API v3 to retrieve concurrent viewer counts for live gaming streams.

**Credential required:** `YOUTUBE_API_KEY` (env var or `.env`).
**Free quota:** 10,000 units/day. Each `get_viewers_for_game` call costs ~101 units
(100 for `search.list` + 1 for `videos.list`).

**`is_configured` property:** returns `False` when the key is absent or when the client has been temporarily disabled due to quota exhaustion/rate limiting; YouTube viewer counts default to 0 and only Twitch data is used.

#### Rate Limit & Quota Exhaustion Caching
To prevent exhausting the low daily free quota of the YouTube Data API v3 and to avoid log spam, the `YouTubeAPIClient` utilizes a class-level variable `_quota_exceeded = False` to cache rate-limit and quota statuses:
- If a request to `search.list` or `videos.list` returns a `403` (quota exceeded) or `429` (too many requests) status code, the client sets `_quota_exceeded = True` and logs a warning.
- For all subsequent game scraping requests, the client checks this flag and immediately returns `{"youtube_viewers": 0, "stream_count": 0}` without making outbound HTTP requests.
- The flag is reset to `False` if the client is re-initialized with an explicit `api_key` (supporting dynamic API key updates from the settings dashboard).

#### `get_viewers_for_game(game_name, max_results=50)`

To prevent hanging the process when YouTube APIs are slow or unreachable, outbound API calls are configured with a strict **3-second timeout**. No artificial sleep delays are introduced during concurrent fetches.

**Step 1 — search.list (100 quota units):**

| Property | Value |
|---|---|
| Endpoint | `GET https://www.googleapis.com/youtube/v3/search` |
| Parameters | `key`, `q=<game_name>`, `type=video`, `eventType=live`, `videoCategoryId=20`, `part=id`, `maxResults=50` |
| Returns | Up to 50 video IDs for live gaming streams matching the game name |

**Step 2 — videos.list (~1 quota unit):**

| Property | Value |
|---|---|
| Endpoint | `GET https://www.googleapis.com/youtube/v3/videos` |
| Parameters | `key`, `id=<comma-joined video IDs>`, `part=liveStreamingDetails` |
| Returns | `liveStreamingDetails.concurrentViewers` per video |

**Aggregation:** `sum(int(video["liveStreamingDetails"]["concurrentViewers"]))` across all
returned videos.

> ⚠️ **Limitation:** YouTube's `search.list` cannot filter by an exact "game category"
> field — it searches by keyword (`q=<game_name>`). Results may include streams that
> mention the game in the title but are not actively playing it. The viewer count may be
> slightly overstated as a result.

---

## Hourly Refresh Pipeline

**Entry point:** `advisor.refresh_hourly_cache()` — `src/ag_kaggle_5day/agents/advisor/cache.py`

Clients are instantiated once at server startup in `app.py` and passed through the
refresh call chain. The lifespan logs whether each API is configured at startup.

### Step 1 — Trending Discovery

**Function:** `scraper.discover_top_games(api_key, twitch_client, youtube_client, category="overall", limit=10)` — `src/ag_kaggle_5day/agents/scraper/discovery.py`

Resolution order:

#### Path A — Twitch Helix API + YouTube Data API v3 (Decoupled & Parallelized)

1. `twitch_client.get_top_games_by_category(category, limit)` → retrieves up to the top 100 games by Twitch viewer count for the specified category.
2. Concurrent fetch via `ThreadPoolExecutor` for each trending game:
   - `twitch_client.get_viewers_for_game(game_id, game_name)` → real Twitch viewers.
   - `twitch_client.get_top_streamers(game_id, limit=3)` → retrieves metadata (username, login, title, viewer count) for the top 3 live streamers.
   - `youtube_client.get_viewers_for_game(game_name)` → real YouTube viewers (if YouTube is configured).
     * *Quota Limitation*: To prevent candidate pool runaway and conserve YouTube API unit quota, the live YouTube `top_streamers` list is only parsed and retained for the **top 20 games** in the trending list. For any game at index >= 20, the live YouTube streamers list is discarded (`top_streamers = []`).
   - If either API client is unconfigured, the pipeline continues with the configured one, setting the other's viewership count to `0`.
3. `avg_length_hours`: `_estimate_avg_length()` checks `SPONSORED_GAMES` first, defaulting to `3.0` hours immediately. **No Gemini/LLM API calls are executed.**
4. `score`: computed via `_calculate_score(twitch_v, youtube_v)` — logarithmic scale, 0-100.
5. Tagged `data_quality: "live"`, `source: "Twitch Helix API"` (with `+ YouTube Data API v3` if YouTube viewers > 0), and includes `top_streamers` list.

#### Path B — Gemini + Google Search Grounding

Used only when Twitch Helix is unconfigured or fails.

| Property | Value |
|---|---|
| Model | `gemma-4-31b-it` |
| API endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent` |
| Tool | `google_search` (Gemini Search Grounding) |
| Expected output | JSON array of 10 objects |

Prompt requests: `title`, `category`, `estimated_twitch_viewers`, `estimated_youtube_viewers`,
`avg_length_hours`, `score` (0-100), `source`, `source_url`.

Tagged `data_quality: "estimated"`, `source: "Gemini Search Estimate"`.

> ⚠️ Numbers are Gemini-synthesised from live search results, not from a streaming API.
> The `source_url` is model-generated and may not be the exact source of the figure.

#### Path C — SPONSORED_GAMES baseline

Used when both A and B fail. First `limit` entries from `SPONSORED_GAMES` are returned with their
exact baseline constants — **no noise, no randomisation**.

Tagged `data_quality: "no_live_data"`, `source: "Local Fallback (no live data)"`.

---

### Step 2 — Sponsored Viewership

**Function:** `scraper.scrape_viewership_for_games(game_titles, api_key, twitch_client, youtube_client)` — `src/ag_kaggle_5day/agents/scraper/discovery.py`

Called with the titles from `SPONSORED_GAMES` (e.g. `Minecraft`, `Elden Ring`, `VALORANT`, `Hades II`).

#### Path A — Twitch Helix + YouTube (Decoupled & Parallelized)

Scrapes all sponsored game titles concurrently in parallel threads using a `ThreadPoolExecutor`:
1. If Twitch Helix is configured: `twitch_client.get_game_id(title)` resolves the title to `game_id`, `twitch_client.get_viewers_for_game(game_id, title)` aggregates Twitch viewers, and `twitch_client.get_top_streamers(game_id)` retrieves the top 3 live streamers.
2. If YouTube Data API is configured: `youtube_client.get_viewers_for_game(title)` retrieves YouTube viewers. Just as in trending discovery, if the YouTube scrape index reaches or exceeds 20, the live `top_streamers` lists are discarded to save API quota.
3. If either Twitch or YouTube client is not configured, the configured one is queried and the other defaults to `0`.
4. `avg_length_hours` resolves to the SPONSORED baseline immediately, bypassing Gemini queries.
5. `score` is computed via `_calculate_score()` and tagged `data_quality: "live"`.

#### Path B — Gemini fallback (for any unresolved titles)

If Twitch could not resolve a title (game not found in Helix), Gemini Search Grounding
is called for the unresolved batch. Tagged `data_quality: "estimated"`.

#### Path C — SPONSORED_GAMES exact baseline

If a title is in `SPONSORED_GAMES` and neither API nor Gemini returned it, the exact
`avg_viewers` constant is used with `youtube_viewers = 0` — **no noise or randomisation**.
Tagged `data_quality: "no_live_data"`.

#### Path D — Unknown game

If a title is not in `SPONSORED_GAMES` and all sources failed:
`twitch_viewers = 0`, `youtube_viewers = 0`, `score = 0`.
Tagged `data_quality: "no_live_data"`, `source: "No data available"`.
**No random numbers are generated.**

---

### Step 3 — De-duplication

`src/ag_kaggle_5day/agents/advisor/reports.py`. The combined list is `trending + sponsored`. Titles are lower-cased and
deduplicated in insertion order; trending entries take precedence over sponsored entries.

---

### Step 4 — Comparison Report (Deprecated)

> [!NOTE]
> Comparative HTML Reports have been deprecated and disabled to conserve Gemini API quota. The system now utilizes the **Medium-Form Article (Spotlight) Workflow** and **Daily Expose Workflow** to generate targeted streamer insights and cluster exposes displayed in the Vibe Tribe chat UI.

#### Medium-Form Article (Spotlight) Workflow:
This workflow runs when a user requests a spotlight analysis for a specific streamer handle via the chatbot overlay. It checks metrics, drafts a creative spotlight via Gemini, edits/formats it to match the retro arcade aesthetic, and delivers it to the chat UI.

#### Daily Expose Workflow:
This workflow runs daily to identify candidate streamers from correlation clusters, construct dossiers, evaluate the most interesting candidate handle, write a long-form expose using Gemini, format it with clickable links, and store the output in Firestore vector storage.

---

### Step 5 — Data Quality Rollup

`src/ag_kaggle_5day/agents/advisor/cache.py`. After combining trending and sponsored results, the `data_quality` field of all
entries is examined:

| Condition | `store.data_quality` | UI signal |
|---|---|---|
| Any entry has `"live"` | `"live"` | ✓ Live Data |
| No `"live"`, any `"estimated"` | `"estimated"` | ~ Estimated |
| All `"no_live_data"` | `"no_live_data"` | ✗ No Live Data |

This summary is exposed at `GET /api/cache/status` under the `data_quality` key.

---

### Step 6 — Persistence & Historical Metrics

After the store is updated in memory, the combined game list is written locally and remotely:
1. **Local cache.json**: Persisted with a `FileLock` (`cache.json.lock`) to eliminate race conditions.
2. **Google BigQuery**: Stored in the `streamer_metrics.hourly_stats` table for historical trends. The fields written are `timestamp`, `title`, `category`, `avg_viewers`, `twitch_viewers`, `youtube_viewers`, `avg_length_hours`, `score`, `tier`, `data_quality`, and `source`.

---

### Step 7 — Sentiment Sampling & Chat Summarizer

**Location:** `src/ag_kaggle_5day/agents/scraper/sentinel.py`, `src/ag_kaggle_5day/agents/gcp_storage/streamer_links.py`, `src/ag_kaggle_5day/cron.py`

To track live streamer and viewer engagement, the pipeline executes a sharded background Sentinel monitoring and real-time highlight calculation:

#### 1. Streamer Candidate Selection & Sentinel Sharding
- The system resolves candidate streamers from unique handles (up to 100) using a **Three-Tier Cohort Selection Algorithm**:
  - **Tier 1 (50%)**: Online streamers currently playing games in the top 15 trending or dashboard tracked list (sorted by live viewers descending).
  - **Tier 2 (30%)**: Other online streamers (sorted by live viewers descending).
  - **Tier 3 (20%)**: Streamers sorted by historical vibe volatility (`chat_volatility` descending).
- **YouTube Connection & Promotion Filtering**: 
  - To control resource allocation, the system only includes YouTube channels that correspond to active top games or link directory connections.
  - A YouTube channel is only promoted to have a persistent profile fabric stored in Firestore if it is either **linked** to a verified Twitch account, or has processed **at least 5 messages** during the chat scrape. Empty, quiet, or unlinked YouTube accounts are discarded.
- The `RaidSentinel` background worker shards these channels across 2 persistent SSL connection pools (up to 50 channels each) to stay within anonymous Twitch IRC limits, while YouTube sentinels run in parallel.
- Connections run asynchronously concurrently with the hourly viewership scrapers for the entire 15–20 minute task duration.

#### 2. Local Lexicon-based 2D Vibe Coordinates Calculation
- Incoming chat lines are read via non-blocking streams:
  - **Twitch Chat**: Read via non-blocking socket streams from Twitch IRC.
  - **YouTube Chat**: Crawled using keyless HTML scraping on `https://www.youtube.com/live_chat?v=VIDEO_ID`. To avoid quota exhaustion, the official YouTube Data API (`liveChatMessages`) is used **strictly as a fallback** if the keyless HTML crawler fails or is blocked.
- The sentinel maps message tokens locally on CPU using defined positive and negative keywords, assigning a score $x_i \in \{-1, 0, 1\}$.
- **Rolling Sentiment Average ($\mu$)**: Calculated over a 3-minute sliding window.
- **Rolling Volatility ($\sigma$)**: Evaluated as the standard deviation of sentiment scores over the window.
- Eliminates redundant API calls and prevents Vertex AI quota exhaustion.

#### 3. Anomaly-Triggered Highlight Summaries
- **VOLUME_SPIKE**: Triggered if messages-per-minute crosses the statistical threshold (mean + 3 * std_dev) calculated over up to 100 historical checks, with a protective minimum floor of 1.5 * mean.
- **VIBE_SHIFT**: Triggered if sentiment standard deviation ($\sigma$) crosses the statistical threshold (mean + 2 * std_dev) clamped between `0.4` and `0.9`.
- **RAID**: Instantly triggered when a Twitch `USERNOTICE` raid incoming message is parsed.
- Highlights enforce a 3-minute cooldown per streamer. On triggers, raw chat logs are deduplicated, maintaining velocity metadata (e.g. `pog (x24)`), and sent to Gemini to generate a one-sentence highlight summary.

#### 4. Multi-Source Telemetry & Helix Metadata Resolution
Alongside chat analysis, the system queries Twitch Helix and Steam Web APIs to resolve metadata:
- `game_name`: The active streaming category at the time of the scrape.
- `streamer_channel_url`: The verified link to the content creator's Twitch channel.
- `stream_url`: Link to the live stream or the most recent archived VOD (`https://twitch.tv/videos/{video_id}`) via `/channel` and `/videos` API checks.
- `top_streamers_of_game`: The top 3 live streamers currently playing that game.
- `recent_clips`: Trending clips list for the broadcaster queried via Helix `/clips`.
- `game_tags`: Category classification tags resolved from top live streams under Helix `/streams` (and `/games`).
- `spectator_ratio`: Ratio of active viewers to active players fetched keylessly via Steam stats API.

To optimize execution speed and prevent rate limits during the hourly cron refresh, **all Helix metadata (clips, tags) and Steam player counts are bypassed during the shutdown flush (`is_shutdown=True` flag)**. 
- During shutdown, the system only writes the core chat sentiment coordinates (sentiment, messages, velocity, volatility) to Firestore and BigQuery.
- To prevent erasing previously saved clips/tags during this partial metrics update, Firestore writes are performed using `merge=True`.
- Quiet channels that processed fewer than 5 messages (`total_messages < 5`) are filtered out and skipped from the shutdown flush entirely.
- The full metadata queries are still executed in real-time when a highlight is triggered (`_compile_and_store_moment`), when a user views a profile on-demand, or during the daily expose profile updates.

#### 5. Storage & Database Schema Upgrades
- **Firestore**: Cached under the `streamer_sentiment` collection (rolling coordinates, latest stats, tags, clips, spectator ratio) and highlight logs under the `streamer_moments` collection (7-day TTL).
- **BigQuery Moments & Raids**: Written to `streamer_metrics.streamer_sentiment_moments` (for highlights) and `streamer_metrics.streamer_raid_history` (for raids).
- **BigQuery Schema Migration**: `chat_volatility` and `spectator_ratio` are dynamically added to the `streamer_metrics.sentiment_history` schema if missing on runtime.
- Daily consolidation reads highlights from `streamer_moments`, bypassing LLM calls completely for quiet streams.

#### 7. Daily Streamer Analytics & Profile Fabric Pipeline (Cron)
- **Function:** `run_daily_analytics_aggregation(api_key)` in [analytics.py](file:///home/wsl-ops/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/advisor/analytics.py).
- **Triggered by:** CLI command `poetry run cron-refresh --task=daily-analytics` or HTTP endpoint `POST /api/cron/analytics`.
- **Process**:
  1. **Source Discovery**: Queries BigQuery `sentiment_history` table to locate all unique streamer handles with historical checks.
  2. **Data Aggregation**: For each streamer, it pulls the complete timeline of checks from Firestore `streamer_sentiment_history`. It programmatically calculates:
     - **Active Hours Binning**: Categorizes active streaming periods into `morning`, `afternoon`, `evening`, or `latenight`.
     - **Primary Game & Top Games**: Identifies the primary game category (highest check count) and the top 5 individual game categories.
     - **Metrics Compilation**: Averages messages/minute (chat speed) and identifies the dominant overall sentiment.
     - **Dynamic Baselines Estimation**: Calculates the mean ($\mu$) and standard deviation ($\sigma$) of both messages per minute and chat volatility across the history (up to 100 checks) to define personalized control limits.
  3. **Vibe Tribe Clustering**: Runs Spectral Clustering on combined correlation matrices to group streamers into dynamic factions (Vibe Tribes). Invokes Gemini to name each tribe and generate a descriptive reasoning snippet explaining the faction's synergy.
  4. **Peer Connections**: Programmatically computes similarity connections between streamers using dynamic non-linear variable (NVAR) combinations (diurnal circular time distance, Jaccard variety game overlap, logarithmic audience engagement density difference, sentiment polarization ratio difference).
  5. **Confidence Status**: Assigns a status of `established` if the streamer has $\ge 5$ checks, otherwise `preliminary`.
  6. **Storage & Caching**:
     - Stores the historical day's snapshot in BigQuery table `streamer_metrics.streamer_analytics_timeseries`.
     - Stores the current dimension and connection mappings in BigQuery table `streamer_metrics.streamer_profile_fabric`.
     - Logs daily pairwise similarity score computations in BigQuery table `streamer_metrics.streamer_similarity_history` with foreign key constraints linking to the `streamer_profile_fabric(streamer_handle)` table (`NOT ENFORCED`).
     - Caches the current profile fabric (including the top 3 detailed peer connections with similarity percentages and explanations) under the Firestore collection `streamer_profiles` for low-latency agent lookup.

---

## On-Demand Custom Scrape

**Function:** `scraper.scrape_metrics(custom_games, api_key, twitch_client, youtube_client)` — `src/ag_kaggle_5day/agents/scraper/discovery.py`
**Triggered by:** `POST /api/collect` with a non-empty `custom_games` list.

Uses the same three-tier resolution (Twitch Helix → Gemini → SPONSORED baseline) as Step 2.
Custom entries are tagged `custom=True`, `tier="custom"`.

`cache.json` is updated under `FileLock` — the lock prevents races with the hourly refresh.

---

## Recommendation Query (RAG-Enabled)

**Function:** `advisor.get_recommendation(query, api_key)` — `src/ag_kaggle_5day/agents/advisor/recommendations.py`
**Triggered by:** `POST /api/recommend`

| Property | Value |
|---|---|
| Model | `gemma-4-31b-it` |
| Tool | `google_search` (Gemini Search Grounding) |
| Vector Search | kNN Cosine distance query in Firestore `playbooks` collection |
| Embedding Model | `gemini-embedding-001` (768 dimensions) |

Prior to querying the model, the recommendation engine computes the embedding of the user query and queries Firestore to retrieve the top 3 most similar past playbooks. These are formatted and injected into the user query contents as a RAG context block (`### Historical Context from Similar Past Playbooks:`).

> ⚠️ **Prompt injection surface:** The user's query is passed directly without sanitisation.
> The model only has access to Google Search; it cannot execute code or read local files.

---

## Playbook Query

**Function:** `advisor.generate_stream_playbook(vibe, scale, duration, api_key, model)` — `src/ag_kaggle_5day/agents/advisor/playbooks.py`
**Triggered by:** `POST /api/playbook`

| Property | Value |
|---|---|
| Model | `gemma-4-31b-it` (or user chosen chatbot model) |
| Output format | Raw JSON string containing platform, hook, and advice |
| Storage | Google Firestore `playbooks` collection with embeddings |

**Ingestion & Matching Flow:**
1. Fetches current cached games via `get_cached_games()`.
2. Computes a suitability score mapping the vibe, scale, and target duration parameters against viewership sizes and average game play lengths.
3. Separates the games: forces the inclusion of all custom tracked games, and selects the top 3 best-suited non-custom games.
4. Combines the custom games and top 3 non-custom matches for evaluation.
5. For each selected game, queries Gemini using a custom instruction requesting target platform recommendation with reasoning, an interactive hook concept, and strategic scheduling advice.
6. Upon successful playbook generation, vector embeddings of the combined metadata and advice text are generated using `gemini-embedding-001` and stored inside Firestore along with the playbook dict.

---

## News Query

**Function:** `advisor.get_game_news(game, api_key)` — `src/ag_kaggle_5day/agents/advisor/news.py`
**Triggered by:** `GET /api/news?game=<name>`

| Property | Value |
|---|---|
| Model | `gemma-4-31b-it` |
| Tool | `google_search` (Gemini Search Grounding) |
| Expected output | JSON array of 3 objects (`title`, `summary`, `url`) |

The game name from the query string is interpolated into the prompt without sanitisation.

---

## Data Provenance and Honest Limitations

| Metric | When Twitch Helix configured | When Twitch fails, Gemini configured | When all fail |
|---|---|---|---|
| Trending game titles | **Twitch Helix `get_top_games`** | **Gemini Search Grounding** | SPONSORED_GAMES list |
| `twitch_viewers` | **Helix `streams` sum (real)** | Gemini-synthesised | SPONSORED baseline (exact constant) |
| `youtube_viewers` | **YouTube Data API `concurrentViewers` sum** | Gemini-synthesised | `0` |
| `avg_length_hours` | SPONSORED baseline (known) or Gemini estimate | Gemini-synthesised | SPONSORED baseline |
| `score` | Computed: `log10(total_viewers) × 20` | Gemini-synthesised (0–100) | SPONSORED baseline |
| `source_url` | Twitch game directory URL | Gemini-generated (unverified) | Twitch directory URL |
| `data_quality` | `"live"` | `"estimated"` | `"no_live_data"` |

**Key improvement over previous implementation:**

The previous pipeline used `random.uniform(0.65, 0.85)` for the Twitch/YouTube viewer
split and `random.randint()` for viewer counts when platform APIs were unavailable. These
have been removed. If no live data is available, the `data_quality` field is set to
`"no_live_data"` and the UI renders `—` for viewer counts rather than fabricated numbers.

---

## Known Issues and Improvement Areas

| # | Issue | Location | Impact |
|---|---|---|---|
| 1 | YouTube `search.list` searches by keyword, not game category tag | `agents/scraper/` | Viewer counts may include streams mentioning the game in the title but not playing it |
| 2 | `source_url` returned by Gemini (Path B) is unverified | `agents/scraper/` | "View on Platform" links may not lead to the exact source of the figure |
| 3 | No cross-validation between trending and sponsored Twitch calls | `agents/advisor/` | The same game may appear in both lists with different viewer counts; trending figure always wins |
| 4 | Custom game names are interpolated into Gemini prompts without sanitisation | `agents/scraper/`, `agents/advisor/` | A crafted game name could attempt to manipulate the prompt. Impact is bounded by the LLM's Google Search tool grant only |
| 5 | YouTube quota: 101 units per game title × 11 titles/hour = ~1,110 units/hour | `agents/scraper/` | Peak usage is within the 10,000 unit daily free tier |

### Remaining improvement areas (not implemented)

- **YouTube game ID filter**: YouTube does not provide a reliable game-category API for live streams. A
  heuristic improvement would be to filter results by channel-level game metadata when available.
- **Twitch Helix top-game viewer count cache**: the `get_top_games` response does not include viewer
  counts, requiring N separate `get_streams` calls per game. A future optimisation could batch-fetch
  streams for all games in a single cursor-paginated loop and aggregate in one pass.
- **Persistent token storage**: the Twitch App Access Token is currently stored in-memory and lost on
  restart. Persisting it to a file (alongside `cache.json`) would avoid an extra token request on each
  cold start.
