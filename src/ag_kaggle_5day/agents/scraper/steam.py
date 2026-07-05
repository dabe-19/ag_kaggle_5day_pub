import logging
import urllib.parse
from typing import Optional

logger = logging.getLogger("streamer_advisor.scraper")

_steam_appid_cache = {}


def get_steam_appid_by_name(game_name: str) -> Optional[int]:
    """Resolves a Steam AppID for a game name using public keyless

    search with caching.
    """
    import hashlib

    if not game_name or game_name.lower() in ("offline", "unknown"):
        return None

    name_lower = game_name.strip().lower()

    # 1. Local static mapping for common tracked games to save requests
    static_map = {
        "counter-strike 2": 730,
        "dota 2": 570,
        "grand theft auto v": 271590,
        "apex legends": 1172470,
        "pubg: battlegrounds": 578080,
        "rust": 252490,
        "cyberpunk 2077": 1091500,
        "terraria": 105600,
        "stardew valley": 413150,
        "monster hunter: world": 582010,
        "elden ring": 1245620,
        "destiny 2": 1085660,
        "tf2": 440,
        "team fortress 2": 440,
        "fallout 4": 377160,
        "helldivers 2": 553850,
    }

    if name_lower in static_map:
        return static_map[name_lower]

    # 2. Check in-memory cache
    if name_lower in _steam_appid_cache:
        val = _steam_appid_cache[name_lower]
        return val if val != -1 else None

    # 3. Check Firestore system_cache
    doc_key = f"steam_appid_{hashlib.md5(name_lower.encode('utf-8')).hexdigest()}"
    try:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_app_cache_state,
            store_app_cache_state,
        )

        cached_val = get_app_cache_state(doc_key)
        if cached_val is not None:
            appid_val = int(cached_val)
            _steam_appid_cache[name_lower] = appid_val
            return appid_val if appid_val != -1 else None
    except Exception as fs_err:
        logger.warning(
            f"Failed to read Steam AppID from Firestore cache for "
            f"'{game_name}': {fs_err}"
        )

    # 4. Query public Steam store search API keylessly
    url = f"https://store.steampowered.com/api/storesearch/?term={urllib.parse.quote(game_name)}&l=english&cc=US"
    try:
        import requests

        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items:
                for item in items:
                    if item.get("type") == "app":
                        resolved_id = int(item.get("id"))
                        _steam_appid_cache[name_lower] = resolved_id
                        try:
                            store_app_cache_state(doc_key, resolved_id)
                        except Exception as store_err:
                            logger.warning(
                                "Failed to save Steam AppID to Firestore "
                                f"for '{game_name}': {store_err}"
                            )
                        return resolved_id
    except Exception as e:
        logger.warning(f"Failed to search Steam appid for '{game_name}': {e}")

    # Store negative hit (-1) to prevent repeated lookup attempts for
    # unknown/non-Steam games
    _steam_appid_cache[name_lower] = -1
    try:
        store_app_cache_state(doc_key, -1)
    except Exception as store_err:
        logger.warning(
            "Failed to save negative Steam AppID hit to Firestore "
            f"for '{game_name}': {store_err}"
        )
    return None


def get_steam_player_count(appid: int) -> int:
    """Queries Steam Web API keylessly to get the active player count for a game ID."""
    url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}"
    try:
        import requests

        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get("response", {}).get("player_count", 0)
    except Exception as e:
        logger.warning(f"Failed to fetch Steam player count for appid {appid}: {e}")
    return 0


# ---------------------------------------------------------------------------
# RaidSentinel Background Observational Worker
# ---------------------------------------------------------------------------
