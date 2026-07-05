## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py`

### Diff Summary
- Defined `get_custom_report_key`, `get_custom_report_state`, and `store_custom_report_state` helper functions in `app.py`.
- Updated POST `/api/compare` and GET `/api/compare` routes to read and write custom report states using these helpers, fallbacking to local files.
- Added defensive header parsing logs to POST `/api/compare` logging header existence and effective key lengths.

### Commands Run
- `poetry run python -m py_compile src/ag_kaggle_5day/app.py` -> Completed successfully.
- `poetry run pytest tests/test_main.py` -> 20 tests passed successfully.

### Decisions & Alternatives
- Defined the caching helpers inside `app.py` to respect path ownership constraints of `core-specialist` (which cannot edit `agents/` or `advisor_agent/` files). This allows immediate verification and a green build before scraper-agent-specialist executes.
- Stored custom reports in Firestore under `custom_report_{hash}` to support stateless scaling across multi-container Cloud Run instances.

### Risks / Follow-ups
- Requires `scraper-agent-specialist` to update `workflows.py`'s `store_report` node, `advisor.py`'s scheduler logic, and `scraper.py`'s fallback chain fast validations.
