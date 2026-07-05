## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/scraper.py`
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/agents/models.json`
- `src/ag_kaggle_5day/agents/test_agents.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/agents/models.json b/src/ag_kaggle_5day/agents/models.json
--- a/src/ag_kaggle_5day/agents/models.json
+++ b/src/ag_kaggle_5day/agents/models.json
@@ -6,5 +6,8 @@
     "news_model": "gemma-4-26b-a4b-it",
     "news_chain": ["gemma-4-26b-a4b-it"],
+    "affiliate_model": "gemma-4-26b-a4b-it",
+    "affiliate_chain": ["gemma-4-26b-a4b-it", "gemini-3.5-flash", "gemini-2.5-flash"]
 }
```

- Added the affiliate playbook generation models configuration mapping `"affiliate_model"` and `"affiliate_chain"` to fallback through `gemma-4-26b-a4b-it`, `gemini-3.5-flash`, and `gemini-2.5-flash`.
- Updated `safe_generate_content` to handle `chain_name="affiliate"` configuration.
- Extended `_infer_category` in `scraper.py` to match the "Racing" category and parse keywords related to Racing/Driving/Forza.
- Standardized staple lookup in `scrape_viewership_for_games` for the Editor's Pick game so that category properties are correctly preserved.
- Re-ordered cache de-duplication in `advisor.py`'s `refresh_hourly_cache` to `custom_entries + sponsored + editors_pick + trending` to stop lower-priority categories (like trending) from overriding specific tier flags.
- Added `matches_category` rules for `racing`, `driving`, `forza` under Action-Adventure.
- Implemented `get_affiliate_playbook` with dynamic search grounding and prior recommendations injection.
- Added comprehensive unit tests in `test_agents.py` for affiliate playbook dynamic generation and random grid positioning, successfully verified via pytest.

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Exit code: 0, 53 passed)

### Decisions & Alternatives
- Mocked `get_affiliate_playbook` and `safe_generate_content` in the playbook random insertion tests. This prevents tests from making real API calls, bypassing any rate-limiting/token issues and ensuring robust, fast test execution.
- Added explicit category rules for Racing/Driving under Action-Adventure to ensure "Forza Horizon 6" displays properly when filters are selected on the dashboard.

### Risks / Follow-ups
- Need to coordinate with frontend-specialist to update `dashboard.html` for the Racing category filters and affiliate card grid injection.
