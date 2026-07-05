## Full Report

### Layer: Tooling

### Files Touched
- `pyproject.toml` — Added ruff dependency to dev group and configured ruff tool settings (lines 35-47)
- `.agents/workflows/the-warden.agent.md` — Replaced linter and formatter 'None' placeholders with `poetry run ruff check` and `poetry run ruff format --check` (lines 6, 17, 34, 35, 43, 74, 75)

### Diff Summary
```toml
# pyproject.toml
 [dependency-groups]
 dev = [
-    "pytest (>=9.1.0,<10.0.0)"
-]
+    "pytest (>=9.1.0,<10.0.0)",
+    "ruff (>=0.9.0,<1.0.0)"
+]
+
+[tool.ruff]
+target-version = "py312"
+line-length = 88
+
+[tool.ruff.lint]
+select = ["E", "F", "W", "I"]
+ignore = []
```

```markdown
# .agents/workflows/the-warden.agent.md
-You are not a linter (the project has those at `None` and `None`).
+You are not a linter (the project has those at `poetry run ruff check` and `poetry run ruff format --check`).
```

### Commands Run
- `poetry lock` → 0 (Successful)
- `poetry install` → 0 (Successful)
- `poetry run ruff --version` → 0 (output: ruff 0.15.17)
- `poetry run start` → 0 (Successfully verified startup)

### Decisions & Alternatives
- Configured Ruff's target-version to py312 to be fully compatible with dependencies while running python 3.14 (Ruff defaults to 3.14 for syntax parsing but remains backward-compatible).

### Risks / Follow-ups
- None.
