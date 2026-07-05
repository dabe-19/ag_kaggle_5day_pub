# Project Style Guide

## Python Coding Style
- Follow PEP 8 style conventions.
- Use raw strings for regular expressions.
- Avoid exposing credentials or secrets in code; load them from environment variables.
- **Strict Line Length (E501)**: Never ignore E501 or disable line-length linting in configuration files. All code, comments, docstrings, and string literals must conform to PEP 8 standards and stay within configured line-length limits (default 88 characters).

## Web Dashboard Aesthetics
**Established:** 2026-06-15 via `@implementation_plan.md`.
**Rule:** Use a dark slate background (`#0b0f19`) with radial accent gradients, frosted glassmorphism elements (`rgba(30, 41, 59, 0.45)` with blur filter), and the Google 'Outfit' font family.
**Rationale:** Provides a premium, high-contrast, modern gaming aesthetic that matches current streaming platform styles.

## Background Scheduler Pattern
**Established:** 2026-06-15 via `@implementation_plan.md`.
**Rule:** Server-side background schedulers MUST use `threading.Timer` with `daemon=True` and a self-rescheduling pattern. They MUST be cancelled in the FastAPI `lifespan` context on shutdown. Never block the event loop at startup.
**Rationale:** Keeps the single-process architecture simple and predictable; daemon threads exit with the process cleanly.

## Game Dict Tier Field
**Established:** 2026-06-15 via `@implementation_plan.md`.
**Rule:** All game dicts in the in-memory cache and `cache.json` MUST include a `"tier"` field with one of three values: `"trending"` | `"sponsored"` | `"custom"`. The UI uses this field to render tier-specific badges.
**Rationale:** Makes data provenance explicit and enables the frontend to distinguish live-discovered trending titles from fixed reference sponsored games and user-added custom games without additional API calls.

## Game Dict Data Quality Field
**Established:** 2026-06-15 via `@implementation_plan.md`.
**Rule:** All game dicts MUST include a `"data_quality"` field with one of three values: `"live"` | `"estimated"` | `"no_live_data"`.
- `"live"` — numbers come from a platform API (Twitch Helix or YouTube Data API v3).
- `"estimated"` — numbers are synthesised by Gemini Search Grounding from live search results.
- `"no_live_data"` — numbers come from the hard-coded SPONSORED_GAMES baseline; no live call succeeded.
**Rationale:** Users and the UI can distinguish real viewership numbers from model estimates and static fallbacks without reading source code.

## External API Client Class Pattern
**Established:** 2026-06-15 via `@implementation_plan.md`.
**Rule:** Each external platform API MUST be wrapped in a dedicated class (e.g. `TwitchAPIClient`, `YouTubeAPIClient`) located in `src/ag_kaggle_5day/agents/scraper.py`. The class MUST:
  1. Read credentials from env vars as defaults, accept them as constructor arguments for testing.
  2. Expose an `is_configured: bool` property that returns `False` when credentials are absent.
  3. Never log credential values; log only opaque action descriptions (e.g. "Twitch App Access Token acquired.").
  4. Use `requests` for HTTP; respect timeouts (default 10s).
**Rationale:** Isolates credential handling, enables clean mocking in tests, and makes the `is_configured` flag available to the startup lifespan for user-friendly warnings.

## External API Client Rate Limit Caching
**Established:** 2026-06-16 via `@implementation_plan.md`.
**Rule:** External API clients (e.g., `YouTubeAPIClient`) prone to rate limits or quota depletion MUST track their rate limit / quota exhaustion status using a class-level variable (e.g., `_quota_exceeded`). The client MUST check this flag in `is_configured` and at the start of API requests to bypass outgoing requests if the API is rate-limited. The flag MUST be reset when the client is initialized with an explicit API key.
**Rationale:** Prevents log spam, timeout loops, and redundant requests when the API key quota is depleted, while allowing dynamic key updates from the UI settings.

## Gemma-4 Prompt Optimization Guidelines
**Established:** 2026-06-16 via `@implementation_plan.md`.
**Rule:** Prompts designed for smaller models (specifically Gemma-4) MUST explicitly forbid generic game/genre gameplay definitions and mandate detailed, data-driven, strategic outputs. Reports must follow strict structural templates (e.g., a Comparative Table with calculated columns like ratio, specific pros/cons, and recommended durations/schedules), and advisor chat recommendations must utilize a Markdown layout (Direct Analysis, Data-Driven Match, Out-of-Sample Recommendation, Action Plan).
**Rationale:** Prevents smaller models from repeating general knowledge summaries and forces them to produce thorough, metrics-based strategic advice.

## Client-Side Markdown Rendering
**Established:** 2026-06-16 via `@implementation_plan.md`.
**Rule:** Advisor chatbot replies containing rich structural elements (lists, bold headings, checklists) MUST be parsed client-side using a standard Markdown library (e.g., `marked.js`) and formatted with CSS to maintain readability.
**Rationale:** Ensures that the advice output remains accessible and clean, avoiding raw markdown strings or crude newline-replace layout tricks.

## High-Contrast Analytical Tables
**Established:** 2026-06-16 via `@implementation_plan.md`.
**Rule:** Dashboard tables comparing multiple titles MUST employ high-contrast color values: solid dark backgrounds (`rgba(15, 23, 42, 0.8)` or greater), distinct borders (`rgba(255, 255, 255, 0.15)`), alternating row fills, and explicit color-coded tier badges.
**Rationale:** Prevents background gradients from degrading table readability and makes comparing metrics easy on all displays.

## Vector Database RAG Memory Injection
**Established:** 2026-06-19 via implementation plan `implementation_plan.md`.
**Rule:** When generating reports, playbooks, or chat recommendations, code MUST perform vector searches against Firestore collections (e.g., `playbooks`, `comparison_reports`, `news_articles`) to retrieve and inject relevant historical context. Firestore composite vector queries MUST handle `FAILED_PRECONDITION` or index errors gracefully by printing composite index creation warnings. Comparison reports HTML MUST be cleaned of tags using BeautifulSoup before embedding.
**Rationale:** Standardizes RAG memory retrieval across storage/agent layers, maintains structural output consistency, and provides clear index provisioning instructions for developers.


## Retro Arcade Styling & Rebranding
**Established:** 2026-06-19 via implementation plan `implementation_plan.md`.
**Rule:** The user interface MUST employ a dark retro-arcade cabinet theme inspired by Tron and Pac-Man. All elements (cards, buttons, inputs, headers) MUST have sharp corners with `border-radius: 0px !important`. Headings/logo MUST use the `'Press Start 2P'` font, and body text/stats/tables MUST use the `'Share Tech Mono'` font. Glowing neon borders (cyan/magenta) and CRT scanline overlays must be used to preserve the theme.
**Rationale:** Standardizes the retro-arcade visual aesthetics and cabinet co-pilot rebranding requested by the operator.


## Backend Agent Response Sanitization
**Established:** 2026-06-19 via implementation plan `implementation_plan.md`.
**Rule:** All LLM and Reasoning Engine agent responses returned via `/api/recommend` MUST pass through a sanitization filter to strip `<thought>`, `<planning>`, and other internal reasoning process tag blocks and headers before reaching the client.
**Rationale:** Prevents leaking internal agent planning, tool-selection details, and tool names to the user dashboard.


## Playbook Snapshotting & Goal Metrics
**Established:** 2026-06-19 via implementation plan `implementation_plan.md`.
**Rule:** Playbooks generated by the advisor MUST be stamped with a local generation timestamp and saved alongside a snapshot of the live metrics (Twitch/YouTube viewer counts) and news articles in the Firestore document. The UI selector MUST support specific strategic stream goals (growth, engagement, monetization, performance) mapped to targeted advice.
**Rationale:** Preserves historical context of recommendations and ensures strategic advice aligns directly with user intent at the time of generation.

## Playbook Preparation & Affiliate Gear Showcase
**Established:** 2026-06-20 via implementation plan `implementation_plan.md`.
**Rule:** Playbook advisors MUST include targeted stream preparation advice (covering hardware, software, or peripherals) in a dedicated `preparation` field, and append a feature-flagged affiliate product card at the end of the strategic playbooks list when enabled.
**Rationale:** Streamlines playbook generation with actionable setup guidelines and facilitates monetization through context-aware affiliate recommendations.

## Category-Specific Report Dataset Padding
**Established:** 2026-06-20 via implementation plan `implementation_plan.md`.
**Rule:** Comparison report datasets filtered by category MUST pad trending games to at least 5 using overall trending cache to prevent LLM prompt contradictions and report generation failures.
**Rationale:** Ensures prompt validation holds and prevents LLM failures for sparse categories.

## Client-Side Category Selector Persistence
**Established:** 2026-06-20 via implementation plan `implementation_plan.md`.
**Rule:** The user's category selection on the dashboard MUST be stored in `localStorage` and restored on page refresh to prevent reverting to default "overall" selection and disrupting ongoing report generation.
**Rationale:** Provides seamless UX and preserves category state across page reloads.


## Streamer Chat Sentiment Tracking
**Established:** 2026-06-26 via implementation plan `implementation_plan.md`.
**Rule:** Live streamer chat sentiment and speed metrics MUST be persisted to BigQuery time-partitioned tables (90-day expiration) and Firestore cache/history collections (7-day TTL history, 1-hour cache), skipping Firestore cache updates if the status is Offline.
**Rationale:** Standardizes metrics caching and provenance logging while avoiding redundant storage operations for inactive channels.


## Editorial Pass and Writer Refinement
**Established:** 2026-06-26 via implementation plan `implementation_plan.md`.
**Rule:** Article generation workflows MUST incorporate an independent Editor Agent pass and Writer Refinement pass, which are bypassed if the article is retrieved from cache.
**Rationale:** Standardizes tone/link validation and ensures style guide adherence without incurring redundant LLM costs on cached hits.


## Streamer Profile Fabric & Spotlight Dual-Section Tone
**Established:** 2026-06-26 via implementation plan `implementation_plan.md`.
**Rule:** Generated streamer spotlight articles MUST use a dual-section layout consisting of (1) "Behind the Cabinet (Spotlight Bio & Vibe)" for personality, active times, and chat interaction, and (2) "The Strategic Grid (Performance & Metrics)" for data-grounded metrics. Phrasing MUST adapt to `fabric_status`: use soft "early-telemetry" wording for `"preliminary"` status, and high-confidence metrics for `"established"` status.
**Rationale:** Prevents tone collisions and aligns spotlight content accuracy with the quantity of historical chat sentiment data collected.


## Streamer Vibe Sentinel & 2D Vibe Space
**Established:** 2026-06-28 via implementation plan `implementation_plan.md`.
**Rule:** Continuous vibe coordinates $(\mu, \sigma)$ calculated in-memory from IRC chat logs MUST be cached on Firestore `streamer_sentiment`. Highlight moments generated on speed spikes, vibe shifts, or raids MUST be saved to Firestore `streamer_moments` (7-day TTL) and BigQuery `streamer_sentiment_moments`. The `#streamer-profile-drawer` UI side drawer MUST render a 2D coordinate grid plotting the active vibe coordinates alongside a vertical timeline of recent moment highlights.
**Rationale:** Standardizes coordinates mapping and moment caching, preserving high-performance client rendering and low-cost OLAP rollups.

## Streamer Multi-Source Data Enrichment
**Established:** 2026-06-28 via implementation plan `implementation_plan.md`.
**Rule:** Streamer profiles cached on Firestore `streamer_sentiment` and returned in the `/api/streamers/{handle}/profile` endpoint MUST include a keyless-resolved `spectator_ratio` (Helix viewers / Steam active player count), a list of `recent_clips` (containing URL, views, and title), and a list of category `game_tags` (resolved from top Helix stream tags). The `#streamer-profile-drawer` UI MUST display the spectator ratio card, tag pills, and clickable clips list.
**Rationale:** Standardizes multi-source telemetry data structure across database, API, and frontend layers to enrich streamer analytics.


## Streamer Profile CRT Radar & HMI Telemetry
**Established:** 2026-06-29 via implementation plan `implementation_plan.md`.
**Rule:** The `#streamer-profile-drawer` UI side drawer MUST render a compact 60x60px circular CRT radar target plotting the active vibe coordinates $(\mu, \sigma)$ in place of the large 180px grid box. Text sizes MUST use `Share Tech Mono` at `0.88rem` (14px) for readability, section headers must use `Press Start 2P` at `0.65rem` formatted as `[ SECTION_NAME ]`, and instantaneous status (`🟢 LIVE [INSTANT]` vs `⚪ OFFLINE`) must be clearly separated from smoothed trend analytics.
**Rationale:** Optimizes side drawer vertical space, preventing excessive scrolling, and aligns with high-performance telemetry dashboard aesthetics while preserving the retro arcade theme.

## Statistical Process Control Triggers & Vibe Tribes
**Established:** 2026-06-30 via implementation plan `implementation_plan.md`.
**Rule:** Event triggers in the RaidSentinel MUST use personalized statistical control limits (mean + 3 * std_dev for chat velocity spikes, mean + 2 * std_dev for sentiment volatility shifts) calculated over historical logs (up to 100 checks) rather than static, archetype-based lookups. The Star Map UI and profiles MUST use Vibe Tribe dynamic faction assignments as the primary social classification, displaying creative naming marquee labels alongside their corresponding LLM-generated descriptive snippets.
**Rationale:** Standardizes dynamic, data-driven event detection and replaces static, repetitive categorizations with immersive retro-neon factions.


## 3D Star Map Perspective Projection & Responsive Forecasting Charts
**Established:** 2026-06-30 via implementation plan `implementation_plan.md`.
**Rule:** The Star Map visualization MUST use a lightweight 3D perspective projection engine in vanilla JavaScript/SVG. It MUST support drag-to-rotate (on the background), scroll/pinch-to-zoom, and node dragging ("stretching"). Text labels MUST be clamped to the SVG boundaries to prevent boundary overflows. Forecast and other mini-charts in drawers/tribe views MUST use `viewBox` and relative widths (`width="100%"`) to support fully responsive rendering on mobile and desktop displays.
**Rationale:** Keeps the application lightweight without adding heavy 3D rendering libraries, eliminates visual overlap/clipping bugs, and ensures dashboard features scale correctly across different screen resolutions.


## Interactive SVG Highlighting & HUD Overlays
**Established:** 2026-07-02 via implementation plan `implementation_plan.md`.
**Rule:** Web visualizations that display dense networks MUST use interactive focal highlighting (dimming unrelated links to 3% opacity while glowing active connections) and a floating HUD console box for touch/hover details.
**Rationale:** Keeps dense visuals readable, preserves crisp node presentation, and ensures accessible interactivity across desktop hover and mobile touch interfaces.



