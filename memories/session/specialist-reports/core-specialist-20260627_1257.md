# Core Specialist Report

## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py` — Added visitor cookie middleware, HMAC hashing helpers, session-isolated custom games fetching/collection, and BigQuery session logging.

### Diff Summary
```python
# Middleware
@app.middleware("http")
async def ensure_visitor_id_cookie(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    has_visitor_id = visitor_id is not None
    if not has_visitor_id:
        import uuid
        visitor_id = str(uuid.uuid4())
        request.state.visitor_id = visitor_id
    else:
        request.state.visitor_id = visitor_id
    response = await call_next(request)
    if not has_visitor_id:
        secure_cookie = request.url.scheme == "https"
        response.set_cookie(
            key="visitor_id", value=visitor_id, httponly=True, secure=secure_cookie, samesite="lax", max_age=365 * 86400
        )
    return response

# Session / Visitor Helpers
def get_visitor_id(request: Request) -> str:
    visitor_id = getattr(request.state, "visitor_id", None)
    if not visitor_id:
        visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        import uuid
        visitor_id = str(uuid.uuid4())
    return visitor_id

def get_user_session_hash(api_key: str) -> str:
    if not api_key:
        return ""
    import hmac
    import hashlib
    return hmac.new(_session_secret.encode("utf-8"), api_key.encode("utf-8"), hashlib.sha256).hexdigest()

# Endpoint /api/games Overlay
@app.get("/api/games")
def api_get_games(request: Request, client_key: str | None = Depends(get_client_key)):
    session_id = get_user_session_hash(client_key) if client_key else None
    if not session_id:
        session_id = f"visitor_{get_visitor_id(request)}"
    else:
        session_id = f"session_{session_id}"
    games = get_cached_games()
    games = [g for g in games if not g.get("custom", False)]
    # Overlay custom games data from session state
    ...
```

### Commands Run
- `poetry run pytest tests/test_main.py` → 24 passed (exit code 0)
- `poetry run start` → Uvicorn started cleanly, restored cache, bound to 8000 (exit code 0 after cancel)

### Decisions & Alternatives
- Decoupled `custom_games` from the global `_store.combined_games` cache to prevent cross-visitor input override.
- Decoupling user-specific inputs to individual Firestore session states ensures that the client's `localStorage` and inputs are not overwritten by other visitors' custom setups.

### Risks / Follow-ups
- Follow-up: The `scraper-agent-specialist` must implement `store_user_activity` in `gcp_storage.py` to prevent dynamic import warnings, and decouple `custom_games` from the global `cache.json` in `advisor.py`.
