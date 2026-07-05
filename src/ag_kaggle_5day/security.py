import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict

from cryptography.fernet import Fernet
from fastapi import Depends, Header, HTTPException, Request

logger = logging.getLogger("streamer_advisor.security")

# ---------------------------------------------------------------------------
# Session and encryption secret setup
# ---------------------------------------------------------------------------
_session_secret = os.environ.get("SESSION_SECRET_KEY", "").strip()
if not _session_secret:
    _secret_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".session_secret"
    )
    if os.path.exists(_secret_file):
        try:
            with open(_secret_file, "r", encoding="utf-8") as _f:
                _session_secret = _f.read().strip()
        except Exception:
            pass
    if not _session_secret:
        _session_secret = str(uuid.uuid4())
        try:
            with open(_secret_file, "w", encoding="utf-8") as _f:
                _f.write(_session_secret)
        except Exception:
            pass

_hashed = hashlib.sha256(_session_secret.encode("utf-8")).digest()
_fernet_key = base64.urlsafe_b64encode(_hashed)
_fernet = Fernet(_fernet_key)


def encrypt_key(raw_key: str) -> str:
    return _fernet.encrypt(raw_key.encode("utf-8")).decode("utf-8")


def decrypt_key(encrypted_key: str) -> str | None:
    try:
        return _fernet.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def get_visitor_id(request: Request) -> str:
    visitor_id = getattr(request.state, "visitor_id", None)
    if not visitor_id:
        visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
    return visitor_id


def get_user_session_hash(api_key: str) -> str:
    if not api_key:
        return ""
    return hmac.new(
        _session_secret.encode("utf-8"), api_key.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def log_activity_safely(
    visitor_id: str,
    session_hash: str | None,
    action_type: str,
    payload: dict | None,
    duration_ms: int,
    status: str,
    error_details: str | None = None,
) -> None:
    try:
        from ag_kaggle_5day.agents.gcp_storage import store_user_activity

        store_user_activity(
            visitor_id=visitor_id,
            session_hash=session_hash,
            action_type=action_type,
            payload_data=payload,
            duration_ms=duration_ms,
            status=status,
            error_details=error_details,
        )
    except Exception as e:
        logger.warning(f"Could not log user activity: {e}")


def get_client_supplied_key(
    request: Request, x_gemini_api_key: str = None
) -> str | None:
    cookie_key = request.cookies.get("gemini_session_key")
    if cookie_key:
        decrypted = decrypt_key(cookie_key)
        if decrypted:
            return decrypted
    header_key = x_gemini_api_key or request.headers.get("X-Gemini-API-Key")
    if header_key and header_key.strip():
        return header_key.strip().strip('"').strip("'")
    return None


def get_client_key(
    request: Request, x_gemini_api_key: str = Header(None)
) -> str | None:
    return get_client_supplied_key(request, x_gemini_api_key)


def get_session_hash(
    request: Request, client_key: str | None = Depends(get_client_key)
) -> str | None:
    if client_key:
        return get_user_session_hash(client_key)
    return None


def get_effective_key(header_key: str = None) -> str:
    """Returns the key from the request header, or falls back to server env var.

    Strips surrounding quotes defensively: Docker Compose env_file passes values
    verbatim, so a value like GEMINI_API_KEY="AIza..." in .env arrives in the
    container with literal quote characters, causing the Gemini SDK to fail with
    [Errno 101] Network is unreachable.
    """
    if header_key and header_key.strip():
        return header_key.strip().strip('"').strip("'")
    raw = os.environ.get("GEMINI_API_KEY", "")
    return raw.strip().strip('"').strip("'")


def get_custom_report_key(custom_games: list[str], category: str) -> str:
    sorted_games = sorted([g.strip().lower() for g in custom_games if g.strip()])
    hash_payload = json.dumps({"games": sorted_games, "category": category})
    hash_val = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()
    return f"custom_report_{hash_val}"


def get_custom_report_filepath(custom_games: list[str], category: str) -> str:
    from ag_kaggle_5day.agents.advisor import CUSTOM_REPORT_FILE

    sorted_games = sorted([g.strip().lower() for g in custom_games if g.strip()])
    hash_payload = json.dumps({"games": sorted_games, "category": category})
    hash_val = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()
    base_dir = os.path.dirname(CUSTOM_REPORT_FILE)
    return os.path.join(base_dir, f"custom_report_{hash_val}.json")


def get_custom_report_state(custom_games: list[str], category: str) -> dict | None:
    # Try Firestore first
    try:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_app_cache_state,
            get_firestore_client,
        )

        client = get_firestore_client()
        if client:
            key = get_custom_report_key(custom_games, category)
            val = get_app_cache_state(key)
            if val is not None:
                return val
    except Exception as e:
        logger.warning(f"Failed to get custom report state from Firestore: {e}")

    # Fallback to local file
    from ag_kaggle_5day.agents.advisor import FileLock

    filepath = get_custom_report_filepath(custom_games, category)
    lock_filepath = filepath + ".lock"

    if not os.path.exists(filepath):
        from ag_kaggle_5day.agents.advisor import (
            _CUSTOM_REPORT_LOCK_FILE,
            CUSTOM_REPORT_FILE,
        )

        filepath = CUSTOM_REPORT_FILE
        lock_filepath = _CUSTOM_REPORT_LOCK_FILE

    if os.path.exists(filepath):
        try:
            lock = FileLock(lock_filepath, timeout=5)
            with lock:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    # Validate that the local file state actually matches the request
                    cached_games = data.get("custom_games", [])
                    cached_category = data.get("category", "overall")
                    sorted_cached = sorted(
                        [g.strip().lower() for g in cached_games if g.strip()]
                    )
                    sorted_req = sorted(
                        [g.strip().lower() for g in custom_games if g.strip()]
                    )
                    if sorted_cached == sorted_req and cached_category == category:
                        return data
        except Exception as e:
            logger.warning(f"Failed to read custom report file {filepath}: {e}")
    return None


def store_custom_report_state(
    custom_games: list[str], category: str, data: dict
) -> None:
    # Try Firestore first
    try:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_firestore_client,
            store_app_cache_state,
        )

        client = get_firestore_client()
        if client:
            key = get_custom_report_key(custom_games, category)
            store_app_cache_state(key, data)
            logger.info(f"Stored custom report state for key '{key}' in Firestore.")
    except Exception as e:
        logger.warning(f"Failed to store custom report state in Firestore: {e}")

    # Fallback/Write to local file as well
    from ag_kaggle_5day.agents.advisor import FileLock

    filepath = get_custom_report_filepath(custom_games, category)
    lock_filepath = filepath + ".lock"

    try:
        lock = FileLock(lock_filepath, timeout=5)
        with lock:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write custom report file {filepath}: {e}")


class RateLimiter:
    def __init__(self, requests_limit: int, window_seconds: float):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        with self.lock:
            self.requests[client_id] = [
                t for t in self.requests[client_id] if now - t < self.window_seconds
            ]
            if len(self.requests[client_id]) < self.requests_limit:
                self.requests[client_id].append(now)
                return True
            return False


def get_client_identifier(request: Request) -> str:
    ip = request.client.host if request.client else "unknown_ip"
    api_key = get_client_supplied_key(request)
    if api_key:
        key_part = api_key[:8]
        return f"{ip}:{key_part}"
    return ip


def check_rate_limit(limiter: RateLimiter, global_limiter: RateLimiter | None = None):
    def dependency(request: Request):
        if global_limiter and not global_limiter.is_allowed("global"):
            raise HTTPException(
                status_code=429,
                detail="Global rate limit exceeded. Please wait before retrying.",
            )
        client_id = get_client_identifier(request)
        if not limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please wait before retrying.",
            )

    return dependency


collect_limiter = RateLimiter(requests_limit=1, window_seconds=10.0)
compare_limiter = RateLimiter(requests_limit=1, window_seconds=10.0)
recommend_limiter = RateLimiter(requests_limit=5, window_seconds=30.0)
playbook_limiter = RateLimiter(requests_limit=3, window_seconds=30.0)
news_limiter = RateLimiter(requests_limit=5, window_seconds=30.0)

live_monitor_client_limiter = RateLimiter(requests_limit=1, window_seconds=120.0)
live_monitor_global_limiter = RateLimiter(requests_limit=10, window_seconds=60.0)

forecast_client_limiter = RateLimiter(requests_limit=2, window_seconds=60.0)
forecast_global_limiter = RateLimiter(requests_limit=15, window_seconds=60.0)

chat_stream_client_limiter = RateLimiter(requests_limit=2, window_seconds=60.0)
chat_stream_global_limiter = RateLimiter(requests_limit=15, window_seconds=60.0)

profile_client_limiter = RateLimiter(requests_limit=10, window_seconds=60.0)
profile_global_limiter = RateLimiter(requests_limit=40, window_seconds=60.0)
