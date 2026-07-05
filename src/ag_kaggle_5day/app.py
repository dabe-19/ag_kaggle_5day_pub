import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app

from ag_kaggle_5day.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("streamer_advisor")


# ---------------------------------------------------------------------------
# Environment bootstrap
# ---------------------------------------------------------------------------
from ag_kaggle_5day.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Agent imports with graceful fallback
# ---------------------------------------------------------------------------
try:
    from ag_kaggle_5day.agents.advisor import (
        get_hourly_cache,
        refresh_hourly_cache,
    )
    from ag_kaggle_5day.agents.scraper import (
        TwitchAPIClient,
        YouTubeAPIClient,
    )

    _agents_loaded = True
except ImportError:
    _agents_loaded = False

    class TwitchAPIClient:
        is_configured = False

    class YouTubeAPIClient:
        is_configured = False

    def refresh_hourly_cache(
        api_key=None,
        twitch_client=None,
        youtube_client=None,
        search_model=None,
        analysis_model=None,
    ):
        pass

    def get_hourly_cache():
        return None


# ---------------------------------------------------------------------------
# Background hourly periodic agent scheduler
# ---------------------------------------------------------------------------
_scheduler_task: asyncio.Task | None = None


async def run_periodic_agent_scheduler(
    api_key: str,
    twitch_client,
    youtube_client,
    interval_seconds: int = 3600,
) -> None:
    """Async background task that periodically runs the metrics refresh
    and scheduled agent tasks.
    """
    await asyncio.sleep(5)

    while True:
        logger.info("Periodic agent scheduler cycle started.")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                refresh_hourly_cache,
                api_key,
                twitch_client,
                youtube_client,
            )
            logger.info("Scheduler: Hourly cache refresh complete.")
        except Exception as e:
            logger.error(f"Scheduler: Cache refresh failed: {e}", exc_info=True)

        if api_key:
            try:
                logger.info("Scheduler: Executing scheduled playbook updates...")
                from ag_kaggle_5day.routes.recommend import query_remote_agent

                prompt = (
                    "Perform scheduled database updates: generate and store "
                    "playbooks for standard profiles. Execute playbook "
                    "generation for the following:\n"
                    "1. vibe='chill', scale='starting', duration=3.0\n"
                    "2. vibe='competitive', scale='affiliate', duration=4.0\n"
                    "3. vibe='community', scale='partner', duration=2.5"
                )
                await query_remote_agent(
                    prompt,
                    user_id="scheduled_system_task",
                    session_id=f"scheduled_session_{int(time.time())}",
                    api_key=api_key,
                )
                logger.info("Scheduler: Scheduled playbook updates complete.")
            except Exception as e:
                logger.error(f"Scheduler: Scheduled updates failed: {e}", exc_info=True)

            try:
                logger.info(
                    "Scheduler: Checking if daily expose generation is needed..."
                )
                from ag_kaggle_5day.agents.advisor import trigger_daily_expose_job

                await trigger_daily_expose_job(api_key=api_key, check_24h_interval=True)
            except (ImportError, AttributeError):
                pass
            except Exception as e:
                logger.error(
                    f"Scheduler: Daily expose check failed: {e}", exc_info=True
                )
        else:
            logger.warning(
                "Scheduler: API key not available, skipping scheduled updates."
            )

        logger.info(
            f"Periodic scheduler cycle complete. Sleeping for {interval_seconds}s."
        )
        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Startup connectivity probe
# ---------------------------------------------------------------------------
def _probe_gemini_connectivity() -> None:
    try:
        import httpx

        httpx.get("https://generativelanguage.googleapis.com/", timeout=5)
        logger.info("Gemini API connectivity probe: OK — endpoint is reachable.")
    except Exception as e:
        logger.warning(
            f"Gemini API connectivity probe FAILED: {e}. "
            "Comparison reports and recommendations will be unavailable. "
            "Check GEMINI_API_KEY format (no surrounding quotes in .env) "
            "and outbound HTTPS access from the container."
        )


# ---------------------------------------------------------------------------
# FastAPI lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup: populates the cache and starts the hourly timer."""
    app.state.settings = settings
    api_key = settings.GEMINI_API_KEY
    twitch = TwitchAPIClient()
    youtube = YouTubeAPIClient()

    app.state.twitch = twitch
    app.state.youtube = youtube
    app.state.cache = get_hourly_cache()

    if twitch.is_configured:
        logger.info(
            "Twitch Helix API configured — will use real concurrent viewer data."
        )
    else:
        logger.warning("TWITCH_CLIENT_ID/SECRET not set — Twitch Helix API disabled.")

    if youtube.is_configured:
        logger.info(
            "YouTube Data API v3 configured — will use real YouTube viewer data."
        )
    else:
        logger.warning("YOUTUBE_API_KEY not set — YouTube Data API disabled.")

    global _scheduler_task

    if _agents_loaded:
        try:
            from ag_kaggle_5day.agents.advisor import (
                _store,
                seed_firestore_cache_if_empty,
            )
            from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

            client = get_firestore_client()
            has_games = False
            if client:
                logger.info(
                    "Server startup: Attempting to restore cache from Firestore..."
                )
                doc_games = (
                    client.collection("system_cache").document("combined_games").get()
                )
                if doc_games.exists:
                    has_games = True
                    doc_data = doc_games.to_dict()
                    games = doc_data.get("data")
                    timestamp = doc_data.get("timestamp")
                    if games and isinstance(games, list):
                        _store.combined_games = games
                        _store.sponsored = [
                            g for g in games if g.get("tier") == "sponsored"
                        ]
                        _store.top5 = [g for g in games if g.get("tier") == "trending"][
                            :5
                        ]

                        if timestamp:
                            if hasattr(timestamp, "timestamp"):
                                _store.refreshed_at = timestamp.timestamp()
                            else:
                                _store.refreshed_at = float(timestamp)
                        else:
                            _store.refreshed_at = 0.0

                        logger.info(
                            f"Server startup: Restored {len(games)} games "
                            f"from Firestore cache. Refreshed at: {_store.refreshed_at}"
                        )

                # Try to load comparison_report document
                doc_report = (
                    client.collection("system_cache")
                    .document("comparison_report")
                    .get()
                )
                if doc_report.exists:
                    report_data = doc_report.to_dict().get("data")
                    if report_data and isinstance(report_data, dict):
                        _store.comparison_report = report_data.get("report", "")
                        logger.info(
                            "Server startup: Restored comparison report "
                            "from Firestore cache."
                        )

            if not has_games:
                seed_firestore_cache_if_empty(force=True)
                logger.info(
                    "Server startup: Firestore cache seeded successfully "
                    "(as it was empty)."
                )
        except Exception as startup_err:
            logger.warning(
                "Server startup: Firestore cache restoration or seeding "
                f"failed: {startup_err}"
            )

    if api_key:

        async def run_probe():
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _probe_gemini_connectivity)
            except Exception as pe:
                logger.warning(f"Failed to execute Gemini connectivity probe: {pe}")

        asyncio.create_task(run_probe())

    disable_scheduler = settings.DISABLE_INTERNAL_SCHEDULER or "K_SERVICE" in os.environ
    enable_initial_refresh = (
        os.environ.get("ENABLE_INITIAL_REFRESH", "false").lower() == "true"
    )

    async def run_initial_refresh():
        await asyncio.sleep(5)
        logger.info(
            "Startup initial refresh: Triggering initial hourly cache "
            "refresh in background..."
        )
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                refresh_hourly_cache,
                api_key,
                twitch,
                youtube,
            )
            logger.info("Startup initial refresh: Hourly cache refresh complete.")
        except Exception as e:
            logger.error(
                f"Startup initial refresh: Cache refresh failed: {e}", exc_info=True
            )

    if _agents_loaded:
        if disable_scheduler:
            if "K_SERVICE" in os.environ:
                logger.info(
                    "Server startup: internal background scheduler is disabled "
                    "(running on Cloud Run). Skipping initial background refresh "
                    "to prevent CPU throttling and race conditions."
                )
            else:
                logger.info(
                    "Server startup: internal background scheduler is "
                    "disabled (relying on external cron webhook)."
                )
                if enable_initial_refresh:
                    logger.info("Launching initial refresh task...")
                    asyncio.create_task(run_initial_refresh())
                else:
                    logger.info("Skipping initial refresh task (dev/test environment).")
        else:
            logger.info("Server startup: scheduling background periodic agent loop...")
            _scheduler_task = asyncio.create_task(
                run_periodic_agent_scheduler(
                    api_key=api_key,
                    twitch_client=twitch,
                    youtube_client=youtube,
                )
            )
    else:
        logger.warning(
            "Agents not loaded — running in degraded mode, skipping "
            "cache refresh scheduler."
        )
    yield
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            logger.info("Periodic agent scheduler task cancelled on shutdown.")


def get_settings(request: Request):
    return request.app.state.settings


def get_cache(request: Request):
    return request.app.state.cache


def get_twitch_client(request: Request):
    return request.app.state.twitch


def get_youtube_client(request: Request):
    return request.app.state.youtube


# ---------------------------------------------------------------------------
# App (Exposed via Google ADK for Agent Runtime compliance)
# ---------------------------------------------------------------------------
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri="sqlite+aiosqlite:///./sessions.db",
    allow_origins=["*"],
    web=False,
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(AGENT_DIR, "static")),
    name="static",
)


# ---------------------------------------------------------------------------
# Secure API Documentation (HTTP Basic Auth)
# ---------------------------------------------------------------------------
security = HTTPBasic()


def authenticate_developer(credentials: HTTPBasicCredentials = Depends(security)):
    expected_username = settings.DOCS_USERNAME
    expected_password = settings.DOCS_PASSWORD

    correct_username = secrets.compare_digest(credentials.username, expected_username)
    correct_password = secrets.compare_digest(credentials.password, expected_password)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app.router.routes = [
    r
    for r in app.router.routes
    if r.path not in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")
]


@app.get("/docs", include_in_schema=False)
async def secure_swagger_ui(username: str = Depends(authenticate_developer)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Secure API Docs")


@app.get("/redoc", include_in_schema=False)
async def secure_redoc_ui(username: str = Depends(authenticate_developer)):
    return get_redoc_html(openapi_url="/openapi.json", title="Secure API ReDoc")


@app.get("/openapi.json", include_in_schema=False)
async def secure_openapi_spec(username: str = Depends(authenticate_developer)):
    return get_openapi(
        title="WOR-ACLE API",
        version="1.0.0",
        routes=app.routes,
    )


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    start_time = time.time()
    route = request.url.path
    try:
        response = await call_next(request)
        process_time_ms = round((time.time() - start_time) * 1000.0, 2)
        logger.info(
            f"Request {request.method} {route} completed with "
            f"{response.status_code} in {process_time_ms}ms",
            extra={
                "event_type": "api_request",
                "route": route,
                "latency_ms": process_time_ms,
                "status_code": response.status_code,
            },
        )
        return response
    except Exception as exc:
        process_time_ms = round((time.time() - start_time) * 1000.0, 2)
        logger.error(
            f"Request {request.method} {route} failed after "
            f"{process_time_ms}ms with: {exc}",
            exc_info=True,
            extra={
                "event_type": "api_request",
                "route": route,
                "latency_ms": process_time_ms,
                "status_code": 500,
            },
        )
        return JSONResponse(
            status_code=500, content={"detail": f"Internal Server Error: {exc}"}
        )


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
            key="visitor_id",
            value=visitor_id,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            max_age=365 * 86400,
        )
    return response


# ---------------------------------------------------------------------------
# Register Routers
# ---------------------------------------------------------------------------
from ag_kaggle_5day.routes import (  # noqa: E402
    admin_router,
    articles_router,
    auth_router,
    games_router,
    matchmaker_router,
    monitoring_router,
    news_router,
    pages_router,
    recommend_router,
    streamers_router,
)

app.include_router(pages_router)
app.include_router(games_router)
app.include_router(recommend_router)
app.include_router(news_router)
app.include_router(streamers_router)
app.include_router(matchmaker_router)
app.include_router(articles_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(monitoring_router)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
from ag_kaggle_5day.routes.admin import (  # noqa: E402
    get_deployment_nonce as get_deployment_nonce,
)
from ag_kaggle_5day.routes.matchmaker import (  # noqa: E402
    ensure_and_enrich_profile as ensure_and_enrich_profile,
)
from ag_kaggle_5day.routes.recommend import (  # noqa: E402
    extract_chat_response_and_trace as extract_chat_response_and_trace,
)
from ag_kaggle_5day.routes.recommend import (  # noqa: E402
    query_remote_agent as query_remote_agent,
)
from ag_kaggle_5day.security import decrypt_key as decrypt_key  # noqa: E402
from ag_kaggle_5day.security import encrypt_key as encrypt_key  # noqa: E402
from ag_kaggle_5day.security import (  # noqa: E402
    forecast_client_limiter as forecast_client_limiter,
)
from ag_kaggle_5day.security import (  # noqa: E402
    forecast_global_limiter as forecast_global_limiter,
)
from ag_kaggle_5day.security import (  # noqa: E402
    get_custom_report_state as get_custom_report_state,
)
from ag_kaggle_5day.security import (  # noqa: E402
    get_effective_key as get_effective_key,
)
from ag_kaggle_5day.security import recommend_limiter as recommend_limiter  # noqa: E402
from ag_kaggle_5day.security import (  # noqa: E402
    store_custom_report_state as store_custom_report_state,
)
from ag_kaggle_5day.workflow_init import advisor_runner as advisor_runner  # noqa: E402
