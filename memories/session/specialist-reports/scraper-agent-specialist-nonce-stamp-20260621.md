## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/agents/scraper.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/agents/advisor.py b/src/ag_kaggle_5day/agents/advisor.py
index a2d9b62..c4d62b9 100644
--- a/src/ag_kaggle_5day/agents/advisor.py
+++ b/src/ag_kaggle_5day/agents/advisor.py
@@ -114,2 +114,3 @@
     logger.info("=== Hourly cache refresh started ===")
+    now = time.time()
 
@@ -128,2 +129,4 @@
         logger.info(f"Trending discovery: {len(trending)} game(s) returned.")
+        for g in trending:
+            g["refreshed_at"] = now
     except Exception as e:
@@ -143,2 +146,3 @@
         for g in sponsored:
             g["tier"] = "sponsored"
+            g["refreshed_at"] = now
         logger.info(f"Sponsored viewership fetched: {len(sponsored)} game(s).")
@@ -195,2 +199,3 @@
             for g in custom_scraped:
                 g["custom"] = True
                 g["tier"] = "custom"
+                g["refreshed_at"] = now
@@ -229,2 +234,3 @@
                 if scraped:
                     g = scraped[0]
                     g["tier"] = "editors_pick"
+                    g["refreshed_at"] = now
                     editors_pick = [g]
                 else:
                     prev_pick = next(
@@ -239,2 +245,3 @@
                     else:
                         g = dict(editors_pick_config)
                         g["tier"] = "editors_pick"
+                        g["refreshed_at"] = now
                         editors_pick = [g]
@@ -262,2 +269,3 @@
                 else:
                     g = dict(editors_pick_config)
                     g["tier"] = "editors_pick"
+                    g["refreshed_at"] = now
                     editors_pick = [g]
@@ -841,2 +849,3 @@
                     "custom": False,
                     "tier": "sponsored",
                     "data_quality": "no_live_data",
+                    "refreshed_at": time.time(),
                 }
diff --git a/src/ag_kaggle_5day/agents/scraper.py b/src/ag_kaggle_5day/agents/scraper.py
index a2d9b62..c4d62b9 100644
--- a/src/ag_kaggle_5day/agents/scraper.py
+++ b/src/ag_kaggle_5day/agents/scraper.py
@@ -1805,2 +1805,3 @@
         for g in custom_results:
             g["custom"] = True
             g["tier"] = "custom"
+            g["refreshed_at"] = time.time()
```

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Exit code: 0, 54 passed)
- `poetry run ruff check` (Exit code: 0)

### Decisions & Alternatives
- Set `refreshed_at` to the current scrape timestamp for all refreshed games (trending, sponsored, custom, and editor's pick) during hourly background scrapes.
- Handled out-of-band custom metrics scrapes by attaching a fresh timestamp at the moment they are generated, ensuring they display dynamic local update times correctly.
- Fallback paths (e.g. failing to scrape and using previously cached game metrics) naturally retain their original older `refreshed_at` timestamps, informing users of data staleness.

### Risks / Follow-ups
- None.
