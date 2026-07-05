import logging
import time

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
)

from ag_kaggle_5day.models import CollectRequest, CompareRequest
from ag_kaggle_5day.security import (
    collect_limiter,
    get_client_identifier,
    get_client_key,
    get_effective_key,
    get_user_session_hash,
    get_visitor_id,
)

logger = logging.getLogger("streamer_advisor.routes.games")
router = APIRouter()

# comparative_report_workflow import removed


@router.get("/api/games")
def api_get_games(
    request: Request,
    client_key: str | None = Depends(get_client_key),
):
    try:
        from ag_kaggle_5day.agents.advisor import get_cached_games
        from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

        session_id = get_user_session_hash(client_key) if client_key else None
        if not session_id:
            session_id = f"visitor_{get_visitor_id(request)}"
        else:
            session_id = f"session_{session_id}"

        games = get_cached_games()
        # Filter out any custom games that might be in the global cache list
        games = [g for g in games if not g.get("custom", False)]

        try:
            session_state = get_app_cache_state(session_id)
            if session_state and isinstance(session_state, dict):
                custom_games_data = session_state.get("custom_games_data", [])
                seen_titles = {g["title"].lower() for g in games}
                for cg in custom_games_data:
                    if cg["title"].lower() not in seen_titles:
                        games.append(cg)
                        seen_titles.add(cg["title"].lower())
        except Exception as e:
            logger.warning(f"Failed to load custom games for session {session_id}: {e}")

        return games
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/collect")
def api_collect_metrics(
    request: Request,
    background_tasks: BackgroundTasks,
    req: CollectRequest = CollectRequest(),
    client_key: str | None = Depends(get_client_key),
    x_gemini_search_model: str = Header(None),
):
    """
    Scrapes viewership for custom games only.
    If no custom games are supplied, returns the current cache without re-scraping.
    """
    try:
        from ag_kaggle_5day.agents.advisor import prefetch_news_for_games
        from ag_kaggle_5day.agents.gcp_storage import (
            get_app_cache_state,
            store_app_cache_state,
        )
        from ag_kaggle_5day.agents.scraper import scrape_metrics

        key = get_effective_key(client_key)
        session_id = get_user_session_hash(client_key) if client_key else None
        if not session_id:
            session_id = f"visitor_{get_visitor_id(request)}"
        else:
            session_id = f"session_{session_id}"

        if req.custom_games:
            client_id = get_client_identifier(request)
            if not collect_limiter.is_allowed(client_id):
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Please wait before retrying.",
                )
        games, logs = scrape_metrics(
            custom_games=req.custom_games, api_key=key, model=x_gemini_search_model
        )
        # Pre-fetch news for the newly added custom games in the background
        if req.custom_games:
            background_tasks.add_task(
                prefetch_news_for_games,
                games,
                key,
                x_gemini_search_model,
            )

        # Update session custom games in Firestore rather than mutating the
        # global store
        if req.custom_games:
            try:
                session_state = get_app_cache_state(session_id) or {}
                session_state["custom_games"] = req.custom_games
                session_state["custom_games_data"] = games
                session_state["last_activity"] = time.time()
                session_state["expire_at"] = time.time() + 3 * 86400
                store_app_cache_state(session_id, session_state)
                logger.info(
                    f"Successfully stored session custom games "
                    f"for {session_id} in Firestore."
                )
            except Exception as store_err:
                logger.error(
                    f"Failed to store session custom games in Firestore: {store_err}"
                )

        return {
            "status": "success",
            "message": (
                f"Custom game metrics collected for {len(req.custom_games)} game(s)."
                if req.custom_games
                else "No custom games provided — returned current cache."
            ),
            "logs": logs,
            "games": games,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/compare")
def api_compare_cached(
    request: Request,
    custom_games: list[str] = Query(None),
    category: str = Query("overall"),
    client_key: str | None = Depends(get_client_key),
):
    """Returns cached comparison reports (deprecated/disabled)."""
    report_msg = (
        "<div style='padding: 2rem; text-align: center; color: #64748b; "
        "font-family: sans-serif; background: rgba(30, 41, 59, 0.4); "
        "border-radius: 12px; border: 1px dashed rgba(255,255,255,0.1);'>"
        "Comparative reports are no longer generated to optimize API quota "
        "and latency. Strategic advice is now accessed directly via "
        "playbooks and news.</div>"
    )
    return {
        "report": report_msg,
        "cached": True,
    }


@router.post("/api/compare")
async def api_compare(
    request: Request,
    background_tasks: BackgroundTasks,
    req: CompareRequest = CompareRequest(),
    client_key: str | None = Depends(get_client_key),
    x_gemini_search_model: str = Header(None),
    x_gemini_analysis_model: str = Header(None),
):
    """Triggers regeneration of comparison reports (deprecated/disabled)."""
    report_msg = (
        "<div style='padding: 2rem; text-align: center; color: #64748b; "
        "font-family: sans-serif; background: rgba(30, 41, 59, 0.4); "
        "border-radius: 12px; border: 1px dashed rgba(255,255,255,0.1);'>"
        "Comparative reports are no longer generated to optimize API quota "
        "and latency. Strategic advice is now accessed directly via "
        "playbooks and news.</div>"
    )
    return {
        "report": report_msg,
        "cached": True,
    }


@router.get("/api/cache/status")
def api_cache_status():
    try:
        from ag_kaggle_5day.agents.advisor import get_hourly_cache

        store = get_hourly_cache()
        return {
            "age_seconds": store.age_seconds if store else 0,
            "report_cached": store.report_cached if store else False,
            "top5_count": len(store.top5) if store else 0,
            "combined_count": len(store.combined_games) if store else 0,
            "data_quality": store.data_quality if store else "no_live_data",
            "analysis_model": store.analysis_model if store else "",
            "refreshed_at": store.refreshed_at if store else 0.0,
            "expose_status": store.expose_status if store else "idle",
            "expose_error": store.expose_error if store else "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
