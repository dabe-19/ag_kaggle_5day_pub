## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/agents/test_agents.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/agents/advisor.py b/src/ag_kaggle_5day/agents/advisor.py
index a2d9b62..c4d62b9 100644
--- a/src/ag_kaggle_5day/agents/advisor.py
+++ b/src/ag_kaggle_5day/agents/advisor.py
@@ -155,10 +155,23 @@ def refresh_hourly_cache(
     # --- Step 3: Load custom entries and refresh their metrics ---
     custom_entries: list[dict] = []
-    if os.path.exists(CACHE_FILE):
-        try:
-            with open(CACHE_FILE, "r") as f:
-                existing = json.load(f)
-            custom_entries = [g for g in existing if g.get("custom", False)]
-        except Exception:
-            pass
+    source_games = []
+    if _store.combined_games:
+        source_games = _store.combined_games
+    else:
+        try:
+            from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state
+            db_games = get_app_cache_state("combined_games")
+            if db_games and isinstance(db_games, list):
+                source_games = db_games
+        except Exception as e:
+            logger.warning(f"Failed to load combined_games from Firestore: {e}")
+
+    if source_games:
+        custom_entries = [g for g in source_games if g.get("custom") or g.get("tier") == "custom"]
+
+    if not custom_entries and os.path.exists(CACHE_FILE):
+        try:
+            with open(CACHE_FILE, "r") as f:
+                existing = json.load(f)
+            custom_entries = [g for g in existing if g.get("custom") or g.get("tier") == "custom"]
+        except Exception:
+            pass
 
     custom_titles = [g["title"] for g in custom_entries]
@@ -176,4 +189,14 @@ def refresh_hourly_cache(
                 g["custom"] = True
                 g["tier"] = "custom"
+
+            # Merge updates back, falling back to previously known metrics
+            # for any that failed to scrape
+            updated_custom = []
+            scraped_by_title = {g["title"].lower(): g for g in custom_scraped}
+            for old_g in custom_entries:
+                t_lower = old_g["title"].lower()
+                if t_lower in scraped_by_title:
+                    updated_custom.append(scraped_by_title[t_lower])
+                else:
+                    updated_custom.append(old_g)
+            custom_entries = updated_custom
         except Exception as e:
             logger.error(f"Failed to refresh custom games viewership: {e}")
@@ -194,4 +217,16 @@ def refresh_hourly_cache(
                     g["tier"] = "editors_pick"
                     editors_pick = [g]
+                else:
+                    prev_pick = next((g for g in source_games if g.get("tier") == "editors_pick"), None)
+                    if prev_pick:
+                        editors_pick = [prev_pick]
+                    else:
+                        g = dict(editors_pick_config)
+                        g["tier"] = "editors_pick"
+                        editors_pick = [g]
             except Exception as e:
                 logger.error(f"Failed to fetch metrics for editors pick: {e}")
+                prev_pick = next((g for g in source_games if g.get("tier") == "editors_pick"), None)
+                if prev_pick:
+                    editors_pick = [prev_pick]
+                else:
+                    g = dict(editors_pick_config)
+                    g["tier"] = "editors_pick"
+                    editors_pick = [g]
 
     # --- Step 4: De-duplicate (custom > sponsored > editors_pick > trending) ---
@@ -210,4 +245,9 @@ def refresh_hourly_cache(
             combined.append(g)
 
+    # Force "tier": "sponsored" for any game in combined that belongs to SPONSORED_GAMES
+    sponsored_titles_set = {g["title"].lower() for g in SPONSORED_GAMES}
+    for g in combined:
+        if g["title"].lower() in sponsored_titles_set:
+            g["tier"] = "sponsored"
+
     # --- Step 5: Determine overall data quality ---
@@ -796,5 +836,5 @@ def seed_firestore_cache_if_empty(force: bool = False) -> None:
                     "custom": False,
-                    "tier": "staple",
+                    "tier": "sponsored",
                     "data_quality": "no_live_data",
                 }
```

### Commands Run
- `poetry run start` (Exit code: 1 - expected port conflict as server is already running on port 8000 on host)
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Exit code: 0, 54 passed)
- `poetry run ruff check` (Exit code: 0, after formatting/comment wrapping fixes)
- `poetry run pytest` (Exit code: 0, 75 passed)

### Decisions & Alternatives
- Modified custom game retention to check the in-memory cache `_store.combined_games` or Firestore cache `combined_games` document first before falling back to local `cache.json`. This ensures that on clean container redeployments, custom games are successfully restored instead of getting lost.
- Updated `seed_firestore_cache_if_empty()` to map default seeded games to `"tier": "sponsored"` rather than `"tier": "staple"`, matching the dashboard design grid expectation.
- Implemented post-merge tier enforcement to ensure sponsored games are strictly locked to `"tier": "sponsored"`, defending against fallback paths overwriting the tier category to `"trending"`.
- Isolated `test_get_cached_games_injects_history` from local files by mocking `os.path.exists` to return `False`, avoiding tests failing due to external file state.

### Risks / Follow-ups
- None.
