import json
import logging
import os
import time
import urllib.parse
from typing import Optional

from filelock import FileLock

from ag_kaggle_5day.agents.scraper.games import (
    SPONSORED_GAMES,
    STAPLE_GAMES,
    _build_canonical_game,
    _calculate_score,
    _estimate_avg_length,
    _infer_category,
)
from ag_kaggle_5day.agents.scraper.gemini import (
    parse_json_response,
    safe_generate_content,
)
from ag_kaggle_5day.agents.scraper.twitch import TwitchAPIClient
from ag_kaggle_5day.agents.scraper.youtube import YouTubeAPIClient

logger = logging.getLogger("streamer_advisor.scraper")

_last_known_yt_cache: Optional[dict[str, dict]] = None


def _get_cached_youtube_viewers(
    game_name: str, max_age_seconds: int = 43200
) -> Optional[dict]:
    """
    Reads cache.json and returns a dict with 'youtube_viewers' and 'youtube_fetched_at'
    if the cached entry has a valid timestamp and is within the age limit.
    """
    from ag_kaggle_5day.agents.scraper import _CACHE_LOCK_FILE, CACHE_FILE

    if not os.path.exists(CACHE_FILE):
        return None
    try:
        lock = FileLock(_CACHE_LOCK_FILE, timeout=5)
        with lock:
            with open(CACHE_FILE, "r") as f:
                games = json.load(f)
            for g in games:
                if g.get("title", "").strip().lower() == game_name.strip().lower():
                    if "youtube_viewers" in g:
                        fetched_at = g.get("youtube_fetched_at")
                        if fetched_at is not None:
                            if time.time() - float(fetched_at) > max_age_seconds:
                                return None
                            return {
                                "youtube_viewers": int(g["youtube_viewers"]),
                                "youtube_fetched_at": float(fetched_at),
                                "top_streamers": [
                                    s
                                    for s in g.get("top_streamers", [])
                                    if s.get("platform") == "youtube"
                                ],
                            }
    except Exception:
        pass
    return None


def _get_last_known_good_youtube_viewers(game_name: str) -> Optional[dict]:
    """
    Looks up the last known good YouTube concurrent viewer count for a game.
    First tries to retrieve it from local cache.json (without age restriction).
    If not found or has 0/None YouTube viewers, falls back to querying the
    BigQuery streamer_metrics.hourly_stats table for the most recent entry
    where youtube_viewers > 0.
    """
    # 1. Try cache.json first (no max age limit)
    from ag_kaggle_5day.agents.scraper import _get_cached_youtube_viewers

    cached = _get_cached_youtube_viewers(game_name, max_age_seconds=999999999)
    if cached and cached.get("youtube_viewers", 0) > 0:
        return cached

    # 1.5. Try in-memory store.combined_games next (to avoid BQ queries on startup)
    try:
        from ag_kaggle_5day.agents.advisor import _store

        if _store.combined_games:
            for g in _store.combined_games:
                if g.get("title", "").strip().lower() == game_name.strip().lower():
                    yt_v = g.get("youtube_viewers", 0)
                    yt_fetched = g.get("youtube_fetched_at")
                    if yt_v > 0 and yt_fetched is not None:
                        return {
                            "youtube_viewers": int(yt_v),
                            "youtube_fetched_at": float(yt_fetched),
                            "top_streamers": [
                                s
                                for s in g.get("top_streamers", [])
                                if s.get("platform") == "youtube"
                            ],
                        }
    except Exception:
        pass

    # 2. Try BigQuery batch cache first, populating it if None
    import ag_kaggle_5day.agents.scraper as scraper

    if scraper._last_known_yt_cache is None:
        scraper._last_known_yt_cache = {}
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

            client = get_bigquery_client()
            if client:
                dataset_id = f"{client.project}.streamer_metrics"
                table_id = f"{dataset_id}.hourly_stats"
                query = f"""
                    SELECT title_lower, youtube_viewers,
                           timestamp, top_streamers
                    FROM (
                      SELECT LOWER(title) as title_lower, youtube_viewers,
                             timestamp, top_streamers,
                             ROW_NUMBER() OVER(
                               PARTITION BY LOWER(title)
                               ORDER BY timestamp DESC
                             ) as rn
                      FROM `{table_id}`
                      WHERE youtube_viewers > 0
                    )
                    WHERE rn = 1
                """
                query_job = client.query(query, timeout=15)
                rows = list(query_job.result())
                for row in rows:
                    import datetime

                    ts = row.timestamp
                    if isinstance(ts, datetime.datetime):
                        fetched_at = ts.timestamp()
                    else:
                        fetched_at = datetime.datetime.fromisoformat(
                            str(ts).replace("Z", "+00:00")
                        ).timestamp()

                    top_streamers_bq = []
                    if hasattr(row, "top_streamers") and row.top_streamers:
                        try:
                            all_s = json.loads(row.top_streamers)
                            top_streamers_bq = [
                                s
                                for s in all_s
                                if isinstance(s, dict)
                                and s.get("platform") == "youtube"
                            ]
                        except Exception:
                            pass

                    scraper._last_known_yt_cache[row.title_lower.strip()] = {
                        "youtube_viewers": int(row.youtube_viewers),
                        "youtube_fetched_at": fetched_at,
                        "top_streamers": top_streamers_bq,
                    }
                logger.info(
                    "Successfully pre-populated YouTube fallback cache with "
                    f"{len(scraper._last_known_yt_cache)} entries from BigQuery."
                )
        except Exception as bq_err:
            logger.warning(
                f"Failed to pre-populate YouTube fallback cache from BigQuery: {bq_err}"
            )

    # Look up in the batch cache
    key = game_name.lower().strip()
    if scraper._last_known_yt_cache and key in scraper._last_known_yt_cache:
        return scraper._last_known_yt_cache[key]

    return None


# ---------------------------------------------------------------------------
# Public API — discover_top_games
# ---------------------------------------------------------------------------


def discover_top_games(
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    model: Optional[str] = None,
    category: str = "overall",
    limit: int = 10,
) -> list[dict]:
    """
    Discovers the top `limit` currently trending streaming game categories
    under the specified Twitch category directory.

    Resolution order:
      1. Twitch Helix API (get_top_games_by_category ->
         get_viewers_for_game per title + get_top_streamers)
         + YouTube Data API v3 (get_viewers_for_game per title)
         -> data_quality: "live"
      2. Gemini + Google Search grounding (requires api_key)
         -> data_quality: "estimated"
      3. First `limit` SPONSORED_GAMES constants (no randomisation)
         -> data_quality: "no_live_data"

    Returns up to `limit` game dicts tagged tier="trending".
    """
    from ag_kaggle_5day.agents.scraper import _get_last_known_good_youtube_viewers

    logger.info(f"Discovering top {limit} trending games for category '{category}'...")

    # --- Path 1: Twitch Helix API ---
    twitch = twitch_client or TwitchAPIClient()
    youtube = youtube_client or YouTubeAPIClient()

    if twitch.is_configured:
        try:
            top_games = twitch.get_top_games_by_category(category, limit=limit)
            logger.info(
                f"Twitch top games for '{category}': "
                f"{[g.get('name') for g in top_games]}"
            )
            if top_games:
                # Pre-populate BigQuery cache on the main thread to avoid concurrent BQ
                # queries and deadlocks
                global _last_known_yt_cache
                if _last_known_yt_cache is None:
                    _last_known_yt_cache = {}
                    try:
                        from ag_kaggle_5day.agents.gcp_storage import (
                            get_bigquery_client,
                        )

                        client = get_bigquery_client()
                        if client:
                            dataset_id = f"{client.project}.streamer_metrics"
                            table_id = f"{dataset_id}.hourly_stats"
                            query = f"""
                                SELECT title_lower, youtube_viewers,
                                       timestamp, top_streamers
                                FROM (
                                  SELECT LOWER(title) as title_lower, youtube_viewers,
                                         timestamp, top_streamers,
                                         ROW_NUMBER() OVER(
                                           PARTITION BY LOWER(title)
                                           ORDER BY timestamp DESC
                                         ) as rn
                                  FROM `{table_id}`
                                  WHERE youtube_viewers > 0
                                )
                                WHERE rn = 1
                            """
                            logger.info(
                                "Pre-populating YouTube BigQuery cache on main thread..."  # noqa: E501
                            )
                            query_job = client.query(query, timeout=15)
                            rows = list(query_job.result())
                            for row in rows:
                                import datetime

                                ts = row.timestamp
                                if isinstance(ts, datetime.datetime):
                                    ts_val = ts.timestamp()
                                else:
                                    ts_val = float(ts) if ts else time.time()

                                t_streamers = []
                                if hasattr(row, "top_streamers") and row.top_streamers:
                                    try:
                                        t_streamers = json.loads(row.top_streamers)
                                    except Exception:
                                        pass

                                _last_known_yt_cache[row.title_lower] = {
                                    "youtube_viewers": int(row.youtube_viewers),
                                    "youtube_fetched_at": ts_val,
                                    "top_streamers": [
                                        s
                                        for s in t_streamers
                                        if s.get("platform") == "youtube"
                                    ],
                                }
                            logger.info(
                                f"Successfully cached {len(_last_known_yt_cache)} games from BigQuery."  # noqa: E501
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to pre-populate BigQuery YouTube cache: {e}"
                        )

                from concurrent.futures import ThreadPoolExecutor

                def fetch_twitch_data(game: dict) -> dict:
                    """Fetch Twitch viewers and top 3 streamers concurrently."""
                    game_id = game.get("id")
                    game_name = game.get("name", "Unknown")
                    twitch_data = twitch.get_viewers_for_game(game_id, game_name)
                    top_streamers = twitch.get_top_streamers(game_id, limit=3)
                    return {
                        "game": game,
                        "twitch_viewers": twitch_data.get("twitch_viewers", 0),
                        "stream_count": twitch_data.get("stream_count", 0),
                        "top_streamers": top_streamers,
                    }

                # Step 1: Fetch Twitch viewers and streamers concurrently (limit to 15
                # workers to reduce contention)
                twitch_results = []
                max_workers = min(len(top_games), 15)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(fetch_twitch_data, g) for g in top_games]
                    for future in futures:
                        try:
                            # 15s timeout to prevent individual hangs from blocking the
                            # job
                            twitch_results.append(future.result(timeout=15.0))
                        except Exception as exec_err:
                            logger.warning(f"Parallel Twitch fetch failed: {exec_err}")

                # Step 2: Fetch YouTube viewers in parallel (max 3 workers to stagger
                # requests safely)
                def fetch_youtube_data(i: int, tr: dict) -> dict:
                    game = tr["game"]
                    game_name = game.get("name", "Unknown")
                    twitch_v = tr["twitch_viewers"]
                    top_streamers = tr["top_streamers"]

                    youtube_v = 0
                    youtube_source = "YouTube Data API v3"
                    youtube_fetched = None
                    yt_streamers = []
                    if youtube.api_key:
                        from ag_kaggle_5day.agents.scraper import (
                            _get_cached_youtube_viewers,
                        )

                        cached_yt = _get_cached_youtube_viewers(game_name)
                        if cached_yt is not None:
                            youtube_v = cached_yt["youtube_viewers"]
                            youtube_fetched = cached_yt["youtube_fetched_at"]
                            yt_streamers = cached_yt.get("top_streamers", [])
                            youtube_source = "YouTube Data API v3 (Cached)"
                            logger.info(
                                f"YouTube: Reusing cached viewers for "
                                f"'{game_name}': {youtube_v:,}"
                            )
                        else:
                            from ag_kaggle_5day.agents.scraper import (
                                _is_quota_exceeded_persistent,
                            )

                            quota_exceeded_before = (
                                YouTubeAPIClient._quota_exceeded
                                or _is_quota_exceeded_persistent()
                            )
                            yt_data = None
                            use_html_only = (i >= 10) or quota_exceeded_before

                            # Stagger starts based on thread modulo to
                            # avoid rate limit spikes
                            if i > 0:
                                time.sleep(0.5 + (i % 3) * 0.2)
                            try:
                                yt_data = youtube.get_viewers_for_game(
                                    game_name, html_only=use_html_only
                                )
                            except Exception as yt_err:
                                logger.warning(
                                    f"YouTube viewer fetch failed for "
                                    f"'{game_name}': {yt_err}"
                                )

                            if yt_data and isinstance(yt_data, dict):
                                youtube_v = yt_data.get("youtube_viewers", 0)
                                youtube_fetched = time.time()
                                if i >= 20:
                                    logger.info(
                                        "YouTube: Discarding live streamers list for "
                                        f"'{game_name}' beyond top-20 limit."
                                    )
                                    yt_streamers = []
                                else:
                                    yt_streamers = yt_data.get("top_streamers", [])
                            else:
                                fallback_yt = _get_last_known_good_youtube_viewers(
                                    game_name
                                )
                                if fallback_yt is not None:
                                    youtube_v = fallback_yt["youtube_viewers"]
                                    youtube_fetched = fallback_yt["youtube_fetched_at"]
                                    yt_streamers = fallback_yt.get("top_streamers", [])
                                    youtube_source = (
                                        "YouTube Data API v3 (Rate-Limited Fallback)"
                                    )

                    combined_streamers = list(top_streamers)
                    combined_streamers.extend(yt_streamers)
                    combined_streamers.sort(
                        key=lambda x: x.get("viewer_count", 0), reverse=True
                    )

                    sponsored = next(
                        (
                            g
                            for g in SPONSORED_GAMES
                            if g["title"].lower() == game_name.lower()
                        ),
                        None,
                    )
                    avg_length = _estimate_avg_length(
                        game_name, youtube.api_key, model=model
                    )

                    try:
                        twitch_v_val = int(twitch_v)
                    except (ValueError, TypeError):
                        twitch_v_val = 0

                    try:
                        youtube_v_val = int(youtube_v)
                    except (ValueError, TypeError):
                        youtube_v_val = 0

                    score = (
                        sponsored["score"]
                        if sponsored
                        else _calculate_score(twitch_v_val, youtube_v_val)
                    )

                    logger.info(
                        f"Trending [Helix]: {game_name} — Twitch {twitch_v_val:,} "
                        f"| YouTube {youtube_v_val:,}"
                    )
                    box_art = tr["game"].get("box_art_url")
                    return _build_canonical_game(
                        title=game_name,
                        category=_infer_category(
                            game_name, sponsored, box_art_url=box_art
                        ),
                        twitch_viewers=twitch_v_val,
                        youtube_viewers=youtube_v_val,
                        avg_length_hours=avg_length,
                        score=score,
                        source="Twitch Helix API"
                        + (f" + {youtube_source}" if youtube_v > 0 else ""),
                        source_url=(
                            f"https://www.twitch.tv/directory/game/"
                            f"{urllib.parse.quote(game_name)}"
                        ),
                        tier="trending",
                        data_quality="live",
                        youtube_fetched_at=youtube_fetched,
                        top_streamers=combined_streamers,
                        stream_count=tr.get("stream_count", 0),
                        cover_url=box_art,
                    )

                results = []
                with ThreadPoolExecutor(max_workers=3) as executor:
                    yt_futures = [
                        executor.submit(fetch_youtube_data, i, tr)
                        for i, tr in enumerate(twitch_results)
                    ]
                    for future in yt_futures:
                        try:
                            # 20s timeout per game to prevent hangs
                            results.append(future.result(timeout=20.0))
                        except Exception as exec_err:
                            logger.warning(f"Parallel YouTube fetch failed: {exec_err}")

                logger.info(f"Twitch Helix trending discovery: {len(results)} games.")
                return results
            else:
                logger.warning(
                    "Twitch Helix returned empty top-games list. "
                    "Falling back to Gemini."
                )
        except Exception as e:
            logger.warning(
                f"Twitch Helix trending discovery failed: {e}. Falling back to Gemini."
            )
    else:
        logger.info(
            "Twitch API not configured (TWITCH_CLIENT_ID/SECRET "
            "missing). Trying Gemini."
        )

    # --- Path 2: Gemini + Google Search grounding ---
    if api_key:
        try:
            prompt = (
                "Search Google and Twitch.tv data for the current "
                f"top {limit} most-watched streaming game categories "
                f"in the '{category}' directory on Twitch and YouTube "
                "right now (today). "
                f"Return ONLY a raw JSON array of exactly {limit} objects. "
                "Each object MUST have these keys:\n"
                "- 'title' (string, exact game/category name)\n"
                "- 'category' (string, e.g. FPS, MOBA, Battle Royale, RPG, etc.)\n"
                "- 'estimated_twitch_viewers' (int, current average "
                "concurrent Twitch viewers)\n"
                "- 'estimated_youtube_viewers' (int, current average "
                "concurrent YouTube viewers)\n"
                "- 'avg_length_hours' (float, average stream session "
                "length in hours)\n"
                f"- 'score' (int 0-100, streaming opportunity score "
                f"based on viewership and competition)\n"
                f"- 'source' (string, source name, e.g. TwitchTracker, SullyGnome)\n"
                f"- 'source_url' (string, a real verifiable URL for this data)\n"
                f"Do NOT include markdown code fences or any text "
                f"outside the JSON array."
            )
            logger.info(
                f"Querying Gemini for live top-{limit} trending games "
                f"under category '{category}' (Search Grounding fallback)..."
            )
            response = safe_generate_content(
                api_key=api_key,
                model=model,
                contents=prompt,
                use_google_search=True,
            )
            parsed = parse_json_response(response.text)
            if isinstance(parsed, list) and len(parsed) > 0:
                games = []
                for item in parsed[:limit]:
                    title = item.get("title", "Unknown")
                    twitch_v = int(item.get("estimated_twitch_viewers", 0))
                    youtube_v = int(item.get("estimated_youtube_viewers", 0))
                    score = int(item.get("score", 50))
                    games.append(
                        _build_canonical_game(
                            title=title,
                            category=item.get("category", "Unknown"),
                            twitch_viewers=twitch_v,
                            youtube_viewers=youtube_v,
                            avg_length_hours=float(item.get("avg_length_hours", 3.0)),
                            score=score,
                            source="Gemini Search Estimate",
                            source_url=item.get("source_url", ""),
                            tier="trending",
                            data_quality="estimated",
                            top_streamers=[],
                        )
                    )
                    logger.info(
                        f"Trending [Gemini estimate]: {title} — "
                        f"Twitch {twitch_v:,} | YouTube {youtube_v:,}"
                    )
                logger.info(f"Gemini returned {len(games)} trending games (estimated).")
                return games
            else:
                logger.warning(
                    "Gemini returned invalid or empty trending list. "
                    "Using SPONSORED_GAMES fallback."
                )
        except Exception as e:
            logger.warning(
                f"Gemini top-{limit} discovery failed: {e}. "
                "Using SPONSORED_GAMES fallback."
            )

    # --- Path 3: SPONSORED_GAMES baseline (no randomisation) ---
    logger.warning(
        "All live sources failed. Using SPONSORED_GAMES constants "
        "as no_live_data fallback."
    )
    results = []
    for g in SPONSORED_GAMES[:limit]:
        results.append(
            _build_canonical_game(
                title=g["title"],
                category=g["category"],
                twitch_viewers=g["avg_viewers"],  # use baseline directly, no noise
                youtube_viewers=0,
                avg_length_hours=g["avg_length_hours"],
                score=g["score"],
                source="Local Fallback (no live data)",
                source_url=(
                    f"https://www.twitch.tv/directory/game/"
                    f"{urllib.parse.quote(g['title'])}"
                ),
                tier="trending",
                data_quality="no_live_data",
                top_streamers=[],
            )
        )
    return results


def discover_top5_games(
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    model: Optional[str] = None,
) -> list[dict]:
    return discover_top_games(
        api_key=api_key,
        twitch_client=twitch_client,
        youtube_client=youtube_client,
        model=model,
        category="overall",
        limit=5,
    )


# ---------------------------------------------------------------------------
# Public API — scrape_viewership_for_games
# ---------------------------------------------------------------------------


def scrape_viewership_for_games(
    game_titles: list[str],
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    model: Optional[str] = None,
) -> list[dict]:
    """
    Fetches current viewership metrics for a specific list of game titles.

    Resolution order per title:
      1. Twitch Helix API (game_id lookup → viewers aggregation)
         + YouTube Data API v3 (live stream search → viewer sum)
         → data_quality: "live"
      2. Gemini Search Grounding for any titles not resolved by platform APIs
         → data_quality: "estimated"
      3. STAPLE_GAMES baseline (exact constants, no noise) for remaining gaps
         → data_quality: "no_live_data"

    The `custom` flag is NOT set here — callers set it.
    The `tier` defaults to "staple"; callers may override after the call.
    """
    logger.info(f"Fetching viewership for {len(game_titles)} game(s): {game_titles}")
    results: dict[str, dict] = {}  # keyed by lower-case title

    twitch = twitch_client or TwitchAPIClient()
    youtube = youtube_client or YouTubeAPIClient()

    # --- Path 1: Twitch Helix + YouTube (Twitch concurrent, YouTube sequential) ---
    if (twitch.is_configured or youtube.is_configured) and game_titles:
        from concurrent.futures import ThreadPoolExecutor

        from ag_kaggle_5day.agents.scraper import (
            _is_quota_exceeded_persistent,
            load_model_config,
        )

        def fetch_twitch_single(title: str) -> Optional[dict]:
            """Fetch Twitch data only (concurrent-safe, high RPM)."""
            stream_count = 0
            box_art_url = None
            if twitch.is_configured:
                try:
                    game_details = twitch.get_game_details(title)
                    if game_details:
                        game_id = game_details["id"]
                        box_art_url = game_details.get("box_art_url")
                        twitch_data = twitch.get_viewers_for_game(game_id, title)
                        twitch_v = twitch_data.get("twitch_viewers", 0)
                        stream_count = twitch_data.get("stream_count", 0)
                        twitch_ok = True
                        top_streamers = twitch.get_top_streamers(game_id, limit=3)
                    else:
                        logger.info(f"Twitch: no game_id found for '{title}'.")
                except Exception as e:
                    logger.warning(f"Twitch Helix viewership failed for '{title}': {e}")
            return {
                "title": title,
                "twitch_viewers": twitch_v,
                "twitch_ok": twitch_ok,
                "stream_count": stream_count,
                "top_streamers": top_streamers,
                "box_art_url": box_art_url,
            }

        # Step 1: Fetch Twitch viewers concurrently
        twitch_data_list = []
        max_workers = min(len(game_titles), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(fetch_twitch_single, title): title
                for title in game_titles
            }
            for future in futures:
                try:
                    res = future.result()
                    if res:
                        twitch_data_list.append(res)
                except Exception as exec_err:
                    title = futures[future]
                    logger.warning(
                        f"Parallel Twitch fetch failed for '{title}': {exec_err}"
                    )

        # Step 2: Fetch YouTube viewers sequentially (low RPM)
        yt_fetch_idx = 0
        for td in twitch_data_list:
            title = td["title"]
            twitch_v = td["twitch_viewers"]
            live_succeeded = td["twitch_ok"]
            sources_used = ["Twitch Helix API"] if td["twitch_ok"] else []

            youtube_v = 0
            youtube_fetched = None
            yt_streamers = []
            if youtube.api_key:
                cached_yt = _get_cached_youtube_viewers(title)
                if cached_yt is not None:
                    youtube_v = cached_yt["youtube_viewers"]
                    youtube_fetched = cached_yt["youtube_fetched_at"]
                    yt_streamers = cached_yt.get("top_streamers", [])
                    live_succeeded = True
                    sources_used.append("YouTube Data API v3 (Cached)")
                    logger.info(
                        f"YouTube: Reusing cached viewers for '{title}': {youtube_v:,}"
                    )
                else:
                    is_limited = (
                        YouTubeAPIClient._quota_exceeded
                        or _is_quota_exceeded_persistent()
                    )
                    yt_data = None
                    if not is_limited:
                        if yt_fetch_idx > 0:
                            time.sleep(0.5)
                        yt_fetch_idx += 1
                        try:
                            yt_data = youtube.get_viewers_for_game(title)
                        except Exception as yt_err:
                            logger.warning(
                                f"YouTube viewer fetch failed for '{title}': {yt_err}"
                            )

                    is_exceeded = (
                        YouTubeAPIClient._quota_exceeded
                        or _is_quota_exceeded_persistent()
                    )
                    if yt_data and not is_exceeded:
                        youtube_v = yt_data.get("youtube_viewers", 0)
                        youtube_fetched = time.time()
                        if yt_fetch_idx >= 20:
                            logger.info(
                                "YouTube: Discarding live streamers list for "
                                f"'{title}' beyond top-20 limit."
                            )
                            yt_streamers = []
                        else:
                            yt_streamers = yt_data.get("top_streamers", [])
                        live_succeeded = True
                        sources_used.append("YouTube Data API v3")
                    else:
                        fallback_yt = _get_last_known_good_youtube_viewers(title)
                        if fallback_yt is not None:
                            youtube_v = fallback_yt["youtube_viewers"]
                            youtube_fetched = fallback_yt["youtube_fetched_at"]
                            yt_streamers = fallback_yt.get("top_streamers", [])
                            live_succeeded = True
                            sources_used.append(
                                "YouTube Data API v3 (Rate-Limited Fallback)"
                            )
                            logger.info(
                                f"YouTube: Rate-limited/failed. Using "
                                f"fallback cached viewers for "
                                f"'{title}': {youtube_v:,}"
                            )

            combined_streamers = list(td.get("top_streamers", []))
            combined_streamers.extend(yt_streamers)
            combined_streamers.sort(
                key=lambda x: x.get("viewer_count", 0), reverse=True
            )

            if live_succeeded:
                config = load_model_config()
                editors_pick_config = config.get("editors_pick") or {}
                staple = next(
                    (g for g in STAPLE_GAMES if g["title"].lower() == title.lower()),
                    None,
                )
                if (
                    not staple
                    and editors_pick_config.get("title", "").lower() == title.lower()
                ):
                    staple = editors_pick_config
                avg_length = _estimate_avg_length(title, api_key, model=model)
                score = _calculate_score(twitch_v, youtube_v)
                source_str = " + ".join(sources_used)

                box_art = td.get("box_art_url")
                results[title.lower()] = _build_canonical_game(
                    title=title,
                    category=_infer_category(title, staple, box_art_url=box_art),
                    twitch_viewers=twitch_v,
                    youtube_viewers=youtube_v,
                    avg_length_hours=avg_length,
                    score=score,
                    source=source_str,
                    source_url=(
                        f"https://www.twitch.tv/directory/game/"
                        f"{urllib.parse.quote(title)}"
                    ),
                    tier="staple",
                    data_quality="live",
                    youtube_fetched_at=youtube_fetched
                    if youtube.is_configured
                    else None,
                    top_streamers=combined_streamers,
                    stream_count=td.get("stream_count", 0),
                    cover_url=box_art,
                )

    # --- Path 2: Gemini fallback for unresolved titles ---
    unresolved = [t for t in game_titles if t.lower() not in results]
    if unresolved and api_key:
        try:
            prompt = (
                "Retrieve current live streaming viewership statistics for "
                "the following video games using Google Search:\n"
                + "\n".join(f"- {t}" for t in unresolved)
                + "\n\nReturn ONLY a raw JSON array of objects. "
                + "Each object MUST have these keys:\n"
                "- 'title' (string, matching the input name exactly)\n"
                "- 'category' (string, e.g. RPG, FPS, etc.)\n"
                "- 'twitch_viewers' (int, current average concurrent Twitch viewers)\n"
                "- 'youtube_viewers' (int, current average "
                "concurrent YouTube viewers)\n"
                "- 'avg_length_hours' (float, average stream session length)\n"
                "- 'score' (int 0-100, streaming viability score)\n"
                "- 'source' (string, source name)\n"
                "- 'source_url' (string, verifiable URL)\n"
                "Do NOT include markdown code fences or text outside the JSON array."
            )
            logger.info(
                f"Querying Gemini (estimate fallback) for "
                f"{len(unresolved)} unresolved game(s)..."
            )
            response = safe_generate_content(
                api_key=api_key,
                model=model,
                contents=prompt,
                use_google_search=True,
            )
            scraped = parse_json_response(response.text)
            if isinstance(scraped, list):
                for sg in scraped:
                    title = sg.get("title")
                    if not title or title.lower() in results:
                        continue
                    twitch_v = int(sg.get("twitch_viewers", 0))
                    youtube_v = int(sg.get("youtube_viewers", 0))
                    results[title.lower()] = _build_canonical_game(
                        title=title,
                        category=sg.get("category", "Unknown"),
                        twitch_viewers=twitch_v,
                        youtube_viewers=youtube_v,
                        avg_length_hours=float(sg.get("avg_length_hours", 3.0)),
                        score=int(sg.get("score", 50)),
                        source="Gemini Search Estimate",
                        source_url=sg.get("source_url", ""),
                        tier="staple",
                        data_quality="estimated",
                    )
                    logger.info(
                        f"Viewership [Gemini estimate]: {title} — "
                        f"Twitch {twitch_v:,} | YouTube {youtube_v:,}"
                    )
        except Exception as e:
            logger.warning(f"Gemini viewership fallback failed: {e}")

    # --- Path 3: STAPLE_GAMES baseline for any remaining gaps (no noise) ---
    still_unresolved = [t for t in game_titles if t.lower() not in results]
    for title in still_unresolved:
        staple = next(
            (g for g in STAPLE_GAMES if g["title"].lower() == title.lower()), None
        )
        if staple:
            results[title.lower()] = _build_canonical_game(
                title=staple["title"],
                category=staple["category"],
                twitch_viewers=staple["avg_viewers"],
                youtube_viewers=0,
                avg_length_hours=staple["avg_length_hours"],
                score=staple["score"],
                source="Local Fallback (no live data)",
                source_url=(
                    f"https://www.twitch.tv/directory/game/"
                    f"{urllib.parse.quote(staple['title'])}"
                ),
                tier="staple",
                data_quality="no_live_data",
            )
            logger.warning(
                f"Used STAPLE baseline (no live data) for: {staple['title']}"
            )
        else:
            # Unknown game — return 0 viewers, labeled explicitly
            results[title.lower()] = _build_canonical_game(
                title=title,
                category="Custom",
                twitch_viewers=0,
                youtube_viewers=0,
                avg_length_hours=3.0,
                score=0,
                source="No data available",
                source_url=(
                    f"https://www.twitch.tv/directory/game/{urllib.parse.quote(title)}"
                ),
                tier="staple",
                data_quality="no_live_data",
            )
            logger.warning(f"No live data available for unknown game: '{title}'")

    # Return in the same order as game_titles
    return [results[t.lower()] for t in game_titles if t.lower() in results]


# ---------------------------------------------------------------------------
# Custom-games thin wrapper (unchanged public contract)
# ---------------------------------------------------------------------------


def scrape_metrics(
    custom_games: list[str] = None,
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    model: Optional[str] = None,
) -> tuple[list[dict], list[str]]:
    """
    Custom-games-only thin wrapper.

    - If custom_games is non-empty: fetches live viewership for those titles,
      tags them custom=True / tier="custom", merges them into cache.json
      (replacing any prior custom entries), and returns the new custom
      entries + logs.
    - If custom_games is empty/None: returns the current cache.json contents
      without triggering any scraping. The bulk refresh is owned by
      refresh_hourly_cache() in advisor.py.
    """
    from ag_kaggle_5day.agents.scraper import _CACHE_LOCK_FILE, CACHE_FILE

    logs: list[str] = []

    def log(level: str, msg: str):
        logs.append(f"[{level.upper()}] {msg}")
        if level.upper() in ("WARNING", "ERROR"):
            logger.warning(msg)
        else:
            logger.info(msg)

    if custom_games is not None:
        log("INFO", f"Scraping viewership for {len(custom_games)} custom game(s)...")
        custom_results = scrape_viewership_for_games(
            [g.strip() for g in custom_games if g.strip()],
            api_key=api_key,
            twitch_client=twitch_client,
            youtube_client=youtube_client,
            model=model,
        )
        for g in custom_results:
            g["custom"] = True
            g["tier"] = "custom"
            g["refreshed_at"] = time.time()

        # Merge: keep non-custom cached games, replace custom ones
        # Use filelock to prevent race with hourly refresh
        lock = FileLock(_CACHE_LOCK_FILE, timeout=5)
        existing: list[dict] = []
        try:
            with lock:
                if os.path.exists(CACHE_FILE):
                    try:
                        with open(CACHE_FILE, "r") as f:
                            existing = json.load(f)
                    except Exception as e:
                        log("ERROR", f"Failed to read existing cache: {e}")

                merged = [g for g in existing if not g.get("custom", False)]
                merged.extend(custom_results)

                try:
                    with open(CACHE_FILE, "w") as f:
                        json.dump(merged, f, indent=2)
                    log(
                        "SUCCESS",
                        f"Cache updated with {len(custom_results)} custom game(s).",
                    )
                except Exception as e:
                    log("ERROR", f"Failed to write cache: {e}")
        except Exception as lock_err:
            log("ERROR", f"Could not acquire cache lock: {lock_err}")

        for g in custom_results:
            quality_label = g.get("data_quality", "unknown")
            log(
                "SUCCESS",
                f"Custom: {g['title']} — Twitch: {g['twitch_viewers']:,} | "
                f"YouTube: {g['youtube_viewers']:,} [{quality_label}]",
            )

        return custom_results, logs

    else:
        # No custom games — return whatever is in cache
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    cached = json.load(f)
                log(
                    "INFO",
                    f"Returned {len(cached)} games from cache "
                    f"(no custom games requested).",
                )
                return cached, logs
            except Exception as e:
                log("ERROR", f"Failed to read cache: {e}")

        log(
            "INFO",
            "No cache found and no custom games provided. "
            "Run refresh_hourly_cache() to populate.",
        )
        return [], logs


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------
