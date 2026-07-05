## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/advisor.py` — Updated sequential and fallback generation of playbooks to determine an insert position $\ge 2$ and pass preceding generated playbooks as context inside the generation loop.
- `src/ag_kaggle_5day/advisor_agent/workflows.py` — Updated `collect_playbooks_node` to determine `insert_idx` $\ge 2$ and pass preceding playbooks context dynamically.
- `src/ag_kaggle_5day/agents/test_agents.py` — Updated test assertions to check for `"Stream Gear & Setup"` instead of the old `"Recommended Gear & Affiliates"`.

### Diff Summary
```diff
# 1. src/ag_kaggle_5day/agents/advisor.py
-    insert_idx = random.randint(0, len(top_matches)) if not game else -1
+    insert_idx = random.randint(2, len(top_matches)) if not game and len(top_matches) >= 2 else len(top_matches) if not game else -1
+    affiliate_appended = False
 
     playbooks = []
     for idx, g in enumerate(top_matches):
-        if not game and idx == insert_idx:
+        if not game and idx == insert_idx and not affiliate_appended:
             try:
                 from ag_kaggle_5day.agents.scraper import load_model_config
 
                 config = load_model_config()
                 if config.get("enable_affiliate_playbook", False):
                     aff_playbook = get_affiliate_playbook(
                         vibe=vibe,
                         scale=scale,
                         stream_goal=stream_goal,
                         api_key=api_key,
                         previous_playbooks=list(playbooks),
                     )
                     playbooks.append(aff_playbook)
+                    affiliate_appended = True
             except Exception as aff_err:
                 logger.error(f"Error appending affiliate playbook: {aff_err}")
         title = g["title"]
 
-    if not game and len(playbooks) < len(top_matches) + 1:
+    if not game and not affiliate_appended and insert_idx >= 0:
         try:
             from ag_kaggle_5day.agents.scraper import load_model_config
 
             config = load_model_config()
             if config.get("enable_affiliate_playbook", False):
                 aff_playbook = get_affiliate_playbook(
                     vibe=vibe,
                     scale=scale,
                     stream_goal=stream_goal,
                     api_key=api_key,
                     previous_playbooks=list(playbooks),
                 )
                 playbooks.append(aff_playbook)
+                affiliate_appended = True
```

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` → exit 0 (58 passed)

### Decisions & Alternatives
- Standardized the index calculations across both fallback and workflow paths to use identical checks.
- Safeguarded `random.randint(2, N)` from throws when $N < 2$ by falling back to the end of the list.

### Risks / Follow-ups
- None.
