# Streamer Metrics Advisor: Architectural Audit & Remediation Plan

This document outlines the immediate structural anti-patterns identified in the current agent-generated codebase, providing concrete remediation steps and a strategy for enforcing these standards through automated tooling. The goal is to stabilize the system while maintaining a flat, localized code structure that remains easy to audit.

---

## 1. Mixing Raw Threading with Asyncio

### The Issue
The FastAPI application currently relies heavily on standard synchronous Python threading (`threading.Timer`, `threading.Thread`) inside the application lifespan and background tasks (e.g., the hourly cache refresh scheduler in `app.py`). Firing raw threads inside an ASGI server can lead to unhandled exceptions crashing the worker, race conditions, and blocking the main event loop if synchronous I/O operations aren't perfectly managed.

### The Fix
Rip out `threading.Timer` and `threading.Thread`. FastAPI is built on `asyncio`, and background tasks should utilize the asynchronous event loop.
* **For fire-and-forget operations** (like kicking off a background news pre-fetch after a request): Use FastAPI's native `BackgroundTasks`.
* **For continuous background loops** (like the hourly cache refresh): Use `asyncio.create_task()` wrapped in an `asyncio.sleep()` loop within the lifespan context manager.

### Automated Enforcement
* **Ruff/Flake8**: Enable the `ASYNC` rule set in Ruff (or use `flake8-async`).
* **Custom Pre-commit Hook**: Implement a lightweight bash script in your pre-commit pipeline that simply `grep`s for `import threading` or `threading.Thread` in `app.py` and `advisor.py` and fails the build if found, forcing developers (or agents) to use `asyncio`.

---

## 2. Global Mutable State & Singletons

### The Issue
The codebase relies on global variables to manage state across requests. In `advisor.py`, there is a module-level singleton `_store = _HourlyCacheStore()`. In `scraper.py`, there are global tracking flags like `YouTubeAPIClient._quota_exceeded`. Global mutable state in a web server makes testing incredibly difficult (state bleeds between tests) and causes severe race conditions under concurrent load.

### The Fix
Transition to FastAPI's Dependency Injection system (`Depends()`). Instead of importing the cache store directly into route functions, instantiate the cache and API clients during the application lifespan and inject them into the routes that need them. This keeps the architecture flat—avoiding deeply nested enterprise-style factories—while safely scoping the state to the request or application context.

### Automated Enforcement
* **Pytest**: Write tests running concurrent requests. If state is global, these tests will naturally collide and fail. 
* **Pylint/Ruff**: Enable rules that flag the `global` keyword (Ruff `PLW0603`) and module-level mutable variables.

---

## 3. Blanket Exception Catching

### The Issue
Throughout `scraper.py` and `advisor.py`, there is extensive use of `except Exception as e:`. This is a classic AI hallucination defense mechanism. Broad exception handling swallows critical systemic errors (like `KeyboardInterrupt`, `SystemExit`, syntax errors in dynamic eval, or typos in variable names), making debugging deeply frustrating.

### The Fix
Audit all `try/except` blocks. Catch specific, expected exceptions based on the exact operation being performed:
* Network calls: Catch `httpx.RequestError`, `httpx.TimeoutException`, or `requests.exceptions.RequestException`.
* JSON parsing: Catch `json.JSONDecodeError`.
* Gemini SDK: Catch `genai.errors.ClientError` or `genai.errors.ServerError`.
Let unexpected systemic errors bubble up so they fail loudly and can be explicitly addressed.

### Automated Enforcement
* **Ruff**: Enable the `BLE` (flake8-blind-except) rule set, specifically `BLE001` (Do not catch blind exception).
* **Ruff**: Enable the `TRY` (tryceratops) rule set, which enforces better exception handling practices and prevents anti-patterns like logging an error and immediately raising the same broad exception.

---

## 4. Manual Environment Bootstrapping

### The Issue
In `app.py`, there is a custom `load_env()` function that manually opens a `.env` file and parses it line by line using `.split("=", 1)`. Manual string parsing for environment variables is brittle and often fails on variables containing equals signs, inline comments, or specific quote escaping, leading to silent credential failures or networking issues when keys are malformed.

### The Fix
Remove the custom parser entirely. Use `pydantic-settings`. It integrates seamlessly with FastAPI, provides robust type validation (e.g., ensuring ports are integers, URLs are valid), and handles `.env` files automatically and safely.

### Automated Enforcement
* **Type Checking (MyPy/Pyright)**: By moving to Pydantic, your configuration becomes a fully typed object. MyPy or Pyright can be enforced in CI to ensure no part of the application attempts to access a configuration variable that doesn't exist or treats a string as an integer.
* **Ruff**: Use the `TID` (flake8-tidy-imports) rule to ban the use of `os.getenv` or `os.environ` outside of the dedicated configuration module, forcing all environment access to go through the validated Pydantic settings object.

---

## 5. Tooling Setup Checklist

To integrate these enforcement mechanisms into your local or CI/CD workflow, set up the following:

1.  **Initialize Ruff:**
    Create a `ruff.toml` or `pyproject.toml` configuration:
    ```toml
    [tool.ruff]
    select = [
        "E", "F",  # Standard Pyflakes/pycodestyle
        "BLE",     # flake8-blind-except
        "TRY",     # tryceratops
        "ASYNC",   # flake8-async
        "PLW",     # Pylint warnings (global statements)
        "TID",     # flake8-tidy-imports
    ]
    ```

2.  **Configure Pre-commit:**
    Create a `.pre-commit-config.yaml` file to run Ruff automatically before any code is committed:
    ```yaml
    repos:
      - repo: https://github.com/astral-sh/ruff-pre-commit
        rev: v0.4.4
        hooks:
          - id: ruff
            args: [ --fix ]
          - id: ruff-format
    ```

3.  **Run formatting and linting:**
    ```bash
    pip install pre-commit ruff
    pre-commit install
    ruff check .
    ```
