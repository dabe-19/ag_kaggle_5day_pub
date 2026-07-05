## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py` — Updated the lifespan startup handler to check the `K_SERVICE` and `DISABLE_INTERNAL_SCHEDULER` environment variables, skipping starting the background periodic scheduler task if either is set.

### Diff Summary
```diff
@@ -410,15 +410,25 @@
     if api_key:
         threading.Thread(target=_probe_gemini_connectivity, daemon=True).start()
 
-    if _agents_loaded:
-        logger.info("Server startup: scheduling background periodic agent loop...")
-        _scheduler_task = asyncio.create_task(
-            run_periodic_agent_scheduler(
-                api_key=api_key,
-                twitch_client=twitch,
-                youtube_client=youtube,
-            )
-        )
+    disable_scheduler = (
+        os.environ.get("DISABLE_INTERNAL_SCHEDULER", "false").lower() == "true"
+        or "K_SERVICE" in os.environ
+    )
+
+    if _agents_loaded:
+        if disable_scheduler:
+            logger.info(
+                "Server startup: internal background scheduler is disabled (relying on external cron webhook)."
+            )
+        else:
+            logger.info("Server startup: scheduling background periodic agent loop...")
+            _scheduler_task = asyncio.create_task(
+                run_periodic_agent_scheduler(
+                    api_key=api_key,
+                    twitch_client=twitch,
+                    youtube_client=youtube,
+                )
+            )
     else:
         logger.warning(
             "Agents not loaded — running in degraded mode, "
```

### Commands Run
- `poetry run start` (startup check, failed due to port 8000 being already in use by running service)
- `poetry run pytest tests/test_main.py` (verification of core logic endpoints, 21 passed)

### Decisions & Alternatives
- Automatically detect Cloud Run environment using the standard Google-provided `K_SERVICE` environment variable to ensure seamless containerized deployments without requiring manual environment setting, while still allowing explicit overrides via `DISABLE_INTERNAL_SCHEDULER`.

### Risks / Follow-ups
- Relies on Cloud Scheduler to periodically trigger `/api/cron/refresh` once per hour for Cloud Run deployments. If Cloud Scheduler is misconfigured, background metrics refresh and playbook updates will not execute.
