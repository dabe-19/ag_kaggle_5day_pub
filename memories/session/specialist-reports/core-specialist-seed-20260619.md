## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py`
- `tests/test_main.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/app.py b/src/ag_kaggle_5day/app.py
index a648ca7..f43b33d 100644
--- a/src/ag_kaggle_5day/app.py
+++ b/src/ag_kaggle_5day/app.py
@@ -398,6 +398,15 @@
     if _agents_loaded:
+        try:
+            from ag_kaggle_5day.agents.advisor import seed_firestore_cache_if_empty
+            seed_firestore_cache_if_empty()
+            logger.info("Server startup: Firestore cache seeded successfully (if it was empty).")
+        except Exception as seed_err:
+            logger.warning(f"Server startup: Firestore cache seeding failed/skipped: {seed_err}")
+
 @app.post("/api/admin/seed")
+async def api_admin_seed(background_tasks: BackgroundTasks, x_gemini_api_key: str = Header(None)):
+    # Verifies key and seeds Firestore, triggers background refresh
```

### Commands Run
- `poetry run start` -> exit 0 (fastapi boots, logs import fallback warning as expected since advisor.py changes aren't implemented yet).

### Decisions & Alternatives
- Defined the manual seeding endpoint as `POST /api/admin/seed` to be consistent with admin namespace rules, requiring the admin api key header.
- Implemented background tasks executor to run the heavy hourly refresh in the background so that the seed response is returned immediately.

### Risks / Follow-ups
- Pending scraper-agent-specialist implementation of `seed_firestore_cache_if_empty` function in `advisor.py`.
