## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/models.json`
- `src/ag_kaggle_5day/agents/scraper.py`
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/agents/test_agents.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/agents/models.json b/src/ag_kaggle_5day/agents/models.json
index 470bc9d..dbf8596 100644
--- a/src/ag_kaggle_5day/agents/models.json
+++ b/src/ag_kaggle_5day/agents/models.json
@@ -1,19 +1,13 @@
 {
-  "report_model": "gemini-3.5-flash",
+  "report_model": "gemma-4-26b-a4b-it",
   "report_chain": [
-    "gemini-3.5-flash",
-    "gemini-2.5-flash",
-    "gemini-3.1-flash-lite",
-    "gemma-4-31b-it",
-    "gemma-4-26b-a4b-it"
+    "gemma-4-26b-a4b-it",
+    "gemma-4-31b-it"
   ],
   "default_model": "gemma-4-26b-a4b-it",
   "default_chain": [
     "gemma-4-26b-a4b-it",
-    "gemma-4-31b-it",
-    "gemini-3.5-flash",
-    "gemini-2.5-flash",
-    "gemini-3.1-flash-lite"
+    "gemma-4-31b-it"
   ],
   "available_models": [

diff --git a/src/ag_kaggle_5day/agents/scraper.py b/src/ag_kaggle_5day/agents/scraper.py
index 2da19d6..36c37cd 100644
--- a/src/ag_kaggle_5day/agents/scraper.py
+++ b/src/ag_kaggle_5day/agents/scraper.py
@@ -921,8 +921,8 @@ def safe_generate_content(
             if system_instruction:
                 gen_config.system_instruction = system_instruction

-            # Google Search grounding tool
-            if use_google_search:
+            # Google Search grounding tool - only enable on the first (primary) attempt
+            if use_google_search and attempt_model == attempts[0]:
                 gen_config.tools = [
                     genai_types.Tool(google_search=genai_types.GoogleSearch())
                 ]

diff --git a/src/ag_kaggle_5day/agents/advisor.py b/src/ag_kaggle_5day/agents/advisor.py
index dcbab68..8b07dfd 100644
--- a/src/ag_kaggle_5day/agents/advisor.py
+++ b/src/ag_kaggle_5day/agents/advisor.py
@@ -323,9 +323,9 @@ def refresh_hourly_cache(
                     f"Error generating comparative analytics: {report_err}</div>"
                 )
 
-    # --- Step 9: Fire-and-forget news pre-fetch (non-blocking, after report) ---
-    # News populates in the background for subsequent requests/cycles.
-    news_targets = trending + custom_entries
+    # Only pre-fetch news for games actually used in the comparison report and playbooks
+    # (top 5 trending, custom, sponsored, and editor's pick) to stay well within API limits
+    news_targets = trending[:5] + custom_entries + sponsored + editors_pick
     logger.info(
         f"Starting non-blocking news pre-fetch for "
         f"{len(news_targets)} target game(s)..."
@@ -1447,6 +1447,17 @@ _NEWS_CACHE_LOCK_FILE = NEWS_CACHE_FILE + ".lock"
 
 def parse_news_markdown(filepath: str) -> dict[str, dict]:
     if not os.path.exists(filepath):
+        # Try loading from Firestore system_cache to recover on cold start in Cloud Run
+        try:
+            from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state
+            data = get_app_cache_state("news_cache_data")
+            if data:
+                logger.info("Restored news cache from Firestore system_cache.")
+                # Save locally so we don't have to keep querying Firestore
+                write_news_markdown(filepath, data, sync_to_firestore=False)
+                return data
+        except Exception as e:
+            logger.warning(f"Failed to restore news cache from Firestore: {e}")
         return {}
 
     import re
@@ -1491,7 +1502,7 @@ def parse_news_markdown(filepath: str) -> dict[str, dict]:
     return news_data
 
 
-def write_news_markdown(filepath: str, news_data: dict[str, dict]) -> None:
+def write_news_markdown(filepath: str, news_data: dict[str, dict], sync_to_firestore: bool = True) -> None:
     try:
         lock = FileLock(_NEWS_CACHE_LOCK_FILE, timeout=5)
         with lock:
@@ -1508,6 +1519,14 @@ def write_news_markdown(filepath: str, news_data: dict[str, dict]) -> None:
 
             with open(filepath, "w", encoding="utf-8") as f:
                 f.write("\n".join(lines) + "\n")
+
+        if sync_to_firestore:
+            try:
+                from ag_kaggle_5day.agents.gcp_storage import store_app_cache_state
+                store_app_cache_state("news_cache_data", news_data)
+                logger.info("Synced news cache to Firestore system_cache.")
+            except Exception as e:
+                logger.warning(f"Failed to sync news cache to Firestore: {e}")
     except Exception as e:
         logger.warning(f"Failed to write news cache markdown: {e}")

diff --git a/src/ag_kaggle_5day/agents/test_agents.py b/src/ag_kaggle_5day/agents/test_agents.py
index 58ea348..2d83b4b 100644
--- a/src/ag_kaggle_5day/agents/test_agents.py
+++ b/src/ag_kaggle_5day/agents/test_agents.py
@@ -373,9 +373,6 @@ def test_safe_generate_content_fallback():
     assert call_models == [
         "gemma-4-31b-it",
         "gemma-4-26b-a4b-it",
-        "gemini-3.5-flash",
-        "gemini-2.5-flash",
-        "gemini-3.1-flash-lite",
     ]
```

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Passed all 51 tests)

### Decisions & Alternatives
- Modified the model fallback list to strictly include Gemma models for background tasks to avoid costly fallback chains using the developer/internal key.
- Fixed the corresponding `test_safe_generate_content_fallback` assertion to only expect Gemma models in the fallback sequence.
- Restricted `google_search` grounding to only run on the first (primary) model attempt in `safe_generate_content`, resolving the Google-side API 500 error when running search grounding on the fallback `gemma-4-31b-it` model.
- Reduced the background scraper news pre-fetching target count from 100 to top 5 trending + custom + sponsored + editors pick (~12 total) to prevent API rate limit issues.
- Added bidirectional synchronization of news markdown cache to and from Firestore `system_cache` (`news_cache_data`) for robust cold start recovery in Cloud Run.

### Risks / Follow-ups
- Disabling grounding on fallback attempts means that if the primary model is rate-limited, the fallback model will generate predictions without Google Search grounding (instead using only Firestore-cached news). This is an acceptable trade-off to avoid API errors.
