from __future__ import annotations

import logging
import os
import sys
import time

from filelock import FileLock

logger = logging.getLogger("streamer_advisor.advisor")

_PACKAGE_DIR = os.path.dirname(os.path.dirname(__file__))
NEWS_CACHE_FILE = os.path.join(_PACKAGE_DIR, "news_cache.md")
_NEWS_CACHE_LOCK_FILE = NEWS_CACHE_FILE + ".lock"


def parse_news_markdown(filepath: str) -> dict[str, dict]:
    if not os.path.exists(filepath):
        # Try loading from Firestore system_cache to recover on cold start in Cloud Run
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

            data = get_app_cache_state("news_cache_data")
            if data:
                logger.info("Restored news cache from Firestore system_cache.")
                # Save locally so we don't have to keep querying Firestore
                write_news_markdown(filepath, data, sync_to_firestore=False)
                return data
        except Exception as e:
            logger.warning(f"Failed to restore news cache from Firestore: {e}")
        return {}

    import re

    news_data = {}
    current_game = None

    try:
        lock = FileLock(_NEWS_CACHE_LOCK_FILE, timeout=5)
        with lock:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Check for game heading: e.g. ## Minecraft
                if line.startswith("## "):
                    current_game = line[3:].strip().lower()
                    news_data[current_game] = {"articles": [], "fetched_at": 0.0}
                # Check for timestamp: e.g. *Fetched at: 1774829100.5*
                elif line.startswith("*Fetched at:") and current_game:
                    match = re.match(r"^\*Fetched at:\s*([0-9.]+)\*$", line)
                    if match:
                        news_data[current_game]["fetched_at"] = float(match.group(1))
                # Check for article item: e.g. - **[Title](Url)**: Summary
                elif line.startswith("- **[") and current_game:
                    match = re.match(r"^-\s*\*\*\[(.*?)\]\((.*?)\)\*\*:\s*(.*)$", line)
                    if match:
                        title, url, summary = match.groups()
                        news_data[current_game]["articles"].append(
                            {
                                "title": title.strip(),
                                "url": url.strip(),
                                "summary": summary.strip(),
                            }
                        )
    except Exception as e:
        logger.warning(f"Failed to parse news cache markdown: {e}")

    return news_data


def write_news_markdown(
    filepath: str,
    news_data: dict[str, dict],
    sync_to_firestore: bool = True,
) -> None:
    try:
        lock = FileLock(_NEWS_CACHE_LOCK_FILE, timeout=5)
        with lock:
            lines = ["# News Cache\n"]
            for game, info in sorted(news_data.items()):
                lines.append(f"\n## {game.title()}")
                fetched_at = info.get("fetched_at", time.time())
                lines.append(f"*Fetched at: {fetched_at}*")
                for art in info.get("articles", []):
                    title = art.get("title", "").replace("\n", " ")
                    url = art.get("url", "").replace("\n", " ")
                    summary = art.get("summary", "").replace("\n", " ")
                    lines.append(f"- **[{title}]({url})**: {summary}")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

        if sync_to_firestore:
            try:
                from ag_kaggle_5day.agents.gcp_storage import store_app_cache_state

                store_app_cache_state("news_cache_data", news_data)
                logger.info("Synced news cache to Firestore system_cache.")
            except Exception as e:
                logger.warning(f"Failed to sync news cache to Firestore: {e}")
    except Exception as e:
        logger.warning(f"Failed to write news cache markdown: {e}")


def prefetch_news_for_games_sync(
    games: list[dict], api_key: str = None, model: str = None
) -> None:
    """
    Synchronously fetches news articles for a list of games in parallel,
    waiting for all to complete.
    Bypasses live queries for games that are already cached and fresh
    (less than 12 hours old).
    Throttles to maximum 8 games refreshed per call (oldest first).
    """
    from ag_kaggle_5day.agents.advisor import NEWS_CACHE_FILE, get_game_news

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    logger.info(f"Starting synchronous news pre-fetch for {len(games)} game(s)...")
    cache = parse_news_markdown(NEWS_CACHE_FILE)

    candidates = []
    for g in games:
        title = g.get("title")
        if not title:
            continue
        title_key = title.strip().lower()
        if title_key not in cache or len(cache[title_key].get("articles", [])) == 0:
            candidates.append((0.0, title))
        else:
            # Check cache freshness (12 hours threshold = 43200 seconds)
            fetched_at = cache[title_key].get("fetched_at", 0.0)
            age = time.time() - fetched_at
            if age >= 43200:
                candidates.append((fetched_at, title))
            else:
                logger.info(
                    f"Re-using fresh cached news for '{title}' "
                    f"(age={age:.1f}s < 43200s)."
                )

    if not candidates:
        logger.info(
            "All games are already cached and fresh. Skipping "
            "synchronous news pre-fetch."
        )
        return

    # Sort by fetched_at ascending (oldest first, completely uncached 0.0 at the front)
    candidates.sort(key=lambda x: x[0])

    # Limit to 8 oldest games
    to_refresh = candidates[:8]
    skipped = candidates[8:]
    uncached_games = [title for _, title in to_refresh]

    if skipped:
        logger.info(
            f"News throttling: {len(candidates)} games need a refresh. "
            f"Only the 8 oldest games will be refreshed: {uncached_games}. "
            f"Skipped {len(skipped)} game(s)."
        )
        for fetched_at, title in skipped:
            age = time.time() - fetched_at if fetched_at > 0 else float("inf")
            logger.info(
                f"Skipping news refresh for '{title}' due to throttling "
                f"limit (age={age:.1f}s)."
            )

    if not uncached_games:
        return

    logger.info(
        f"Fetching news concurrently (sync wait) for {len(uncached_games)} "
        f"uncached/stale game(s): {uncached_games}"
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    pool_start = time.time()

    def fetch_news_worker(game_title: str, idx: int):
        # Spacing delay to respect LLM rate limits relative to pool start
        elapsed = time.time() - pool_start
        target_delay = idx * 2.0
        if elapsed < target_delay:
            time.sleep(target_delay - elapsed)
        logger.info(
            f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
            f"Scraping news for '{game_title}'..."
        )
        try:
            get_game_news(game_title, api_key=api_key, model=model, refresh=True)
            logger.info(
                f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
                f"Completed news for '{game_title}'"
            )
        except Exception as e:
            logger.warning(
                f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
                f"Failed news for '{game_title}': {e}"
            )

    max_workers = min(len(uncached_games), 2)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_news_worker, title, i)
            for i, title in enumerate(uncached_games)
        ]
        # Wait for all to complete
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.warning(f"Error in sync news pre-fetch worker: {e}")


def prefetch_news_for_games(
    games: list[dict], api_key: str = None, model: str = None
) -> None:
    """
    Pre-fetches news articles for a list of games in parallel, with spacing
    to respect rate limits.
    Bypasses live queries for games that are already cached and fresh
    (less than 12 hours old).
    Throttles to maximum 8 games refreshed per call (oldest first).
    """
    from ag_kaggle_5day.agents.advisor import NEWS_CACHE_FILE, get_game_news

    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        logger.info("Test environment detected. Skipping background news pre-fetch.")
        return

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    logger.info(f"Starting news pre-fetch for {len(games)} game(s)...")
    cache = parse_news_markdown(NEWS_CACHE_FILE)

    candidates = []
    for g in games:
        title = g.get("title")
        if not title:
            continue
        title_key = title.strip().lower()
        if title_key not in cache or len(cache[title_key].get("articles", [])) == 0:
            candidates.append((0.0, title))
        else:
            # Check cache freshness (12 hours threshold = 43200 seconds)
            fetched_at = cache[title_key].get("fetched_at", 0.0)
            age = time.time() - fetched_at
            if age >= 43200:
                candidates.append((fetched_at, title))
            else:
                logger.info(
                    f"Re-using fresh cached news for '{title}' "
                    f"(age={age:.1f}s < 43200s)."
                )

    if not candidates:
        logger.info("All games are already cached and fresh. Skipping news pre-fetch.")
        return

    # Sort by fetched_at ascending (oldest first, completely uncached 0.0 at the front)
    candidates.sort(key=lambda x: x[0])

    # Limit to 8 oldest games
    to_refresh = candidates[:8]
    skipped = candidates[8:]
    uncached_games = [title for _, title in to_refresh]

    if skipped:
        logger.info(
            f"News throttling: {len(candidates)} games need a refresh. "
            f"Only the 8 oldest games will be refreshed: {uncached_games}. "
            f"Skipped {len(skipped)} game(s)."
        )
        for fetched_at, title in skipped:
            age = time.time() - fetched_at if fetched_at > 0 else float("inf")
            logger.info(
                f"Skipping news refresh for '{title}' due to throttling "
                f"limit (age={age:.1f}s)."
            )

    if not uncached_games:
        return

    logger.info(
        f"Fetching news concurrently for {len(uncached_games)} "
        f"uncached/stale game(s): {uncached_games}"
    )

    from concurrent.futures import ThreadPoolExecutor

    def _run_news_pool():
        """Runs the ThreadPoolExecutor in a background thread so the caller
        returns immediately.

        Starts with a 5-second delay to yield API quota to the report generation
        call, then processes news with max 2 concurrent workers to avoid rate-limit
        starvation of other LLM consumers.
        """
        time.sleep(5)  # Let report generation get first crack at the API

        pool_start = time.time()

        def fetch_news_worker(game_title: str, idx: int):
            # Spacing delay to respect rate limits relative to pool start
            elapsed = time.time() - pool_start
            target_delay = idx * 2.0
            if elapsed < target_delay:
                time.sleep(target_delay - elapsed)
            logger.info(
                f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
                f"(Background) Scraping news for '{game_title}'..."
            )
            try:
                get_game_news(game_title, api_key=api_key, model=model, refresh=True)
                logger.info(
                    logger.info(
                        f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
                        f"(Background) Completed news for '{game_title}'"
                    )
                )
            except Exception as e:
                logger.warning(
                    f"[News Prefetch] [{idx + 1}/{len(uncached_games)}] "
                    f"(Background) Failed news for '{game_title}': {e}"
                )

        max_workers = min(len(uncached_games), 2)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i, title in enumerate(uncached_games):
                executor.submit(fetch_news_worker, title, i)
        logger.info("Background news pre-fetch pool completed.")

    try:
        import asyncio

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _run_news_pool)
    except RuntimeError:
        _run_news_pool()


def get_game_news(
    game: str, api_key: str = None, model: str = None, refresh: bool = False
) -> list[dict]:
    """Retrieves the 3 most relevant news articles for a given game.
    Checks the local markdown cache news_cache.md first.
    If refresh is True or not cached, performs a live Gemini Search Grounding query.
    """
    from ag_kaggle_5day.agents.advisor import (
        NEWS_CACHE_FILE,
        _GeminiError,
        parse_json_response,
        safe_generate_content,
    )

    game_key = game.strip().lower()

    # Check cache first if not forcing refresh
    if not refresh:
        cache = parse_news_markdown(NEWS_CACHE_FILE)
        if game_key in cache and len(cache[game_key].get("articles", [])) > 0:
            logger.info(f"Serving cached news articles for '{game}'")
            return cache[game_key]["articles"]

        # Not cached! Kick off background pre-fetch thread so it is cached next time
        logger.info(f"News not cached for '{game}'. Starting background pre-fetch.")
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, get_game_news, game, api_key, model, True)
        except RuntimeError:
            get_game_news(game, api_key, model, True)

        # Return immediate placeholders
        return [
            {
                "title": f"News pre-fetching in background for {game}...",
                "summary": (
                    "We are retrieving the latest news articles right now. "
                    "Close and reopen this modal in a few seconds, or click "
                    "'Perform Fresh Search' to force a live reload."
                ),
                "url": "#",
            }
        ]

    # Perform live search
    logger.info(f"Fetching news articles for: '{game}' (refresh={refresh})")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        logger.warning(
            f"No API key provided for news search. Using mock fallback for '{game}'."
        )
        return [
            {
                "title": f"New update released for {game}",
                "summary": (
                    "Developers announced a patch addressing stability, "
                    "performance, and balancing changes based on "
                    "community feedback."
                ),
                "url": "https://news.google.com",
            },
            {
                "title": f"Why {game} is trending in streaming lists",
                "summary": (
                    "Streamers are noting a resurgence of interest due to "
                    "active community hubs and engaging viewer interactions."
                ),
                "url": "https://news.google.com",
            },
        ]

    try:
        prompt = (
            f"Search for recent news, esports announcements, or release "
            f"updates for the video game '{game}'. "
            "Return a JSON array of 3 objects representing the most "
            "relevant articles. Each object MUST have the following keys: "
            "'title' (string, the headline), "
            "'summary' (string, a concise 1-2 sentence description of the news), "
            "'url' (string, the exact reference link URL)."
            "Do not return markdown format like ```json, only the raw "
            "JSON array string."
        )
        logger.info(f"Sending search news request to Gemini for '{game}'...")
        start_time = time.time()
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            use_google_search=True,
            timeout=60.0,
        )
        latency = round((time.time() - start_time) * 1000.0, 2)
        logger.info(
            f"Received news for '{game}' in {latency}ms",
            extra={"event_type": "gemini_call", "latency_ms": latency},
        )
        articles = parse_json_response(response.text)

        if isinstance(articles, list) and len(articles) > 0:
            cache = parse_news_markdown(NEWS_CACHE_FILE)
            cache[game_key] = {"articles": articles, "fetched_at": time.time()}
            write_news_markdown(NEWS_CACHE_FILE, cache)

            # Store news in Firestore vector store
            from ag_kaggle_5day.agents.gcp_storage import (
                get_embeddings_batch,
                store_news_vector,
            )

            # Generate batch embeddings for all articles in a single API call
            article_texts = [
                f"Game: {game}. Headline: {art.get('title', '')}. "
                f"Summary: {art.get('summary', '')}"
                for art in articles
            ]
            try:
                embeddings = get_embeddings_batch(article_texts, api_key)
            except Exception as emb_err:
                logger.warning(
                    f"Failed to pre-compute batch embeddings for '{game}': {emb_err}"
                )
                embeddings = []

            for idx, article in enumerate(articles):
                try:
                    emb = embeddings[idx] if idx < len(embeddings) else None
                    store_news_vector(
                        game=game,
                        headline=article.get("title", ""),
                        summary=article.get("summary", ""),
                        url=article.get("url", ""),
                        api_key=api_key,
                        embedding=emb,
                    )
                except Exception as store_err:
                    logger.error(
                        "Failed to store news article vector in "
                        f"Firestore for '{game}': {store_err}"
                    )

            return articles

    except _GeminiError as e:
        if e.code == 429:
            logger.warning(
                f"Gemini API 429 rate limit exceeded during news fetch "
                f"for '{game}': {e}. Using cache or fallback."
            )
        else:
            logger.error(f"Failed to fetch live news for '{game}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to fetch live news for '{game}': {e}", exc_info=True)

    # If live fetch failed but we have a cached version, fallback to cache
    # instead of showing failure
    cache = parse_news_markdown(NEWS_CACHE_FILE)
    if game_key in cache and len(cache[game_key].get("articles", [])) > 0:
        logger.info(
            f"Fallback to cached news articles for '{game}' after fetch failed."
        )
        return cache[game_key]["articles"]

    return [
        {
            "title": "News Search failed",
            "summary": (
                "Could not connect to Gemini search grounding service "
                "to fetch real-time news updates."
            ),
            "url": "https://news.google.com",
        }
    ]
