## Full Report

### Layer: core-specialist

### Files Touched
- `src/ag_kaggle_5day/app.py` — Added cryptographic helper functions using cryptography.fernet to encrypt and decrypt client Gemini API keys. Added `/api/auth/connect` and `/api/auth/disconnect` endpoints. Updated endpoints to fetch client keys using cookie-based dependencies (`get_client_key`) falling back to header keys for compatibility.

### Diff Summary
```diff
+from fastapi import Cookie, Response
+import base64
+import hashlib
+from cryptography.fernet import Fernet
+
+_session_secret = os.environ.get("SESSION_SECRET_KEY", "").strip()
+if not _session_secret:
+    _fernet_key = Fernet.generate_key()
+else:
+    hashed = hashlib.sha256(_session_secret.encode("utf-8")).digest()
+    _fernet_key = base64.urlsafe_b64encode(hashed)
+
+_fernet = Fernet(_fernet_key)
+
+def encrypt_key(raw_key: str) -> str:
+    return _fernet.encrypt(raw_key.encode("utf-8")).decode("utf-8")
+
+def decrypt_key(encrypted_key: str) -> str | None:
+    try:
+        return _fernet.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
+    except Exception:
+        return None
+
+def get_client_supplied_key(request: Request, x_gemini_api_key: str = None) -> str | None:
+    cookie_key = request.cookies.get("gemini_session_key")
+    if cookie_key:
+        decrypted = decrypt_key(cookie_key)
+        if decrypted:
+            return decrypted
+    header_key = x_gemini_api_key or request.headers.get("X-Gemini-API-Key")
+    if header_key and header_key.strip():
+        return header_key.strip().strip('"').strip("'")
+    return None

-def api_get_games(x_gemini_api_key: str = Header(None)):
+def api_get_games(client_key: str | None = Depends(get_client_key)):
```

### Commands Run
- `poetry run start` (Boots successfully)
- `poetry run pytest tests/test_main.py` (23 passed)

### Decisions & Alternatives
- Implemented `get_client_supplied_key` to decrypt the `gemini_session_key` cookie dynamically and seamlessly fall back to HTTP headers if no cookie is present, which guarantees full backwards compatibility with current integration and unit tests without changing their HTTP requests.

### Risks / Follow-ups
- The frontend layer specialist needs to modify `dashboard.html` to POST to `/api/auth/connect` and remove localStorage/sessionStorage caching.
