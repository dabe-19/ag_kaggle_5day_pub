## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/advisor_agent/workflows.py`

### Diff Summary
- Imported `get_affiliate_playbook` from `ag_kaggle_5day.agents.advisor`.
- Updated `collect_playbooks_node` to determine a random insertion index for the affiliate playbook (if it's not a single game lookup).
- Extracted the preceding playbooks context (`playbooks[:insert_idx]`) and passed it to `get_affiliate_playbook` as `previous_playbooks`.
- Inserted the generated affiliate playbook at the randomly determined index.

### Commands Run
- Pytest not run yet due to cross-layer dependency (requires `advisor.py` updates in `scraper-agent-specialist` layer).

### Decisions & Alternatives
- Passed `playbooks[:insert_idx]` as the preceding playbooks context, ensuring only already "generated" recommendations are passed to the affiliate playbook builder.

### Risks / Follow-ups
- Pending `scraper-agent-specialist` implementing `get_affiliate_playbook` in `advisor.py` to prevent import errors and execute tests.
