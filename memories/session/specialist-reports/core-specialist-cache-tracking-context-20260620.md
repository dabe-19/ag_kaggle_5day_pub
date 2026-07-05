## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py`

### Diff Summary
- Added `custom_context: str | None = None` to `PlaybookRequest` Pydantic model.
- Created `safe_generate_stream_playbook` helper wrapper to check `advisor.py` signature dynamically using `inspect.signature` to prevent crashes when other layers are not yet updated.
- Updated `/api/playbook` endpoint to receive `custom_context` and pass it to `safe_generate_stream_playbook` and `stream_playbook_workflow`'s inputs.
- Implemented Firestore cache restoration in `lifespan(app)` startup to load `combined_games` and `comparison_report` from Firestore system_cache on boot.
- Added check in startup to seed defaults only if Firestore lacks the `combined_games` document entirely.
- Created startup background `run_initial_refresh` async task (with 5-second delay) that executes hourly cache refresh on startup, launched specifically if internal background scheduler is disabled (`disable_scheduler = True`).
- Implemented immediate `_store.combined_games` in-memory update and Firestore storage sync inside `/api/collect` to avoid lagging or waiting for the hourly refresh after scraping a new custom game.

### Commands Run
- `poetry run python -m py_compile src/ag_kaggle_5day/app.py` -> Completed successfully.
- `poetry run pytest tests/test_main.py` -> 21 tests passed successfully.

### Decisions & Alternatives
- Used `inspect.signature` inside `safe_generate_stream_playbook` to ensure that API requests do not fail while the agent layer has not yet been updated with the new signature.
- Restored `top5` and `sponsored` from `combined_games` during Firestore cache restoration to ensure that the startup cache is fully populated with all tiers.

### Risks / Follow-ups
- Requires `scraper-agent-specialist` to update the signatures in `advisor.py` and `workflows.py` to support `custom_context` and skip the affiliate playbook for single games.
