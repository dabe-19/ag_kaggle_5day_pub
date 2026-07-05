import logging
import time
from typing import Optional

import requests

from ag_kaggle_5day.agents.scraper.games import (
    _TWITCH_STREAM_PAGE_CAP,
    TWITCH_CATEGORIES,
)

logger = logging.getLogger("streamer_advisor.scraper")


class TwitchAPIClient:
    """
    Wraps Twitch Helix API using the App Access Token (client credentials) flow.
    No user login is required.

    Credentials are read from env vars (TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
    unless supplied explicitly. Both must be present to use any Helix endpoint.
    """

    _TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    _HELIX_BASE = "https://api.twitch.tv/helix"

    def __init__(
        self, client_id: Optional[str] = None, client_secret: Optional[str] = None
    ):
        from ag_kaggle_5day.config import Settings

        current_settings = Settings()
        self.client_id = client_id or current_settings.TWITCH_CLIENT_ID or ""
        self.client_secret = (
            client_secret or current_settings.TWITCH_CLIENT_SECRET or ""
        )
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> str:
        """Fetches or returns a cached App Access Token."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        logger.info("Requesting new Twitch App Access Token...")
        resp = requests.post(
            self._TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        # expires_in is in seconds; record the wall-clock expiry time
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        logger.info("Twitch App Access Token acquired.")
        return self._token

    def _helix_get(self, path: str, params: dict) -> dict:
        """Makes a single authenticated GET request to the Helix API."""
        token = self._get_token()
        resp = requests.get(
            f"{self._HELIX_BASE}{path}",
            headers={
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {token}",
            },
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_top_games(self, n: int = 5) -> list[dict]:
        """
        Calls GET /helix/games/top to retrieve the top-n games by viewer count.
        Returns a list of {id, name, box_art_url} dicts.
        """
        logger.info(f"Fetching top {n} games from Twitch Helix API...")
        data = self._helix_get("/games/top", {"first": min(n, 100)})
        games = data.get("data", [])[:n]
        logger.info(f"Twitch Helix returned {len(games)} top games.")
        return games

    def get_game_id(self, game_name: str) -> Optional[str]:
        """
        Resolves a game name to a Twitch game_id via GET /helix/games?name=<name>.
        Returns None if not found.
        """
        try:
            data = self._helix_get("/games", {"name": game_name})
            items = data.get("data", [])
            if items:
                return items[0]["id"]
        except Exception as e:
            logger.warning(f"Twitch game_id lookup failed for '{game_name}': {e}")
        return None

    def get_game_details(self, game_name: str) -> Optional[dict]:
        """Resolves a game name to Twitch game details (ID and box art URL)."""
        try:
            data = self._helix_get("/games", {"name": game_name})
            items = data.get("data", [])
            if items:
                return {
                    "id": items[0]["id"],
                    "name": items[0]["name"],
                    "box_art_url": items[0].get("box_art_url"),
                }
        except Exception as e:
            logger.warning(f"Twitch game details lookup failed for '{game_name}': {e}")
        return None

    def get_viewers_for_game(self, game_id: str, game_name: str) -> dict:
        """
        Aggregates concurrent Twitch viewer count for a game by summing
        viewer_count across all live streams for that game_id.

        Paginates up to _TWITCH_STREAM_PAGE_CAP pages (100 streams/page)
        to stay within rate limits.

        Returns {"twitch_viewers": int, "stream_count": int}.
        """
        logger.info(f"Aggregating Twitch viewers for '{game_name}' (id={game_id})...")
        total_viewers = 0
        stream_count = 0
        cursor = None
        pages_fetched = 0

        while pages_fetched < _TWITCH_STREAM_PAGE_CAP:
            params: dict = {"game_id": game_id, "first": 100}
            if cursor:
                params["after"] = cursor

            try:
                data = self._helix_get("/streams", params)
            except Exception as e:
                logger.warning(f"Twitch streams request failed for '{game_name}': {e}")
                break

            streams = data.get("data", [])
            for stream in streams:
                total_viewers += stream.get("viewer_count", 0)
                stream_count += 1

            cursor = data.get("pagination", {}).get("cursor")
            pages_fetched += 1

            if not cursor or not streams:
                break

        logger.info(
            f"Twitch viewers for '{game_name}': {total_viewers:,} "
            f"across {stream_count} streams "
            f"({pages_fetched} page(s) fetched)."
        )
        return {"twitch_viewers": total_viewers, "stream_count": stream_count}

    def get_top_games_by_category(self, category: str, limit: int = 10) -> list[dict]:
        """Retrieves the top categories/games for the selected category directory.

        - 'overall': calls /games/top.
        - 'games': calls /games/top and filters out non-gaming directories.
        - IRL/Music/Creative/Esports: queries /streams with category game_ids,
          aggregates viewers, and returns the top `limit`.
        """
        category = category.lower().strip()
        if category in ("overall", "games"):
            logger.info(
                f"Fetching top {limit} games for category '{category}' "
                "from Twitch Helix..."
            )
            # Fetch extra games in case we need to filter
            raw_games = self.get_top_games(20 if category == "games" else limit)
            if category == "overall":
                return raw_games[:limit]

            # Filter out non-gaming
            _EXCLUDED_CATEGORIES = {
                "just chatting",
                "irl",
                "music",
                "art",
                "talk shows & podcasts",
                "pools, hot tubs, and beaches",
                "sports",
                "asmr",
                "makers & crafting",
                "software and game development",
            }
            filtered = [
                g
                for g in raw_games
                if g.get("name", "").lower() not in _EXCLUDED_CATEGORIES
            ]
            return filtered[:limit]

        # For specific category (IRL, Music, Creative, Esports)
        target_names = TWITCH_CATEGORIES.get(category, [])
        if not target_names:
            logger.warning(
                f"Unknown Twitch category '{category}', returning empty list."
            )
            return []

        logger.info(f"Resolving game IDs for {category} games: {target_names}...")
        # Resolve names to IDs using GET /games?name=...
        # Twitch supports up to 100 name parameters
        resolved_ids = {}
        try:
            # Build multiple name query parameters
            params = [("name", name) for name in target_names]
            data = self._helix_get("/games", params)
            for item in data.get("data", []):
                resolved_ids[item["id"]] = item["name"]
        except Exception as e:
            logger.warning(f"Failed to resolve category game IDs for {category}: {e}")
            return []

        if not resolved_ids:
            logger.warning(f"No game IDs resolved for {category} games.")
            return []

        logger.info(f"Fetching active streams for resolved IDs in {category}...")
        # Query streams with resolved game IDs
        stream_params = [("first", "100")]
        for g_id in resolved_ids:
            stream_params.append(("game_id", g_id))

        try:
            data = self._helix_get("/streams", stream_params)
            streams = data.get("data", [])
        except Exception as e:
            logger.warning(f"Failed to fetch streams for {category}: {e}")
            return []

        # Aggregate viewer counts by game ID
        viewership = {g_id: 0 for g_id in resolved_ids}
        for stream in streams:
            g_id = stream.get("game_id")
            if g_id in viewership:
                viewership[g_id] += stream.get("viewer_count", 0)

        # Sort resolved games by aggregated viewer count descending
        sorted_game_ids = sorted(
            viewership.keys(), key=lambda gid: viewership[gid], reverse=True
        )

        # Build return list of {id, name, box_art_url}
        results = []
        for gid in sorted_game_ids[:limit]:
            results.append(
                {
                    "id": gid,
                    "name": resolved_ids[gid],
                    "box_art_url": f"https://static-cdn.jtvnw.net/ttv-boxart/{gid}-52x72.jpg",
                }
            )
        return results

    def get_top_streamers(self, game_id: str, limit: int = 3) -> list[dict]:
        """
        Calls GET /helix/streams?game_id={game_id}&first={limit} to get top streamers.
        Returns a list of {user_name, user_login, title, viewer_count} dicts.
        """
        if not game_id:
            return []
        try:
            logger.info(f"Fetching top {limit} streamers for game_id={game_id}...")
            data = self._helix_get(
                "/streams", {"game_id": game_id, "first": min(limit, 100)}
            )
            streams = data.get("data", [])[:limit]

            results = []
            for s in streams:
                results.append(
                    {
                        "user_name": s.get("user_name"),
                        "user_login": s.get("user_login"),
                        "title": s.get("title"),
                        "viewer_count": s.get("viewer_count", 0),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"Failed to fetch top streamers for game {game_id}: {e}")
            return []

    def get_channel_details(self, user_login: str) -> Optional[dict]:
        """Calls GET /helix/users?login={user_login} to get channel metadata.

        Returns user details dict or None.
        """
        if not user_login:
            return None
        try:
            logger.info(f"Fetching channel details for user={user_login}...")
            data = self._helix_get("/users", {"login": user_login.strip()})
            users = data.get("data", [])
            if users:
                return users[0]
        except Exception as e:
            logger.warning(f"Failed to fetch channel details for {user_login}: {e}")
        return None

    def get_most_recent_video(self, user_login: str) -> Optional[dict]:
        """Gets the title and VOD URL of the most recent Twitch video/stream VOD."""
        if not user_login:
            return None
        try:
            # First resolve login to user_id
            user_info = self.get_channel_details(user_login)
            if not user_info:
                return None
            user_id = user_info.get("id")
            if not user_id:
                return None

            logger.info(f"Fetching most recent video for user_id={user_id}...")
            data = self._helix_get("/videos", {"user_id": user_id, "first": 1})
            videos = data.get("data", [])
            if videos:
                v = videos[0]
                return {
                    "title": v.get("title", ""),
                    "url": v.get("url", ""),
                    "language": v.get("language"),
                }
        except Exception as e:
            logger.warning(
                f"Failed to fetch most recent Twitch video for {user_login}: {e}"
            )
        return None

    def get_top_live_streams(self, limit: int = 100) -> list[dict]:
        """Calls GET /helix/streams to retrieve the top live streams across all games.
        Returns a list of {user_name, user_login, title, viewer_count, game_id,
        game_name} dicts.
        """
        try:
            logger.info(f"Fetching top {limit} live streams across Twitch...")
            data = self._helix_get("/streams", {"first": min(limit, 100)})
            streams = data.get("data", [])[:limit]

            results = []
            for s in streams:
                results.append(
                    {
                        "user_name": s.get("user_name"),
                        "user_login": s.get("user_login"),
                        "title": s.get("title"),
                        "viewer_count": s.get("viewer_count", 0),
                        "game_id": s.get("game_id"),
                        "game_name": s.get("game_name"),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"Failed to fetch top live streams: {e}")
            return []

    def get_online_streams(self, user_logins: list[str]) -> list[dict]:
        """Calls GET /helix/streams with a list of user_logins to find which
        ones are online.
        Returns a list of active stream dicts.
        """
        if not user_logins:
            return []
        try:
            # Helix allows up to 100 logins in a single query
            params = {"user_login": [u.strip().lower() for u in user_logins[:100]]}
            data = self._helix_get("/streams", params)
            return data.get("data", [])
        except Exception as e:
            logger.warning(f"Failed to check online streams: {e}")
            return []

    def get_recent_vods(self, user_id: str, limit: int = 5) -> list[dict]:
        """Calls GET /helix/videos?user_id={user_id}&first={limit}&type=archive

        to fetch past broadcast archives.
        """
        if not user_id:
            return []
        try:
            logger.info(f"Fetching past broadcast VODs for user_id={user_id}...")
            params = {
                "user_id": user_id,
                "first": min(limit, 100),
                "type": "archive",
            }
            data = self._helix_get("/videos", params)
            videos = data.get("data", [])
            results = []
            for v in videos:
                results.append(
                    {
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "view_count": v.get("view_count", 0),
                        "created_at": v.get("created_at"),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"Failed to fetch VODs for user_id {user_id}: {e}")
            return []

    def get_stream_tags(self, user_login: str) -> list[str]:
        """Fetches active tags for a streamer's live stream."""
        try:
            data = self._helix_get("/streams", {"user_login": user_login.strip()})
            streams = data.get("data", [])
            if streams:
                return streams[0].get("tags", [])
        except Exception as e:
            logger.warning(f"Failed to fetch stream tags for {user_login}: {e}")
        return []

    def get_game_tags(self, game_id: str) -> list[str]:
        """Fetches typical tags for a game by aggregating tags from top live streams."""
        if not game_id:
            return []
        try:
            data = self._helix_get("/streams", {"game_id": game_id, "first": 5})
            streams = data.get("data", [])
            tags_set = set()
            for s in streams:
                s_tags = s.get("tags", [])
                if s_tags:
                    for tag in s_tags:
                        tags_set.add(tag)
            return list(tags_set)
        except Exception as e:
            logger.warning(f"Failed to fetch game tags for game_id {game_id}: {e}")
        return []

    def get_broadcaster_clips(self, broadcaster_id: str, limit: int = 5) -> list[dict]:
        """Fetches recent/trending clips for a broadcaster ID."""
        if not broadcaster_id:
            return []
        try:
            data = self._helix_get(
                "/clips", {"broadcaster_id": broadcaster_id, "first": limit}
            )
            clips = data.get("data", [])
            results = []
            for c in clips:
                results.append(
                    {
                        "url": c.get("url", ""),
                        "view_count": c.get("view_count", 0),
                        "title": c.get("title", ""),
                        "created_at": c.get("created_at", ""),
                        "creator_name": c.get("creator_name", ""),
                    }
                )
            return results
        except Exception as e:
            logger.warning(
                f"Failed to fetch clips for broadcaster {broadcaster_id}: {e}"
            )
        return []

    def get_schedule(self, broadcaster_id: str) -> Optional[dict]:
        """Calls GET /helix/schedule to retrieve stream schedule."""
        if not broadcaster_id:
            return None
        try:
            data = self._helix_get("/schedule", {"broadcaster_id": broadcaster_id})
            return data.get("data")
        except Exception as e:
            logger.warning(
                f"Failed to fetch schedule for broadcaster {broadcaster_id}: {e}"
            )
            return None

    def query_igdb_genres(self, game_name: str) -> Optional[list[str]]:
        """Queries the IGDB API v4 to retrieve genre names for a game."""
        meta = self.query_igdb_metadata(game_name)
        return meta.get("genres") if meta else None

    def query_igdb_metadata(self, game_name: str) -> Optional[dict]:
        """Queries the IGDB API v4 to retrieve genre and theme names for a game."""
        if not game_name or not game_name.strip():
            return None
        try:
            token = self._get_token()
            headers = {
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            # Clean and escape the game name for query
            escaped_name = game_name.replace('"', '\\"')
            body = f'fields genres.name, themes.name; search "{escaped_name}"; limit 1;'

            resp = requests.post(
                "https://api.igdb.com/v4/games",
                headers=headers,
                data=body.encode("utf-8"),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                genres = [g["name"] for g in data[0].get("genres", []) if "name" in g]
                themes = [t["name"] for t in data[0].get("themes", []) if "name" in t]
                return {"genres": genres, "themes": themes}
        except Exception as e:
            logger.warning(f"Failed to query IGDB metadata for '{game_name}': {e}")
        return None


# ---------------------------------------------------------------------------
# YouTube Data API v3 client
# ---------------------------------------------------------------------------
