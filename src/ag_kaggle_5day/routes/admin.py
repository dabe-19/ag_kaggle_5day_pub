import logging
import os

from fastapi import APIRouter, HTTPException, Request

from ag_kaggle_5day.security import decrypt_key

logger = logging.getLogger("streamer_advisor.routes.admin")
router = APIRouter()


def get_deployment_nonce() -> str:
    """Reads deployment nonce from env or parses service.yaml."""
    if "DEPLOY_NONCE" in os.environ:
        return os.environ["DEPLOY_NONCE"]

    import re

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        yaml_path = os.path.join(curr_dir, "service.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r") as f:
                    content = f.read()
                match = re.search(
                    r"client\.knative\.dev/nonce:\s*['\"]?([a-zA-Z0-9_-]+)['\"]?",
                    content,
                )
                if match:
                    return match.group(1)
            except Exception:
                pass
        curr_dir = os.path.dirname(curr_dir)

    return "local-dev"


@router.get("/api/config")
def api_get_config(request: Request):
    try:
        cookie_key = request.cookies.get("gemini_session_key")
        has_session_key = False
        if cookie_key:
            has_session_key = decrypt_key(cookie_key) is not None
        has_gemini = (
            bool(os.environ.get("GEMINI_API_KEY", "").strip()) or has_session_key
        )
        has_twitch = bool(
            os.environ.get("TWITCH_CLIENT_ID", "").strip()
            and os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
        )
        has_youtube = bool(os.environ.get("YOUTUBE_API_KEY", "").strip())

        from ag_kaggle_5day.agents.scraper import load_model_config

        config = load_model_config()

        affiliate_playbook = None
        if config.get("enable_affiliate_playbook", False):
            affiliate_products = config.get("affiliate_products", [])
            if affiliate_products:
                import datetime

                try:
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    now_local = now_utc.astimezone()
                    generated_at_iso = now_local.isoformat()
                    formatted_time = now_local.strftime("%I:%M %p %Z")
                except Exception:
                    generated_at_iso = ""
                    formatted_time = ""
                products_list = []
                for p in affiliate_products:
                    price_str = f" ({p['price']})" if p.get("price") else ""
                    name_link = f"**[{p['name']}]({p['link']})**"
                    products_list.append(f"- {name_link}{price_str}: {p['benefit']}")

                prep_str = (
                    "To supercharge your setup for high-quality production, "
                    "consider the following recommended gear and peripherals:\n\n"
                    + "\n".join(products_list)
                )

                affiliate_playbook = {
                    "game": "Stream Gear & Setup",
                    "category": "Setup Recommendations",
                    "score": 100,
                    "platform": "Universal (Improves Stream Quality & Engagement)",
                    "hook": (
                        "Level up your hardware and production value to "
                        "stand out from the competition."
                    ),
                    "advice": (
                        "Using professional hardware and peripherals not only "
                        "enhances your viewer's experience, but also streamlines "
                        "your workflow. Streamlining your OBS control, audio "
                        "mixing, and video clarity makes growing your channel "
                        "much more natural."
                    ),
                    "preparation": prep_str,
                    "news": [],
                    "stream_goal": "growth",
                    "generated_at": generated_at_iso,
                    "formatted_time": formatted_time,
                    "twitch_viewers": 0,
                    "youtube_viewers": 0,
                    "total_viewers": 0,
                    "is_affiliate": True,
                }

        return {
            "deployment_nonce": get_deployment_nonce(),
            "server_key_configured": has_gemini,
            "client_key_configured": has_session_key,
            "twitch_configured": has_twitch,
            "youtube_configured": has_youtube,
            "available_models": config.get(
                "available_models",
                [
                    {"id": "gemma-4-31b-it", "name": "Gemma 4 31B"},
                    {"id": "gemma-4-26b-a4b-it", "name": "Gemma 4 A4B-it"},
                    {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite"},
                    {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash"},
                    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
                ],
            ),
            "enable_affiliate_playbook": config.get("enable_affiliate_playbook", False),
            "affiliate_playbook": affiliate_playbook,
        }
    except Exception as e:
        logger.error(f"Error in api_get_config: {e}")
        raise HTTPException(status_code=500, detail=str(e))
