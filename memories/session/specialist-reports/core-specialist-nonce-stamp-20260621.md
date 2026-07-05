## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py`
- `Dockerfile` (modified by quartermaster, audited by core-specialist)

### Diff Summary
```diff
diff --git a/Dockerfile b/Dockerfile
index e3c99c9..c4d62b9 100644
--- a/Dockerfile
+++ b/Dockerfile
@@ -40,4 +40,5 @@
 # Copy application source so the package is importable at runtime
 COPY --chown=appuser:appuser --from=builder /app/src ./src
+COPY --chown=appuser:appuser service.yaml ./service.yaml
 
 ENV PYTHONPATH="/app/src"
diff --git a/src/ag_kaggle_5day/app.py b/src/ag_kaggle_5day/app.py
index a2d9b62..c4d62b9 100644
--- a/src/ag_kaggle_5day/app.py
+++ b/src/ag_kaggle_5day/app.py
@@ -1781,4 +1781,27 @@
     }
 
+def get_deployment_nonce() -> str:
+    """Reads deployment nonce from env or parses service.yaml."""
+    if "DEPLOY_NONCE" in os.environ:
+        return os.environ["DEPLOY_NONCE"]
+
+    import re
+
+    curr_dir = os.path.dirname(os.path.abspath(__file__))
+    for _ in range(5):
+        yaml_path = os.path.join(curr_dir, "service.yaml")
+        if os.path.exists(yaml_path):
+            try:
+                with open(yaml_path, "r") as f:
+                    content = f.read()
+                match = re.search(
+                    r"client\.knative\.dev/nonce:\s*['\"]?([a-zA-Z0-9_-]+)['\"]?",
+                    content,
+                )
+                if match:
+                    return match.group(1)
+            except Exception:
+                pass
+        curr_dir = os.path.dirname(curr_dir)
+
+    return "local-dev"
+
 @app.get("/api/config")
 def api_get_config():
@@ -1853,4 +1876,5 @@
         return {
+            "deployment_nonce": get_deployment_nonce(),
             "server_key_configured": has_gemini,
             "twitch_configured": has_twitch,
```

### Commands Run
- `poetry run start` (Exit code: 1 - expected port conflict as server is running on host)
- `poetry run pytest tests/test_main.py` (Exit code: 0, 21 passed)
- `poetry run ruff check` (Exit code: 0, after formatting and docstring fixes)

### Decisions & Alternatives
- Reverted dynamic import of `get_deployment_nonce` from `advisor.py` to prevent cyclic import dependency issues that would break FastAPI application load. Instead, implemented the `get_deployment_nonce` helper directly in `app.py` as it is a core-level environment detail.
- Ensured a default fallback of `"local-dev"` is returned if `service.yaml` cannot be located on the filesystem.

### Risks / Follow-ups
- None.
