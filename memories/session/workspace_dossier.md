# Workspace Dossier

## Mode
Fresh bootstrap (no custom active team agents exist yet).

## Operator Choices
- **Output Folder**: `.agents/workflows/` (default)
- **Bootstrap Type**: Fresh bootstrap
- **Primary Language**: Python (Poetry packaging)

## Workspace Reality

### Existing Roster
- `the-deacon.agent` ([the-deacon.agent.md](file:///home/dabe/projects/ag_kaggle_5day/.agents/workflows/the-deacon.agent.md))
- `the-trestleboard.agent` ([the-trestleboard.agent.md](file:///home/dabe/projects/ag_kaggle_5day/.agents/workflows/the-trestleboard.agent.md))
- `the-secretary.agent` ([the-secretary.agent.md](file:///home/dabe/projects/ag_kaggle_5day/.agents/workflows/the-secretary.agent.md))

### Primary Stack
- **Language**: Python 3.14.2 ([.python-version:L1](file:///home/dabe/projects/ag_kaggle_5day/.python-version#L1))
- **Build/Package System**: Poetry 2.0.0 ([pyproject.toml:L23-25](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L23-L25))
- **Dependencies**: fastapi, uvicorn, google-genai, requests, beautifulsoup4, jinja2, google-api-python-client, filelock, httpx[http2] ([pyproject.toml:L10-20](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L10-L20))
- **Layout**: `src/` layout with `ag_kaggle_5day` package ([pyproject.toml:L29-31](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L29-L31))

### Runtime Topology
- **Core App**: Python execution via Poetry script entry point (`poetry run start`) executing `ag_kaggle_5day.main:start` ([pyproject.toml:L26-27](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L26-L27), [main.py:L5-18](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/main.py#L5-L18))
- **Web Layer**: FastAPI server running on Uvicorn, serving an interactive dashboard and exposing cache, recommend, news, and compare endpoints ([app.py:L224-488](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/app.py#L224-L488))
- **API Cache & Scheduler**: Server-side in-memory singleton cache store (`_HourlyCacheStore`) populated with trending, staple, and custom games. Refreshed via a daemon `threading.Timer` reschedule pattern every 3600 seconds, and cancelled in FastAPI lifespan shutdown ([advisor.py:L45-217](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/advisor.py#L45-L217), [app.py:L105-220](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/app.py#L105-L220))
- **External Viewership Clients**:
  - **Twitch Helix API**: App credentials flow (client ID & secret), fetches top games, translates to game IDs, and aggregates viewers across top streams ([scraper.py:L237-365](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/scraper.py#L237-L365))
  - **YouTube Data API v3**: Searches live streams for gaming category, aggregates current viewers, implements quota exhaustion tracking ([scraper.py:L368-553](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/scraper.py#L368-L553))
  - **Gemini Search Grounding**: Fallback viewer estimates synthesised via Google GenAI SDK with Search tool grounding ([scraper.py:L571-676](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/scraper.py#L571-L676))
  - **Static Staples**: Last-resort fallback constants from `STAPLE_GAMES` ([scraper.py:L105-140](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/scraper.py#L105-L140))

### Docs Surface
- [README.md](file:///home/dabe/projects/ag_kaggle_5day/README.md) — Streamer Metrics Advisor overview, local docker/nginx development instructions, and cloud run deployment ([README.md:L1-75](file:///home/dabe/projects/ag_kaggle_5day/README.md#L1-L75))
- [User's Guide](file:///home/dabe/projects/ag_kaggle_5day/docs/users_guide.md) — Instructions for launching, entering API keys, caching, and custom reports.
- [Deployment Guide](file:///home/dabe/projects/ag_kaggle_5day/docs/deployment_guide.md) — Guide for Docker/nginx HTTPS setups and deploying to Google Cloud Run.
- [Data Pipeline Reference](file:///home/dabe/projects/ag_kaggle_5day/docs/data_pipeline.md) — Viewership, news, and comparison logic data flows.

### Style Surface
- [STYLE_GUIDE.md](file:///home/dabe/projects/ag_kaggle_5day/STYLE_GUIDE.md) — Coding conventions, background scheduler patterns, tier/data_quality field rules, API client encapsulation, Gemini prompt instructions, and client-side markdown rendering ([STYLE_GUIDE.md:L1-61](file:///home/dabe/projects/ag_kaggle_5day/STYLE_GUIDE.md#L1-L61))

### Tests & CI
- **Test Runner**: pytest ([pyproject.toml:L33-36](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L33-L36))
- **FastAPI Endpoints Suite**: Covers main page rendering, fallback key logic, admin logs, config status, cache status ([test_main.py:L1-217](file:///home/dabe/projects/ag_kaggle_5day/tests/test_main.py#L1-L217))
- **Agents & Scrapers Unit Suite**: Covers mock Twitch/YouTube client results, cache persistence, score calculations, fallback model chaining, persistent quota storage, and news pre-fetch freshness ([test_agents.py:L1-602](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/test_agents.py#L1-L602))

### Canonical Commands with Flag Glossary
- **Run Server**: `poetry run start` (Starts Uvicorn FastAPI binding to `0.0.0.0:8000` by default; supports `--host` and `--port` flags) ([main.py:L9-15](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/main.py#L9-L15))
- **Test Suite**: `poetry run pytest` (Runs both endpoint tests and mock agent unit tests; no special flags required) ([README.md:L11-14](file:///home/dabe/projects/ag_kaggle_5day/README.md#L11-L14))
- **Docker Compose**: `docker compose up --build` (Compiles app and nginx proxy locally) ([README.md:L28-31](file:///home/dabe/projects/ag_kaggle_5day/README.md#L28-L31))
- **Lint/Format**: None pre-configured.

### Layer Path Map
- **Core App Layer**: `src/ag_kaggle_5day/` — Contains app routing, main entry, and dashboard layout.
  - *Layer Test*: `poetry run pytest tests/test_main.py`
- **Agent/Scraper Layer**: `src/ag_kaggle_5day/agents/` — Implements scrapers, model fallback configs, in-memory cache scheduler, news cache, and LLM advice.
  - *Layer Test*: `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py`
- **Verification Layer**: `tests/` — Integration and endpoint checks.
- **Infrastructure Layer**: `docker/`, `scripts/` — Container config, certificates, and Compose definitions.

### Tool Inventory
- `chrome-devtools-mcp` (`playwright` browser automation): **present** (verified in lazy loading tools)
- `run_command` (terminal execution): **present** (verified)
- `search_web` / `read_url_content`: **present** (verified)
- `view_file` / `replace_file_content`: **present** (verified)
- `ask_question`: **present** (verified)
- `antigravity/memory` tool: **absent** (simulated by direct file system writes to `memories/session/`)

### Static Roster Pre-Wiring
The team roster will pre-wire all ten canonical-core agent names verbatim:
1. `the-architect` (Core Planner)
2. `dispatcher` (Pipeline Orchestrator)
3. `quartermaster` (Tooling/Dependencies)
4. `tester` (Verification)
5. `george` (Senior Auditor)
6. `the-tyler` (Security Auditor - Cross-cutting / out-of-pipeline)
7. `the-warden` (Style Reviewer - Cross-cutting / out-of-pipeline)
8. `the-chronicler` (Docs Steward)
9. `git-manager` (Git Version Control)
10. `trowel` (Status Updater)

### Project-Specific Specialists
1. `core-specialist` (FastAPI and UI logic specialists)
2. `scraper-agent-specialist` (YouTube, Twitch, and LLM advisor specialists)

### Risk Surface
- **Credentials Exposure**: YouTube and Twitch client keys must be supplied via env files or UI and never checked in.
- **YouTube API Quotas**: Extremely low daily quota limits. Managed via quota status caching, fallback estimates, and client bypasses.
- **Twitch Helix Limits**: Stream pagination must stay capped to prevent rate blocks.
- **Outbound Connectivity**: Container network configuration can cause Gemini HTTP/2 connection errors. Checked via a startup probe.

## Open Questions
- What is the canonical absolute path of the Antigravity built-in implementation plan? We will map it in the blueprint for resolving the `{{IMPLEMENTATION_PLAN_PATH}}` placeholder.

## Citations Index
- **Pinned Python version**: [.python-version:L1-2](file:///home/dabe/projects/ag_kaggle_5day/.python-version#L1-L2)
- **Poetry project config**: [pyproject.toml:L1-37](file:///home/dabe/projects/ag_kaggle_5day/pyproject.toml#L1-L37)
- **App entry point**: [main.py:L1-19](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/main.py#L1-L19)
- **FastAPI app config**: [app.py:L1-488](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/app.py#L1-L488)
- **Advisor cache & report**: [advisor.py:L1-974](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/advisor.py#L1-L974)
- **Scrapers & APIs**: [scraper.py:L1-1246](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/scraper.py#L1-L1246)
- **Main test suite**: [test_main.py:L1-217](file:///home/dabe/projects/ag_kaggle_5day/tests/test_main.py#L1-L217)
- **Agent-specific test suite**: [test_agents.py:L1-602](file:///home/dabe/projects/ag_kaggle_5day/src/ag_kaggle_5day/agents/test_agents.py#L1-L602)
- **README file**: [README.md:L1-75](file:///home/dabe/projects/ag_kaggle_5day/README.md#L1-L75)
- **Style Guide**: [STYLE_GUIDE.md:L1-61](file:///home/dabe/projects/ag_kaggle_5day/STYLE_GUIDE.md#L1-L61)
- **George Auditor State**: [GEORGE.md:L1-46](file:///home/dabe/projects/ag_kaggle_5day/GEORGE.md#L1-L46)
