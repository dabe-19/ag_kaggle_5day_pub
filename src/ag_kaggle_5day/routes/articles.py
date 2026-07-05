import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from ag_kaggle_5day.models import MediumFormRequest
from ag_kaggle_5day.security import (
    check_rate_limit,
    get_client_key,
    news_limiter,
)

logger = logging.getLogger("streamer_advisor.routes.articles")
router = APIRouter()


def post_process_article(article: dict) -> dict:
    if not article or "content" not in article:
        return article

    content = article["content"]
    if not content or not isinstance(content, str):
        return article

    try:
        from bs4 import BeautifulSoup

        from ag_kaggle_5day.agents.gcp_storage import (
            get_firestore_client,
            resolve_streamer_link,
        )

        soup = BeautifulSoup(content, "html.parser")
        fs = get_firestore_client()
        modified = False

        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "/spotlight" in href or "/expose" in href or "handle=" in href:
                handle = None
                if "handle=" in href:
                    from urllib.parse import parse_qs, urlparse

                    parsed = urlparse(href)
                    params = parse_qs(parsed.query)
                    if "handle" in params:
                        handle = params["handle"][0]
                else:
                    parts = href.split("/")
                    parts = [p for p in parts if p]
                    if parts:
                        handle = parts[-1]

                if handle:
                    # 1. Resolve friendly name if text contains a raw UC channel ID
                    text = a.get_text().strip()
                    clean_text = text.lstrip("@").strip()
                    if clean_text.lower().startswith("uc") and len(clean_text) == 24:
                        friendly = text
                        try:
                            # Try resolving display name
                            link_info = resolve_streamer_link(clean_text, fs)
                            if link_info and link_info.get("display_name"):
                                friendly = link_info["display_name"]
                                if text.startswith("@") and not friendly.startswith(
                                    "@"
                                ):
                                    friendly = "@" + friendly
                            else:
                                p_doc = (
                                    fs.collection("streamer_profiles")
                                    .document(clean_text.lower())
                                    .get()
                                )
                                if p_doc.exists:
                                    p_data = p_doc.to_dict()
                                    friendly = (
                                        p_data.get("youtube_title")
                                        or p_data.get("twitch_display_name")
                                        or friendly
                                    )
                        except Exception:
                            pass

                        if friendly != text:
                            a.string = friendly
                            modified = True

                    # 2. Determine platform and inject class for CSS styling
                    is_youtube = False
                    if handle.lower().startswith("uc"):
                        is_youtube = True
                    else:
                        try:
                            p_doc = (
                                fs.collection("streamer_profiles")
                                .document(handle.lower())
                                .get()
                            )
                            if (
                                p_doc.exists
                                and p_doc.to_dict().get("platform") == "youtube"
                            ):
                                is_youtube = True
                            else:
                                link_info = resolve_streamer_link(handle, fs)
                                if link_info and link_info.get("platform") == "youtube":
                                    is_youtube = True
                        except Exception:
                            pass

                    if is_youtube:
                        classes = a.get("class", [])
                        if isinstance(classes, str):
                            classes = [classes]
                        if "youtube-link" not in classes:
                            classes.append("youtube-link")
                            a["class"] = classes
                            modified = True

        if modified:
            article["content"] = str(soup)
    except Exception as e:
        logger.warning(f"Error post-processing article content: {e}")

    return article


@router.post(
    "/api/articles/medium-form",
    dependencies=[Depends(check_rate_limit(news_limiter))],
)
async def api_generate_medium_form(
    req: MediumFormRequest, client_key: str | None = Depends(get_client_key)
):
    """Generates or retrieves a medium-form article spotlighting a streamer."""
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_cached_medium_form_article

        cached = get_cached_medium_form_article(req.streamer_handle)
        if cached:
            return post_process_article(cached)
    except Exception:
        pass

    if not client_key or not client_key.strip():
        raise HTTPException(
            status_code=400,
            detail="Personal Gemini API Key is required to analyze streamer handles.",
        )

    personal_key = client_key.strip().strip('"').strip("'")

    logger.log(
        25,
        "[EXPOSE] Incoming API request to generate medium-form expose "
        f"for '{req.streamer_handle}'",
    )

    try:
        from ag_kaggle_5day.agents.advisor import (
            get_or_generate_medium_form_article,
        )

        article = await get_or_generate_medium_form_article(
            streamer_handle=req.streamer_handle,
            api_key=personal_key,
            model=req.model,
        )
        return post_process_article(article)
    except (ImportError, AttributeError):
        return post_process_article(
            {
                "streamer_handle": req.streamer_handle,
                "title": f"Spotlight: {req.streamer_handle}",
                "content": (
                    f"<p>This is a placeholder medium-form article for "
                    f"<strong>{req.streamer_handle}</strong>. "
                    "The advisor agent is currently offline.</p>"
                ),
                "timestamp": time.time(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/articles/expose/status")
def api_get_expose_status():
    """Returns the current background expose generation status."""
    from ag_kaggle_5day.agents.advisor import _store

    return {
        "status": _store.expose_status,
        "error": _store.expose_error,
    }


@router.get("/api/articles/expose/latest")
async def api_get_latest_expose():
    """Fetches the latest daily expose article from Firestore."""
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_latest_expose_article

        article = get_latest_expose_article()
        if not article:
            raise HTTPException(status_code=404, detail="No daily exposes found.")
        return post_process_article(article)
    except (ImportError, AttributeError):
        return post_process_article(
            {
                "streamer_handle": "ninja",
                "title": "Streamer of the Day: Ninja",
                "content": (
                    "<p>This is a placeholder daily expose for "
                    "<strong>Ninja</strong>.</p>"
                ),
                "timestamp": time.time(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/articles/expose/history")
async def api_get_expose_history():
    """Retrieves a history of the daily expose articles from Firestore."""
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_expose_history

        history = get_expose_history()
        return [post_process_article(a) for a in history]
    except (ImportError, AttributeError):
        return []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
