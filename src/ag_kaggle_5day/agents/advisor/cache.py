from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from filelock import FileLock

logger = logging.getLogger("streamer_advisor.advisor")
from ag_kaggle_5day.agents.scraper import (  # noqa: E402
    _CACHE_LOCK_FILE,
    CACHE_FILE,
    SPONSORED_GAMES,
    STAPLE_GAMES,
    TwitchAPIClient,
    YouTubeAPIClient,
)

CACHE_TTL_SECONDS = 3600


@dataclass
class _HourlyCacheStore:
    top5: list[dict] = field(default_factory=list)
    sponsored: list[dict] = field(default_factory=list)
    combined_games: list[dict] = field(default_factory=list)
    comparison_report: str = ""
    refreshed_at: float = 0.0
    data_quality: str = "no_live_data"  # 'live' | 'estimated' | 'no_live_data'
    analysis_model: str = ""
    history_cache: dict[str, list[dict]] = None
    history_cache_time: float = 0.0
    is_refreshing: bool = False
    expose_status: str = "idle"
    expose_error: str = ""

    @property
    def staples(self) -> list[dict]:
        return self.sponsored

    @staples.setter
    def staples(self, value: list[dict]):
        self.sponsored = value

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.refreshed_at) >= CACHE_TTL_SECONDS

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.refreshed_at)

    @property
    def report_cached(self) -> bool:
        return bool(self.comparison_report)


_store = _HourlyCacheStore()


def reload_cache_from_firestore_if_stale() -> None:
    """
    Checks if the in-memory cache is stale. If so, attempts to pull
    the latest combined_games and comparison_report documents from Firestore,
    updating the in-memory singleton _store.
    """
    if not _store.is_stale:
        return

    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        client = get_firestore_client()
        if not client:
            return

        logger.info("Local cache is stale. Checking Firestore for updates...")
        doc_games = client.collection("system_cache").document("combined_games").get()
        if doc_games.exists:
            doc_data = doc_games.to_dict()
            games = doc_data.get("data")
            timestamp = doc_data.get("timestamp")

            # Resolve Firestore timestamp to float epoch time
            fs_time = 0.0
            if timestamp:
                if hasattr(timestamp, "timestamp"):
                    fs_time = timestamp.timestamp()
                else:
                    fs_time = float(timestamp)

            # If Firestore has newer data, update our in-memory store
            if fs_time > _store.refreshed_at or not _store.combined_games:
                if games and isinstance(games, list):
                    _store.combined_games = games
                    _store.sponsored = [
                        g for g in games if g.get("tier") == "sponsored"
                    ]
                    _store.top5 = [g for g in games if g.get("tier") == "trending"][:5]
                    _store.refreshed_at = fs_time

                    # Update overall data quality status
                    all_qualities = {
                        g.get("data_quality", "no_live_data") for g in games
                    }
                    if "live" in all_qualities:
                        _store.data_quality = "live"
                    elif "estimated" in all_qualities:
                        _store.data_quality = "estimated"
                    else:
                        _store.data_quality = "no_live_data"

                    logger.info(
                        f"Dynamically reloaded {len(games)} games from Firestore "
                        f"system_cache. Refreshed at: {fs_time}"
                    )

        # Also pull the latest comparison report
        doc_report = (
            client.collection("system_cache").document("comparison_report").get()
        )
        if doc_report.exists:
            report_data = doc_report.to_dict().get("data")
            if report_data and isinstance(report_data, dict):
                report_html = report_data.get("report", "")
                if report_html:
                    _store.comparison_report = report_html
                    logger.info(
                        "Dynamically reloaded comparison report from Firestore."
                    )
    except Exception as e:
        logger.warning(f"Failed to reload cache from Firestore: {e}")


def get_hourly_cache() -> _HourlyCacheStore:
    """Exposes the cache store for read-only inspection (e.g. /api/cache/status)."""
    reload_cache_from_firestore_if_stale()
    return _store


def refresh_hourly_cache(
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    search_model: Optional[str] = None,
    analysis_model: Optional[str] = None,
    sync_news: bool = False,
) -> None:
    if _store.is_refreshing:
        logger.info(
            "refresh_hourly_cache: Refresh is already in progress. "
            "Skipping concurrent run."
        )
        return
    _store.is_refreshing = True
    try:
        _refresh_hourly_cache_internal(
            api_key=api_key,
            twitch_client=twitch_client,
            youtube_client=youtube_client,
            search_model=search_model,
            analysis_model=analysis_model,
            sync_news=sync_news,
        )
    finally:
        _store.is_refreshing = False


def _refresh_hourly_cache_internal(
    api_key: str = None,
    twitch_client: Optional[TwitchAPIClient] = None,
    youtube_client: Optional[YouTubeAPIClient] = None,
    search_model: Optional[str] = None,
    analysis_model: Optional[str] = None,
    sync_news: bool = False,
) -> None:
    """
    Performs the full hourly refresh:
      1. Discovers top-10 trending games (Twitch Helix → Gemini estimate
         → SPONSORED fallback).
      2. Fetches live viewership for all SPONSORED_GAMES titles.
      3. Loads custom entries from cache.json and updates their viewership.
      4. De-duplicates trending ∪ custom ∪ sponsored (trending wins on conflict).
      5. Synchronously pre-fetches news articles for trending and custom games.
      6. Generates and caches the comparative analytics HTML report (including
         news/custom).
      7. Persists combined games list to cache.json (filelock protected).
      8. Updates store.data_quality based on the sources actually used.
    """
    from ag_kaggle_5day.agents.advisor import (
        discover_top_games,
        get_visible_trending_games,
        prefetch_news_for_games,
        prefetch_news_for_games_sync,
        scrape_viewership_for_games,
    )

    logger.info("=== Hourly cache refresh started ===")
    now = time.time()

    twitch = twitch_client or TwitchAPIClient()
    youtube = youtube_client or YouTubeAPIClient()

    # --- Step 1: Discover top-100 trending ---
    try:
        trending = discover_top_games(
            api_key=api_key,
            twitch_client=twitch,
            youtube_client=youtube,
            model=search_model,
            category="overall",
            limit=100,
        )
        logger.info(f"Trending discovery: {len(trending)} game(s) returned.")
        for g in trending:
            g["refreshed_at"] = now
    except Exception as e:
        logger.error(f"discover_top_games failed: {e}", exc_info=True)
        trending = []

    # --- Step 2: Live viewership for sponsored games ---
    sponsored_titles = [g["title"] for g in SPONSORED_GAMES]
    try:
        sponsored = scrape_viewership_for_games(
            sponsored_titles,
            api_key=api_key,
            twitch_client=twitch,
            youtube_client=youtube,
            model=search_model,
        )
        for g in sponsored:
            g["tier"] = "sponsored"
            g["refreshed_at"] = now
        logger.info(f"Sponsored viewership fetched: {len(sponsored)} game(s).")
    except Exception as e:
        logger.error(
            f"scrape_viewership_for_games failed for sponsored: {e}", exc_info=True
        )
        sponsored = []

    # --- Step 3: Load custom entries and refresh their metrics ---
    # Decoupled: Custom games are session-specific and managed in client requests.
    custom_entries: list[dict] = []
    source_games = []
    if _store.combined_games:
        source_games = _store.combined_games
    else:
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

            db_games = get_app_cache_state("combined_games")
            if db_games and isinstance(db_games, list):
                source_games = db_games
        except Exception as e:
            logger.warning(f"Failed to load combined_games from Firestore: {e}")

    # --- Step 3.5: Load editor's pick and fetch its metrics ---
    from ag_kaggle_5day.agents.scraper import load_model_config

    config = load_model_config()
    editors_pick_config = config.get("editors_pick")
    editors_pick = []
    if editors_pick_config:
        title = editors_pick_config.get("title")
        if title:
            try:
                scraped = scrape_viewership_for_games(
                    [title],
                    api_key=api_key,
                    twitch_client=twitch,
                    youtube_client=youtube,
                    model=search_model,
                )
                if scraped:
                    g = scraped[0]
                    g["tier"] = "editors_pick"
                    g["refreshed_at"] = now
                    editors_pick = [g]
                else:
                    prev_pick = next(
                        (g for g in source_games if g.get("tier") == "editors_pick"),
                        None,
                    )
                    if prev_pick:
                        editors_pick = [prev_pick]
                    else:
                        g = dict(editors_pick_config)
                        g["tier"] = "editors_pick"
                        g["refreshed_at"] = now
                        editors_pick = [g]
            except Exception as e:
                logger.error(f"Failed to fetch metrics for editors pick: {e}")
                prev_pick = next(
                    (g for g in source_games if g.get("tier") == "editors_pick"), None
                )
                if prev_pick:
                    editors_pick = [prev_pick]
                else:
                    g = dict(editors_pick_config)
                    g["tier"] = "editors_pick"
                    g["refreshed_at"] = now
                    editors_pick = [g]

    # --- Step 4: De-duplicate (custom > sponsored > editors_pick > trending) ---
    seen_titles: set[str] = set()
    combined: list[dict] = []
    for g in custom_entries + sponsored + editors_pick + trending:
        key = g["title"].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            combined.append(g)

    # Force "tier": "sponsored" for any game in combined that belongs to SPONSORED_GAMES
    sponsored_titles_set = {g["title"].lower() for g in SPONSORED_GAMES}
    for g in combined:
        if g["title"].lower() in sponsored_titles_set:
            g["tier"] = "sponsored"

    # --- Step 5: Determine overall data quality ---
    all_qualities = {g.get("data_quality", "no_live_data") for g in combined}
    if "live" in all_qualities:
        overall_quality = "live"
    elif "estimated" in all_qualities:
        overall_quality = "estimated"
    else:
        overall_quality = "no_live_data"

    # --- Step 5.5: Cache Quality Protection Check ---
    # Never overwrite a higher-quality existing cache (live/estimated)
    # with a lower-quality fallback cache (no_live_data).
    if overall_quality == "no_live_data":
        existing_overall = "no_live_data"
        if _store.combined_games:
            existing_qualities = {
                g.get("data_quality", "no_live_data") for g in _store.combined_games
            }
            existing_overall = (
                "live"
                if "live" in existing_qualities
                else (
                    "estimated" if "estimated" in existing_qualities else "no_live_data"
                )
            )
        else:
            try:
                from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

                existing = get_app_cache_state("combined_games")
                if existing and isinstance(existing, list):
                    existing_qualities = {
                        g.get("data_quality", "no_live_data") for g in existing
                    }
                    existing_overall = (
                        "live"
                        if "live" in existing_qualities
                        else (
                            "estimated"
                            if "estimated" in existing_qualities
                            else "no_live_data"
                        )
                    )
            except Exception as check_err:
                logger.warning(
                    f"Failed to check existing Firestore cache quality: {check_err}"
                )

        if existing_overall in ("live", "estimated"):
            logger.warning(
                f"=== Skipping cache overwrite ===\n"
                f"New refresh failed to fetch live data "
                f"(overall_quality='{overall_quality}'), "
                f"but existing cache contains superior data "
                f"(existing_overall='{existing_overall}'). "
                f"Aborting cache save and report generation to protect "
                f"existing data."
            )
    # Fetch active Steam player counts keylessly for all resolved games
    logger.info("Resolving Steam player counts for combined games list...")
    from ag_kaggle_5day.agents.scraper import (
        get_steam_appid_by_name,
        get_steam_player_count,
    )

    for g in combined:
        title = g.get("title")
        if title:
            try:
                appid = get_steam_appid_by_name(title)
                if appid:
                    players = get_steam_player_count(appid)
                    g["steam_player_count"] = players
                else:
                    g["steam_player_count"] = None
            except Exception as steam_err:
                logger.warning(
                    f"Failed to fetch Steam players for '{title}': {steam_err}"
                )
                g["steam_player_count"] = None

    # --- Step 6: Update store (games list first) ---
    _store.top5 = trending
    _store.sponsored = [g for g in combined if g.get("tier") == "sponsored"]
    _store.combined_games = combined
    _store.refreshed_at = time.time()
    _store.data_quality = overall_quality

    # --- Step 7: Persist to cache.json (filelock protected) ---
    lock = FileLock(_CACHE_LOCK_FILE, timeout=5)
    try:
        with lock:
            with open(CACHE_FILE, "w") as f:
                json.dump(combined, f, indent=2)
            logger.info(
                f"cache.json persisted: {len(combined)} total entries. "
                f"quality={overall_quality}"
            )
        # Save to Firestore system_cache
        try:
            from ag_kaggle_5day.agents.gcp_storage import store_app_cache_state

            store_app_cache_state("combined_games", combined)
        except Exception as store_err:
            logger.error(
                f"Failed to store combined_games in Firestore system_cache: {store_err}"
            )
    except Exception as e:
        logger.error(f"Failed to persist cache.json: {e}", exc_info=True)

    # Write to BigQuery persistently
    from ag_kaggle_5day.agents.gcp_storage import write_metrics_to_bigquery

    try:
        write_metrics_to_bigquery(combined)
    except Exception as bq_err:
        logger.error(f"Failed to write metrics to BigQuery: {bq_err}", exc_info=True)

    # --- Step 8: Generate comparison report FIRST (disabled/deprecated) ---
    logger.info("refresh_hourly_cache: Comparison report generation is disabled.")

    # Only pre-fetch news for games actually used in the comparison report and playbooks
    # (visible trending across all categories, custom, sponsored, and editor's pick)
    # to stay well within API limits
    visible_trending = get_visible_trending_games(trending, limit=10)
    news_targets = []
    seen_targets = set()
    for g in visible_trending + custom_entries + sponsored + editors_pick:
        title = g.get("title", "").strip().lower()
        if title and title not in seen_targets:
            seen_targets.add(title)
            news_targets.append(g)

    if sync_news:
        logger.info(
            f"Starting synchronous news pre-fetch for "
            f"{len(news_targets)} target game(s)..."
        )
        try:
            prefetch_news_for_games_sync(
                news_targets, api_key=api_key, model=search_model
            )
        except Exception as news_err:
            logger.error(
                f"Synchronous news pre-fetch failed: {news_err}", exc_info=True
            )
    else:
        logger.info(
            f"Starting non-blocking news pre-fetch for "
            f"{len(news_targets)} target game(s)..."
        )
        try:
            prefetch_news_for_games(news_targets, api_key=api_key, model=search_model)
        except Exception as news_err:
            logger.error(
                f"Non-blocking news pre-fetch failed to start: {news_err}",
                exc_info=True,
            )

    # Discover and profile micro-streamers hourly
    try:
        from ag_kaggle_5day.agents.scraper import discover_and_profile_micro_streamers

        discover_and_profile_micro_streamers(count=5, api_key=api_key)
    except Exception as ms_err:
        logger.error(
            f"Failed to discover and profile micro streamers: {ms_err}", exc_info=True
        )

    logger.info(
        f"=== Hourly cache refresh complete: {len(trending)} trending, "
        f"{len(sponsored)} sponsored, "
        f"report={'cached' if _store.comparison_report else 'empty'}, "
        f"quality={overall_quality} ==="
    )


def seed_firestore_cache_if_empty(force: bool = False) -> None:
    """
    Checks if the Firestore system_cache collection has the combined_games and
    comparison_report documents. If not (or if force=True), seeds them with defaults.
    """
    import urllib.parse

    from ag_kaggle_5day.agents.advisor import (
        _fallback_comparison_html,
        _local_custom_report_key,
    )
    from ag_kaggle_5day.agents.gcp_storage import (
        get_app_cache_state,
        get_firestore_client,
        store_app_cache_state,
    )
    from ag_kaggle_5day.agents.scraper import STAPLE_GAMES

    client = get_firestore_client()
    if not client:
        logger.warning("Firestore client not available. Skipping seeding.")
        return

    # 1. Seed combined_games if empty or forced
    games_state = None
    if not force:
        try:
            games_state = get_app_cache_state("combined_games")
        except Exception as e:
            logger.warning(f"Failed to check Firestore combined_games state: {e}")

    if force or not games_state:
        logger.info("Seeding Firestore system_cache with default STAPLE_GAMES...")
        results = []
        for g in STAPLE_GAMES:
            results.append(
                {
                    "title": g["title"],
                    "category": g["category"],
                    "avg_viewers": g["avg_viewers"],
                    "twitch_viewers": g["avg_viewers"],
                    "youtube_viewers": 0,
                    "avg_length_hours": g["avg_length_hours"],
                    "score": g["score"],
                    "source": "Local Fallback (no live data)",
                    "source_url": (
                        f"https://www.twitch.tv/directory/game/"
                        f"{urllib.parse.quote(g['title'])}"
                    ),
                    "custom": False,
                    "tier": "sponsored",
                    "data_quality": "no_live_data",
                    "refreshed_at": time.time(),
                }
            )
        try:
            store_app_cache_state("combined_games", results)
            # Warm in-memory cache as well
            _store.combined_games = results
            _store.sponsored = results
            _store.top5 = results[:5] if len(results) >= 5 else results
            _store.refreshed_at = time.time()
            _store.data_quality = "no_live_data"
            logger.info("Firestore combined_games seeded successfully.")
        except Exception as e:
            logger.error(f"Error seeding Firestore combined_games: {e}")

    # 2. Seed comparison_report if empty or forced
    report_state = None
    if not force:
        try:
            report_state = get_app_cache_state("comparison_report")
        except Exception as e:
            logger.warning(f"Failed to check Firestore comparison_report state: {e}")

    if force or not report_state:
        logger.info(
            "Seeding Firestore system_cache with default fallback comparison report..."
        )
        fallback_report = _fallback_comparison_html()
        try:
            store_app_cache_state("comparison_report", {"report": fallback_report})
            # Warm in-memory cache as well
            _store.comparison_report = fallback_report
            logger.info("Firestore comparison_report seeded successfully.")

            # Seed all category custom report keys as well
            categories = ["overall", "sandbox", "rpg", "fps", "racing"]
            for cat in categories:
                cat_fallback = _fallback_comparison_html(cat)
                key = _local_custom_report_key([], cat)
                data = {
                    "custom_games": [],
                    "category": cat,
                    "report": cat_fallback,
                    "status": "success",
                    "generated_at": time.time(),
                }
                store_app_cache_state(key, data)
                logger.info(f"Seeded Firestore key '{key}' for category '{cat}'")
        except Exception as e:
            logger.error(f"Error seeding Firestore comparison_report: {e}")


def get_cached_games() -> list[dict]:
    """
    Returns the full game list from the in-process store (trending + staples + custom).
    Falls back to cache.json if the store hasn't been populated yet.
    Enriches each game with the past 24 hours of viewership history from BigQuery.
    """
    from ag_kaggle_5day.agents.advisor import (
        _store,
        reload_cache_from_firestore_if_stale,
    )
    from ag_kaggle_5day.agents.scraper import CACHE_FILE

    reload_cache_from_firestore_if_stale()
    games = []
    if _store.combined_games:
        # Merge in custom entries from cache.json if they exist
        custom_entries: list[dict] = []
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    existing = json.load(f)
                custom_entries = [g for g in existing if g.get("custom", False)]
            except Exception:
                pass
        combined = list(_store.combined_games)
        seen = {g["title"].lower() for g in combined}
        for g in custom_entries:
            if g["title"].lower() not in seen:
                combined.append(g)
                seen.add(g["title"].lower())
        games = combined
    if not games:
        # 1. Try Firestore system_cache first
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

            db_games = get_app_cache_state("combined_games")
            if db_games and isinstance(db_games, list):
                games = db_games
                _store.combined_games = games
                logger.info(
                    f"Successfully loaded {len(games)} games from Firestore "
                    "system_cache fallback."
                )
        except Exception as db_err:
            logger.warning(f"Failed to load cached games from Firestore: {db_err}")

    if not games:
        # 2. Fall back to local cache.json
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    games = json.load(f)
                    _store.combined_games = games
            except Exception:
                pass

    if not games:
        # 3. Last resort: do NOT run a blocking scrape to avoid hanging the
        # request thread.
        # Instead, return the static STAPLE_GAMES immediately as a
        # no_live_data fallback.
        logger.warning(
            "Cache store empty and no cache.json found — returning STAPLE "
            "fallbacks immediately."
        )
        import urllib.parse

        results = []
        for g in STAPLE_GAMES:
            results.append(
                {
                    "title": g["title"],
                    "category": g["category"],
                    "avg_viewers": g["avg_viewers"],
                    "twitch_viewers": g["avg_viewers"],
                    "youtube_viewers": 0,
                    "avg_length_hours": g["avg_length_hours"],
                    "score": g["score"],
                    "source": "Local Fallback (no live data)",
                    "source_url": (
                        f"https://www.twitch.tv/directory/game/"
                        f"{urllib.parse.quote(g['title'])}"
                    ),
                    "custom": False,
                    "tier": "staple",
                    "data_quality": "no_live_data",
                }
            )
        games = results

    # Enrich games with historical viewership from BigQuery
    # Cache the historical mapping for 10 minutes (600 seconds)
    if _store.history_cache is None or (time.time() - _store.history_cache_time) > 600:
        history_map = {}
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

            client = get_bigquery_client()
            if client:
                dataset_id = f"{client.project}.streamer_metrics"
                table_id = f"{dataset_id}.hourly_stats"
                query = f"""
                    SELECT title, timestamp, twitch_viewers, youtube_viewers
                    FROM `{table_id}`
                    WHERE timestamp >= TIMESTAMP_SUB(
                        CURRENT_TIMESTAMP(), INTERVAL 24 HOUR
                    )
                    ORDER BY timestamp ASC
                """
                query_job = client.query(query, timeout=10)
                rows = list(query_job.result())
                for row in rows:
                    title_lower = row.title.lower().strip()
                    import datetime

                    ts = row.timestamp
                    if isinstance(ts, datetime.datetime):
                        t_val = ts.timestamp()
                    else:
                        t_val = datetime.datetime.fromisoformat(
                            str(ts).replace("Z", "+00:00")
                        ).timestamp()

                    pt = {
                        "time": t_val,
                        "twitch_viewers": row.twitch_viewers or 0,
                        "youtube_viewers": row.youtube_viewers or 0,
                        "viewers": (row.twitch_viewers or 0)
                        + (row.youtube_viewers or 0),
                    }
                    if title_lower not in history_map:
                        history_map[title_lower] = []
                    history_map[title_lower].append(pt)

                _store.history_cache = history_map
                _store.history_cache_time = time.time()
                logger.info(
                    f"Successfully loaded 24h historical trends for "
                    f"{len(history_map)} games from BigQuery."
                )
        except Exception as e:
            logger.warning(f"Failed to load historical data from BigQuery: {e}")

    # Inject history into the returning games list
    h_map = _store.history_cache or {}
    for g in games:
        g["history"] = h_map.get(g["title"].lower().strip(), [])

    return games
