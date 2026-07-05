## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/advisor_agent/agent.py`
- `src/ag_kaggle_5day/advisor_agent/workflows.py`
- `src/ag_kaggle_5day/app.py`
- `src/ag_kaggle_5day/cron.py`

### Diff Summary
- `agent.py`: Registered two new Gemini tools: `get_streamer_profile_fabric` and `query_streamer_connections` with lazy imports inside the functions.
- `app.py`: Added a POST endpoint `/api/cron/analytics` executing within an asyncio thread pool executor to prevent any synchronous db/network blocking logic from halting the FastAPI server.
- `cron.py`: Implemented a CLI task `daily-analytics` calling `run_daily_analytics_aggregation(key)`. Integrated the analytics check into the `daily-expose` job to dynamically aggregate if data is stale.
- `workflows.py`: Injected `get_streamer_profile_fabric(handle)` context into the prompts for both medium-form and long-form exposes. Re-structured the output schemas to enforce exactly two main parts ("Behind the Cabinet" narrative bio & active hours and "The Strategic Grid" telemetry and recommendations). Added `TONE CONFIDENCE RULE` to softer-phrase preliminary profiles.

### Commands Run
- `poetry run pytest tests/test_main.py` → Exit 0 (24 passed)

### Decisions & Alternatives
- Opted for a section-split narrative structure for spotlight exposes, balancing friendly bio descriptions with data-driven analytics.
- Integrated the daily aggregation pipeline as a pre-requisite check in the daily expose job so that even if the cron scheduler misses a run, we guarantee fresh profile clusters on expose generation.

### Risks / Follow-ups
- Follow up by implementing the backend schemas, the daily analytics aggregator logic, and vector calculations in the `scraper-agent-specialist` phase.
