## Full Report

### Layer: core-specialist

### Files Touched
- `src/agent.py` — Fixed Reasoning Engine `ModuleNotFoundError` by inserting `sys.path` adjustment.
- `src/ag_kaggle_5day/app.py` — Updated request schema (`PlaybookRequest`) and `/api/playbook` endpoint to dynamically route "Stream Gear & Setup" queries directly to the advisor. Standardized startup configuration fallback keys and price estimates.
- `src/ag_kaggle_5day/dashboard.html` — Removed green visual overrides in initial rendering and curation board. Implemented invisible affiliate placeholder generation sequentially aligned with target indices (randomIndex >= 2).

### Diff Summary
```diff
# 1. src/agent.py import path resolution
+import os
+import sys
+
+# Ensure the parent directory (src/) is in sys.path so ag_kaggle_5day is importable in packaged environments.
+sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
+
 from ag_kaggle_5day.advisor_agent.agent import root_agent as root_agent

# 2. src/ag_kaggle_5day/app.py schema and endpoint update
 class PlaybookRequest(BaseModel):
     ...
     custom_context: str | None = None
+    previous_playbooks: list[dict] | None = None
 
+        if req.game == "Stream Gear & Setup":
+            from ag_kaggle_5day.agents.advisor import get_affiliate_playbook
+            key = get_effective_key(x_gemini_api_key) if x_gemini_api_key and x_gemini_api_key.strip() else None
+            aff_playbook = get_affiliate_playbook(..., previous_playbooks=req.previous_playbooks)
+            return {"playbooks": [aff_playbook]}
```

### Commands Run
- `poetry run pytest tests/test_main.py` → exit 0 (22 passed)

### Decisions & Alternatives
- Dynamically inserted `src` parent directory in `agent.py` rather than altering Vertex AI runtime packaging commands to guarantee robustness.
- Intercepted affiliate requests directly in `api_playbook` to avoid complex state machine changes in ADK workflows.

### Risks / Follow-ups
- None.
