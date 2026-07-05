## Full Report

### Layer: scraper-agent-specialist (test-isolation-fix)

### Files Touched
- `src/ag_kaggle_5day/agents/test_agents.py` — Wrapped environment-modifying mock settings in `try-finally` to ensure `app_mod.advisor_runner` is properly restored.

### Diff Summary
```diff
     app_mod.advisor_runner = mock_runner
 
+    try:
-    # Mock asyncio.sleep so the test runs instantly and terminates on second call
-    with (
-        patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]),
-        patch("ag_kaggle_5day.app.refresh_hourly_cache") as mock_refresh,
-        patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),
-    ):
-        try:
-            await run_periodic_agent_scheduler(
-                api_key="fake_key",
-                twitch_client="mock_twitch",
-                youtube_client="mock_youtube",
-                interval_seconds=10,
-            )
-        except Exception as e:
-            # We catch the Stop loop exception to end the while True loop
-            assert str(e) == "Stop loop"
-
-        assert mock_refresh.call_count == 1
-        mock_refresh.assert_called_once_with("fake_key", "mock_twitch", "mock_youtube")
+        # Mock asyncio.sleep so the test runs instantly and terminates on second call
+        with (
+            patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]),
+            patch("ag_kaggle_5day.app.refresh_hourly_cache") as mock_refresh,
+            patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),
+        ):
+            try:
+                await run_periodic_agent_scheduler(
+                    api_key="fake_key",
+                    twitch_client="mock_twitch",
+                    youtube_client="mock_youtube",
+                    interval_seconds=10,
+                )
+            except Exception as e:
+                # We catch the Stop loop exception to end the while True loop
+                assert str(e) == "Stop loop"
+
+            assert mock_refresh.call_count == 1
+            mock_refresh.assert_called_once_with("fake_key", "mock_twitch", "mock_youtube")
+    finally:
+        app_mod.advisor_runner = orig_runner
```

### Commands Run
- `poetry run start` → exit 0 (FastAPI server booted successfully)

### Decisions & Alternatives
- Dynamically saving and restoring the module runner in `try-finally` avoids polluting subsequent integration test executions.

### Risks / Follow-ups
- None.
