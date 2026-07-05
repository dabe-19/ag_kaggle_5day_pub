## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/gcp_storage.py` — Implement store_comparison_report_vector, store_news_vector, search_similar_comparison_reports, and search_similar_news (lines 236-402)
- `src/ag_kaggle_5day/agents/advisor.py` — Implement RAG injections and DB vectors storing in cache refresh, news fetch, playbook generation, and recommendations (lines 222-230, 321-364, 503-511, 701-789, 1110-1125, 1362-1390)

### Diff Summary
```diff
# In gcp_storage.py:
+def store_comparison_report_vector(report_html: str, custom_games: list[str], api_key: str) -> None:
+    """Generates embedding for a comparison report and saves to Firestore 'comparison_reports' collection."""
+    ...
+def store_news_vector(game: str, headline: str, summary: str, url: str, api_key: str) -> None:
+    ...
+def search_similar_comparison_reports(query: str, api_key: str, limit: int = 3) -> list[dict]:
+    ...
+def search_similar_news(query: str, api_key: str, limit: int = 3) -> list[dict]:
+    ...

# In advisor.py:
@@ -221,6 +221,14 @@
         _store.comparison_report = comparison_report
         _store.analysis_model = analysis_model or "gemma-4-31b-it"
+        # Save comparison report to Firestore
+        from ag_kaggle_5day.agents.gcp_storage import store_comparison_report_vector
+        try:
+            custom_games_list = [g["title"] for g in combined if g.get("custom") or g.get("tier") == "custom"]
+            store_comparison_report_vector(comparison_report, custom_games_list, api_key)
+        except Exception as store_err:
+            logger.error(f"Failed to store hourly comparison report vector: {store_err}")
```

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` → `43 passed, 7 warnings in 8.21s` (exit code 0)
- `poetry run start` → Started server successfully and verified background scheduler cycle.

### Decisions & Alternatives
- To prevent spamming the Firestore collection with duplicate news article entries, we added a duplicate check in `store_news_vector()` using Firestore queries filtering by `game` and `headline`. This check executes efficiently and stays within free-tier quotas.
- We used `BeautifulSoup` inside `store_comparison_report_vector` to strip HTML formatting before embedding reports, generating cleaner and more semantically relevant vectors.

### Risks / Follow-ups
- A Firestore composite vector index is required for the new collections (`comparison_reports` and `news_articles`). Safe error handling catches index omissions and outputs warning logs with the exact `gcloud` commands to create them.
