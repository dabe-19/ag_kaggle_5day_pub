import logging
import os
import random

from fastapi import APIRouter, Depends, Header, HTTPException

from ag_kaggle_5day.security import (
    check_rate_limit,
    get_client_key,
    get_effective_key,
    news_limiter,
)

logger = logging.getLogger("streamer_advisor.routes.news")
router = APIRouter()


@router.get("/api/news", dependencies=[Depends(check_rate_limit(news_limiter))])
def api_news(
    game: str,
    refresh: bool = False,
    client_key: str | None = Depends(get_client_key),
    x_gemini_search_model: str = Header(None),
):
    try:
        from ag_kaggle_5day.agents.advisor import get_game_news

        key = get_effective_key(client_key)
        news = get_game_news(
            game, api_key=key, model=x_gemini_search_model, refresh=refresh
        )
        return {"news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/news/random")
def api_news_random(limit: int = 5):
    articles = []

    # 1. Try Firestore
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        client = get_firestore_client()
        if client:
            docs = (
                client.collection("news_articles")
                .order_by("timestamp", direction="DESCENDING")
                .limit(50)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict()
                articles.append(
                    {
                        "title": data.get("headline") or "Streaming Update",
                        "author": data.get("author") or "",
                        "summary": data.get("summary") or "No summary available.",
                        "url": data.get("url") or "#",
                        "game": data.get("game") or "",
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to fetch news from Firestore: {e}")

    # 2. Fallback to local news_cache.md
    if not articles:
        try:
            from ag_kaggle_5day.agents.advisor import (
                NEWS_CACHE_FILE,
                parse_news_markdown,
            )

            if os.path.exists(NEWS_CACHE_FILE):
                news_data = parse_news_markdown(NEWS_CACHE_FILE)
                for game_name, info in news_data.items():
                    for art in info.get("articles", []):
                        articles.append(
                            {
                                "title": art.get("title") or "Streaming Update",
                                "author": art.get("author") or "",
                                "summary": art.get("summary")
                                or "No summary available.",
                                "url": art.get("url") or "#",
                                "game": game_name.capitalize(),
                            }
                        )
        except Exception as e:
            logger.warning(f"Failed to fetch news from local cache: {e}")

    # 3. Fallback to hardcoded defaults if everything else fails
    if not articles:
        articles = [
            {
                "title": "Twitch Updates Community Guidelines on Branded Content",
                "author": "Staff Writer",
                "summary": (
                    "Twitch has updated its rules regarding on-stream overlays, "
                    "sponsorships, and sponsor logos to provide clearer "
                    "boundaries for creators."
                ),
                "url": "https://blog.twitch.tv",
                "game": "IRL",
            },
            {
                "title": "Elden Ring Patch Notes Introduce Balance Adjustments",
                "author": "FromSoftware Team",
                "summary": (
                    "The latest patch brings weapon adjustments, bug fixes, "
                    "and stability improvements across all platforms."
                ),
                "url": "https://bandainamcoent.com",
                "game": "Elden Ring",
            },
            {
                "title": "VALORANT Champions Tour Sets New Viewership Records",
                "author": "Esports Insider",
                "summary": (
                    "VCT tournament viewership surged past 1.5 million concurrent "
                    "viewers across Twitch and YouTube co-streams."
                ),
                "url": "https://playvalorant.com",
                "game": "VALORANT",
            },
        ]

    random.shuffle(articles)
    return {"articles": articles[:limit]}
