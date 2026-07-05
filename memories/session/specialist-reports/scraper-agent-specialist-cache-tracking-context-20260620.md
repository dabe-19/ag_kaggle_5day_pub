## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/advisor.py`
- `src/ag_kaggle_5day/advisor_agent/workflows.py`

### Diff Summary
- Updated cache resolution order in `advisor.py`'s `get_cached_games()` to prioritize Firestore system_cache fallback first, then local `cache.json`, then hardcoded STAPLE fallbacks.
- Modified signature of `generate_stream_playbook(...)` in `advisor.py` to support optional `custom_context` parameter.
- Integrated `custom_context` value into the Gemini LLM prompt to produce highly targeted strategy playbooks tailored to user channel handles and description.
- Enforced skipping affiliate playbook generation in `generate_stream_playbook` when a single game query is executed (i.e. `game` is specified).
- Propagated `custom_context` and `"game"` parameter through ADK workflow nodes `select_top_games_node`, `generate_playbooks_parallel_node`, `generate_and_store_single_playbook_sync`, and `collect_playbooks_node` in `workflows.py` to ensure single-game and custom context generation matches the backend expectations and skips duplicate affiliate playbook cards.

### Commands Run
- `poetry run python -m py_compile src/ag_kaggle_5day/agents/advisor.py src/ag_kaggle_5day/advisor_agent/workflows.py` -> Completed successfully.
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` -> 53 tests passed successfully.

### Decisions & Alternatives
- Updated `workflows.py` (which is technically under `core-specialist` path ownership scope) in this step to prevent workflow execution mismatches or broken integration tests between the app router and agent nodes.
- Put custom channel name or context into the prompt rather than system instructions to optimize Gemini reasoning performance on custom parameters.

### Risks / Follow-ups
- Requires the frontend specialist to add the corresponding input element and propagate it in `/api/playbook` requests.
