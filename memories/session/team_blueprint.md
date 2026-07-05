# Team Blueprint

## Operator Inputs
- **Naming Convention**: Neutral
- **Primary Language**: Python
- **Package Manager**: Poetry

## Roster (Canonical Core)
All 10 canonical-core agents are included verbatim:
1. `the-architect` (Base Template: `the-architect.template.agent.md`)
2. `dispatcher` (Base Template: `dispatcher.template.agent.md`)
3. `quartermaster` (Base Template: `quartermaster.template.agent.md`)
4. `tester` (Base Template: `tester.template.agent.md`)
5. `george` (Base Template: `george.template.agent.md`)
6. `the-tyler` (Base Template: `the-tyler.template.agent.md` - Security Auditor / Out-of-Pipeline)
7. `the-warden` (Base Template: `the-warden.template.agent.md` - Style Reviewer / Out-of-Pipeline)
8. `the-chronicler` (Base Template: `the-chronicler.template.agent.md` - Out-of-Pipeline Docs Steward)
9. `git-manager` (Base Template: `git-manager.template.agent.md`)
10. `trowel` (Base Template: `trowel.template.agent.md`)

## Roster (Project-Specific Layer Specialists)

### `core-specialist`
- **Description**: Specialist for managing core FastAPI application logic, endpoints, HTML/CSS dashboard layout, and logging setup.
- **Argument-hint**: Path of the core file to edit or task description.
- **Rules Summary**: Restricted to changes under `src/ag_kaggle_5day/` (excluding `src/ag_kaggle_5day/agents/`).
- **Workflow Summary**: Reads, edits, and coordinates verification of core application layers.
- **Platform Context**:
  - **Owned Paths**: `src/ag_kaggle_5day/` (excluding `src/ag_kaggle_5day/agents/`)
  - **Build Command**: `poetry run start`
  - **Test Command**: `poetry run pytest tests/test_main.py`
  - **Lint/Format Command**: None pre-configured
  - **Gotchas**: Keep event loop non-blocking; daemon thread timers must reschedule cleanly.

### `scraper-agent-specialist`
- **Description**: Specialist for YouTube/Twitch live scrapers, LLM caching, and advisor recommendation models.
- **Argument-hint**: Path of scraper or agent file or integration test task.
- **Rules Summary**: Restricted to changes under `src/ag_kaggle_5day/agents/`. Must handle rate limits and protect secrets.
- **Workflow Summary**: Drafts scraper flows, schedules periodic scraping, and implements recommendation queries.
- **Platform Context**:
  - **Owned Paths**: `src/ag_kaggle_5day/agents/`
  - **Build Command**: `poetry run start`
  - **Test Command**: `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py`
  - **Lint/Format Command**: None pre-configured
  - **Gotchas**: Be mindful of low YouTube API quotas (managed via cache), Twitch Helix stream pagination caps, and outbound container network reachability issues.

## Implementation Plan Schema
The implementation plan (`implementation_plan.md`) must enumerate every project-specific layer specialist by name in the `### Touched Layers (Handoff Routing)` section:
- `core-specialist`
- `scraper-agent-specialist`

## Fixed-Order Pipeline
The dispatcher will route active pipeline steps strictly in the following order:
1. `quartermaster` (when toolchain/dependencies change)
2. `core-specialist`
3. `scraper-agent-specialist`
4. `tester`
5. `george`

## Cross-Cutting Wiring
- `the-tyler` (Security Auditor) and `the-warden` (Style Reviewer) are cross-cutting reviewers invoked directly by `george` during the auditing phase, and are out-of-pipeline.
- `the-chronicler` (Docs Steward) is triggered post-audit once george clears the work.
- `git-manager` is triggered to commit/push when verdict is `Pass`.
- `trowel` is called to close the loop once all checks pass.

## Placeholder Resolutions
- `{{PROJECT_NAME}}` → "ag-kaggle-5day"
- `{{PRIMARY_LANGUAGE}}` → "Python"
- `{{BUILD_CMD}}` → "poetry run start"
- `{{BUILD_FLAG_GLOSSARY}}` → "Starts Uvicorn FastAPI binding to 0.0.0.0:8000 by default; supports --host and --port flags"
- `{{TEST_CMD}}` → "poetry run pytest"
- `{{TEST_FLAG_GLOSSARY}}` → "Runs both endpoint tests and mock agent unit tests"
- `{{LINT_CMD}}` → "None"
- `{{FORMAT_CMD}}` → "None"
- `{{RUN_CMD}}` → "poetry run start"
- `{{STATUS_FILE_PATH}}` → "GEORGE.md"
- `{{STYLE_GUIDE_PATH}}` → "STYLE_GUIDE.md"
- `{{ARCHITECTURE_VISION_PATH}}` → "README.md"
- `{{IMPLEMENTATION_PLAN_PATH}}` → "implementation_plan.md"
- `{{TOOLING_FILES_GLOB}}` → "pyproject.toml poetry.lock poetry.toml"
- `{{DESTRUCTIVE_SCRIPTS_BLACKLIST}}` → "make_py_project.sh"
- `{{LAYER_SPECIALIST_LIST}}` → "- **core-specialist** -> `core-specialist`\n- **scraper-agent-specialist** -> `scraper-agent-specialist`"
- `{{PIPELINE_ORDER}}` → "1. `quartermaster`\n2. `core-specialist`\n3. `scraper-agent-specialist`\n4. `tester`\n5. `george`"
- `{{LAYER_SPECIALIST_PLAN_LINES}}` → "- **core-specialist**: yes | no — {brief description of changes}\n- **scraper-agent-specialist**: yes | no — {brief description of changes}"

## Cross-Check Results
- All 10 canonical names appear verbatim: Verified
- Cross-cutting reviewers out of pipeline: Verified
- Platform context included for all specialists: Verified
- Tool tokens present: Verified
- Contract schema names listed: Verified
- Pipeline order is canonical: Verified

## Amendment Log
- **2026-06-16**: Fresh team bootstrap blueprint designed and verified under Neutral naming preference. Resolved implementation plan references directly to Antigravity's `@implementation_plan.md`.
