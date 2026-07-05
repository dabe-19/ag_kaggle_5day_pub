## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/advisor.py` — Limited the number of category trending games in comparison reports to the top 15 by score.

### Diff Summary
#### `src/ag_kaggle_5day/agents/advisor.py`
```diff
@@ -764,5 +764,10 @@
             category_trending.extend(sampled)
 
+    # Limit category_trending to the top 15 games by score
+    category_trending = sorted(
+        category_trending, key=lambda g: g.get("score", 0), reverse=True
+    )[:15]
+
     # Combine and deduplicate
     final_games_list = []
```

### Commands Run
- `poetry run ruff check src/ag_kaggle_5day/agents/advisor.py --fix && poetry run ruff format src/ag_kaggle_5day/agents/advisor.py`
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py`

### Decisions & Alternatives
- Capped only the comparison report prompt payload to the top 15 games, rather than limiting the global trending discovery (which remains at 100). This maintains the visual richness of the dashboard grid while eliminating model timeouts.
- Applied the limit globally across all categories inside `_generate_comparison_report` to ensure child processes for custom reports and all other category reports are protected.

### Risks / Follow-ups
- None. All 84 agent tests pass successfully.
