import hashlib
import json
import logging
import os
import threading
import time
from typing import Optional

import requests
from filelock import FileLock

logger = logging.getLogger("streamer_advisor.scraper")

QUOTA_STATUS_FILE = os.path.join(os.path.dirname(__file__), "quota_status.json")
_QUOTA_LOCK_FILE = QUOTA_STATUS_FILE + ".lock"


def _get_key_hash(key: str) -> str:
    if not key:
        return ""
    return hashlib.sha256(key.encode()).hexdigest()


def _is_quota_exceeded_persistent() -> bool:
    from ag_kaggle_5day.agents.scraper import _QUOTA_LOCK_FILE, QUOTA_STATUS_FILE

    if not os.path.exists(QUOTA_STATUS_FILE):
        return False
    try:
        lock = FileLock(_QUOTA_LOCK_FILE, timeout=5)
        with lock:
            with open(QUOTA_STATUS_FILE, "r") as f:
                data = json.load(f)
            timestamp = data.get("blocked_at", 0.0)
            if timestamp > 0.0 and time.time() - timestamp < 43200:  # 12 hours
                return True
    except Exception:
        pass
    return False


def _set_quota_exceeded_persistent(exceeded: bool, key_hash: str = "") -> None:
    from ag_kaggle_5day.agents.scraper import _QUOTA_LOCK_FILE, QUOTA_STATUS_FILE

    try:
        lock = FileLock(_QUOTA_LOCK_FILE, timeout=5)
        with lock:
            data = {"blocked_at": 0.0, "key_hash": ""}
            if os.path.exists(QUOTA_STATUS_FILE):
                try:
                    with open(QUOTA_STATUS_FILE, "r") as f:
                        data = json.load(f)
                except Exception:
                    pass
            if exceeded:
                data["blocked_at"] = time.time()
            else:
                data["blocked_at"] = 0.0
            data["key_hash"] = key_hash
            with open(QUOTA_STATUS_FILE, "w") as f:
                json.dump(data, f, indent=2)
    except Exception:
        pass


class YouTubeAPIClient:
    """
    Wraps YouTube Data API v3 to retrieve concurrent viewer counts for live
    gaming streams searched by game title.

    Quota cost per call to get_viewers_for_game():
      - 100 units (search.list) + ~1 unit (videos.list) = ~101 units per game title.

    API key is read from env var YOUTUBE_API_KEY unless supplied explicitly.
    """

    _lock = threading.Lock()
    _SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    _VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
    _quota_exceeded = False
    _last_key = ""

    def __init__(self, api_key: Optional[str] = None):
        from ag_kaggle_5day.agents.scraper import _QUOTA_LOCK_FILE, QUOTA_STATUS_FILE
        from ag_kaggle_5day.config import Settings

        current_settings = Settings()
        incoming_key = api_key or current_settings.YOUTUBE_API_KEY or ""
        self.api_key = incoming_key

        last_key_hash = ""
        if os.path.exists(QUOTA_STATUS_FILE):
            try:
                lock = FileLock(_QUOTA_LOCK_FILE, timeout=5)
                with lock:
                    with open(QUOTA_STATUS_FILE, "r") as f:
                        status_data = json.load(f)
                    last_key_hash = status_data.get("key_hash", "")
            except Exception:
                pass

        incoming_hash = _get_key_hash(incoming_key)
        # Clear quota block if a new/different API key is provided
        if incoming_key and incoming_hash != last_key_hash:
            YouTubeAPIClient._quota_exceeded = False
            _set_quota_exceeded_persistent(False, key_hash=incoming_hash)
            YouTubeAPIClient._last_key = incoming_key

    @property
    def is_configured(self) -> bool:
        return (
            bool(self.api_key)
            and not YouTubeAPIClient._quota_exceeded
            and not _is_quota_exceeded_persistent()
        )

    def get_most_recent_video(self, channel_id: str) -> Optional[dict]:
        """Gets the title and watch URL of the most recent video uploaded by

        channel_id.
        """
        if (
            YouTubeAPIClient._quota_exceeded
            or _is_quota_exceeded_persistent()
            or not self.api_key
        ):
            return None
        with YouTubeAPIClient._lock:
            try:
                search_url = "https://www.googleapis.com/youtube/v3/search"
                resp = requests.get(
                    search_url,
                    params={
                        "key": self.api_key,
                        "channelId": channel_id,
                        "order": "date",
                        "type": "video",
                        "part": "id,snippet",
                        "maxResults": 1,
                    },
                    timeout=3,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        item = items[0]
                        v_id = item.get("id", {}).get("videoId")
                        title = item.get("snippet", {}).get("title", "")
                        if v_id:
                            return {
                                "title": title,
                                "url": f"https://www.youtube.com/watch?v={v_id}",
                            }
            except Exception as e:
                logger.warning(f"Failed to fetch most recent YouTube video: {e}")
        return None

    def _scrape_viewers_via_html(self, game_name: str) -> Optional[dict]:
        import json
        import urllib.parse

        import requests

        query = game_name.strip()
        if not (query.startswith('"') and query.endswith('"')):
            query = f'"{query}"'
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}&sp=EgJAAQ%253D%253D"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code != 200:
                return None

            data = None
            for marker in [
                "var ytInitialData",
                "window['ytInitialData']",
                'window["ytInitialData"]',
            ]:
                idx = resp.text.find(marker)
                if idx != -1:
                    start_brace = resp.text.find("{", idx)
                    if start_brace != -1:
                        try:
                            data, _ = json.JSONDecoder().raw_decode(
                                resp.text[start_brace:]
                            )
                            break
                        except Exception:
                            pass
            if not data:
                return None
            video_renderers = []

            def find_renderers(obj):
                if isinstance(obj, dict):
                    if "videoRenderer" in obj:
                        video_renderers.append(obj["videoRenderer"])
                    for k, v in obj.items():
                        find_renderers(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_renderers(item)

            find_renderers(data)

            total_viewers = 0
            stream_count = 0
            streams_list = []

            for vr in video_renderers:
                view_text = vr.get("viewCountText", {}).get("simpleText", "")
                if not view_text:
                    runs = vr.get("viewCountText", {}).get("runs", [])
                    view_text = "".join(r.get("text", "") for r in runs)

                badges = vr.get("badges", [])
                badge_labels = [
                    b.get("metadataBadgeRenderer", {}).get("label", "") for b in badges
                ]

                is_live = (
                    "LIVE" in badge_labels
                    or "live" in view_text.lower()
                    or "watching" in view_text.lower()
                )
                viewers = 0

                if is_live and (
                    "watching" in view_text.lower()
                    or "watching now" in view_text.lower()
                ):
                    num_str = view_text.split(" ")[0].replace(",", "")
                    try:
                        if "K" in num_str:
                            viewers = int(float(num_str.replace("K", "")) * 1000)
                        elif "M" in num_str:
                            viewers = int(float(num_str.replace("M", "")) * 1000000)
                        else:
                            viewers = int(num_str)
                    except ValueError:
                        pass

                if is_live:
                    stream_count += 1
                    total_viewers += viewers

                    channel_title = "Unknown YouTuber"
                    owner_runs = vr.get("ownerText", {}).get("runs", [])
                    if owner_runs:
                        channel_title = owner_runs[0].get("text", "Unknown YouTuber")

                    channel_id = ""
                    if owner_runs and "navigationEndpoint" in owner_runs[0]:
                        channel_id = (
                            owner_runs[0]["navigationEndpoint"]
                            .get("browseEndpoint", {})
                            .get("browseId", "")
                        )

                    video_title = ""
                    title_runs = vr.get("title", {}).get("runs", [])
                    if title_runs:
                        video_title = title_runs[0].get("text", "")

                    streams_list.append(
                        {
                            "user_name": channel_title,
                            "user_login": channel_id,
                            "title": video_title,
                            "viewer_count": viewers,
                            "platform": "youtube",
                        }
                    )

            streams_list.sort(key=lambda x: x.get("viewer_count", 0), reverse=True)
            top_streamers = [s for s in streams_list if s.get("viewer_count", 0) > 0][
                :3
            ]
            if not top_streamers and streams_list:
                top_streamers = streams_list[:3]

            return {
                "youtube_viewers": total_viewers,
                "stream_count": stream_count,
                "top_streamers": top_streamers,
            }
        except Exception as e:
            logger.warning(f"YouTube HTML search scraper failed for '{game_name}': {e}")
            return None

    def _scrape_channel_stats_via_html(self, channel_id: str) -> dict:
        import re

        import requests
        from bs4 import BeautifulSoup

        url = f"https://www.youtube.com/channel/{channel_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/120.0.0.0"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                # Extract title
                title = ""
                name_meta = soup.find("meta", itemprop="name")
                if name_meta:
                    title = name_meta.get("content", "").strip()
                if not title:
                    og_title = soup.find("meta", property="og:title")
                    if og_title:
                        title = og_title.get("content", "").strip()
                if not title:
                    title_tag = soup.find("title")
                    if title_tag:
                        title = title_tag.text.replace("- YouTube", "").strip()
                if not title:
                    title = channel_id

                # Extract avatar
                avatar = ""
                og_image = soup.find("meta", property="og:image")
                if og_image:
                    avatar = og_image.get("content", "").strip()

                # Extract description
                desc = ""
                og_desc = soup.find("meta", property="og:description")
                if og_desc:
                    desc = og_desc.get("content", "").strip()

                # Extract subscribers count
                def parse_yt_count(text):
                    text = text.lower().strip()
                    multiplier = 1
                    if "k" in text:
                        multiplier = 1000
                        text = text.replace("k", "")
                    elif "thousand" in text:
                        multiplier = 1000
                        text = text.replace("thousand", "")
                    elif "m" in text:
                        multiplier = 1000000
                        text = text.replace("m", "")
                    elif "million" in text:
                        multiplier = 1000000
                        text = text.replace("million", "")

                    match = re.search(r"[\d\.]+", text)
                    if match:
                        return int(float(match.group(0)) * multiplier)
                    return 0

                subscribers = 0
                sub_match = re.search(
                    r"\"(\d+(?:\.\d+)?[KMB]?\s+subscribers?)\"", resp.text
                )
                if not sub_match:
                    sub_match = re.search(
                        r"\"(\d+(?:\.\d+)?\s+(?:thousand|million|billion)\s+subscribers?)\"",
                        resp.text,
                    )
                if sub_match:
                    subscribers = parse_yt_count(sub_match.group(1))

                # Extract videos count
                videos = 0
                vid_matches = re.findall(
                    r"\"(\d+(?:\.\d+)?[KMB]?\s+videos?)\"", resp.text
                )
                vid_matches_alt = re.findall(
                    r"\"(\d+(?:\.\d+)?\s+(?:thousand|million|billion)\s+videos?)\"",
                    resp.text,
                )
                all_vids = [parse_yt_count(x) for x in vid_matches + vid_matches_alt]
                if all_vids:
                    videos = max(all_vids)

                # Extract views count
                views_list = []
                for v_text in re.findall(
                    r"\"(\d+(?:\.\d+)?[KMB]?\s+views?)\"", resp.text
                ):
                    views_list.append(parse_yt_count(v_text))
                for v_text in re.findall(
                    r",\s*(\d+(?:\.\d+)?\s+(?:thousand|million|billion)\s+views?)",
                    resp.text,
                ):
                    views_list.append(parse_yt_count(v_text))
                total_views = sum(views_list) if views_list else 0

                return {
                    "youtube_subscribers": subscribers,
                    "youtube_views": total_views,
                    "youtube_videos": videos,
                    "youtube_avatar": avatar,
                    "youtube_description": desc,
                    "youtube_title": title,
                }
        except Exception as e:
            logger.warning(f"YouTube HTML channel stats scrape failed: {e}")
        return {}

    def get_channel_stats(self, channel_id: str) -> dict:
        """Retrieves subscriberCount, videoCount, viewCount, and description/avatar

        for channel_id.
        Tries zero-quota HTML scraper first as primary, falling back to official
        API if needed.
        """
        # Heal case-preserved channel ID using Firestore cache if available
        if (
            channel_id.lower().startswith("uc")
            and len(channel_id) == 24
            and channel_id.lower() == channel_id
        ):
            try:
                from ag_kaggle_5day.agents.gcp_storage import (
                    get_case_preserved_youtube_id,
                    get_firestore_client,
                )

                db_client = get_firestore_client()
                if db_client:
                    healed = get_case_preserved_youtube_id(channel_id, None, db_client)
                    if healed and healed != channel_id:
                        channel_id = healed
            except Exception as e:
                logger.warning(f"YouTube: Failed to heal channel ID {channel_id}: {e}")

        logger.info(
            f"YouTube: Fetching channel stats via HTML scrape for {channel_id}..."
        )
        try:
            html_data = self._scrape_channel_stats_via_html(channel_id)
            if (
                html_data
                and html_data.get("youtube_title")
                and html_data.get("youtube_subscribers", 0) > 0
            ):
                logger.info(f"YouTube HTML stats scrape succeeded for {channel_id}.")
                return html_data
        except Exception as html_err:
            logger.warning(
                f"YouTube: HTML stats scrape failed for {channel_id}: {html_err}"
            )

        # Fallback to official API if HTML scraper fails or returns incomplete data
        if self.is_configured:
            logger.info(
                "YouTube: Falling back to official API get_channel_stats for "
                f"{channel_id}..."
            )
            try:
                url = "https://www.googleapis.com/youtube/v3/channels"
                resp = requests.get(
                    url,
                    params={
                        "key": self.api_key,
                        "id": channel_id,
                        "part": "statistics,snippet",
                    },
                    timeout=4,
                )
                if resp.status_code in (403, 429):
                    YouTubeAPIClient._quota_exceeded = True
                    _set_quota_exceeded_persistent(
                        True, key_hash=_get_key_hash(self.api_key)
                    )
                    logger.warning(
                        "YouTube API quota exceeded during channels.list fallback."
                    )
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        item = items[0]
                        stats = item.get("statistics", {})
                        snippet = item.get("snippet", {})
                        thumbnails = snippet.get("thumbnails", {})
                        avatar_url = thumbnails.get("default", {}).get(
                            "url"
                        ) or thumbnails.get("medium", {}).get("url", "")

                        return {
                            "youtube_subscribers": int(stats.get("subscriberCount", 0)),
                            "youtube_views": int(stats.get("viewCount", 0)),
                            "youtube_videos": int(stats.get("videoCount", 0)),
                            "youtube_avatar": avatar_url,
                            "youtube_description": snippet.get("description", ""),
                            "youtube_title": snippet.get("title", ""),
                        }
            except Exception as e:
                logger.warning(
                    "YouTube API get_channel_stats fallback failed for "
                    f"{channel_id}: {e}"
                )

        return {}

    def get_viewers_for_game(
        self, game_name: str, max_results: int = 10, html_only: bool = False
    ) -> dict:
        """Retrieves concurrent viewers and top live streams for a game from

        YouTube. Always tries the zero-quota HTML search scraper first to
        preserve official API quota.
        """
        html_res = self._scrape_viewers_via_html(game_name)
        if html_res is not None:
            logger.info(
                f"YouTube viewers via HTML for '{game_name}': "
                f"{html_res['youtube_viewers']:,} across "
                f"{html_res['stream_count']} streams."
            )
            return html_res

        if html_only:
            logger.info(
                "YouTube: HTML scrape failed and html_only=True. "
                f"Skipping fallback for '{game_name}'."
            )
            return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}

        # Fallback to official API
        if YouTubeAPIClient._quota_exceeded or _is_quota_exceeded_persistent():
            logger.info(
                "YouTube API key disabled/blocked. Skipping official scrape "
                f"for '{game_name}'."
            )
            return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}

        logger.info(f"Fetching YouTube live viewers via API for '{game_name}'...")

        with YouTubeAPIClient._lock:
            try:
                query = game_name.strip()
                if not (query.startswith('"') and query.endswith('"')):
                    query = f'"{query}"'
                search_resp = requests.get(
                    self._SEARCH_URL,
                    params={
                        "key": self.api_key,
                        "q": query,
                        "type": "video",
                        "eventType": "live",
                        "videoCategoryId": "20",
                        "part": "id",
                        "maxResults": min(max_results, 50),
                    },
                    timeout=3,
                )
                if search_resp.status_code in (403, 429):
                    YouTubeAPIClient._quota_exceeded = True
                    _set_quota_exceeded_persistent(
                        True, key_hash=_get_key_hash(self.api_key)
                    )
                    return {
                        "youtube_viewers": 0,
                        "stream_count": 0,
                        "top_streamers": [],
                    }
                search_resp.raise_for_status()
            except Exception as err:
                logger.warning(
                    f"YouTube search request failed for '{game_name}': {err}"
                )
                time.sleep(0.5)
                return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}

            search_data = search_resp.json()
            video_ids = [
                item["id"]["videoId"]
                for item in search_data.get("items", [])
                if isinstance(item.get("id"), dict) and "videoId" in item["id"]
            ]

            if not video_ids:
                time.sleep(0.5)
                return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}

            try:
                videos_resp = requests.get(
                    self._VIDEOS_URL,
                    params={
                        "key": self.api_key,
                        "id": ",".join(video_ids),
                        "part": "liveStreamingDetails,snippet",
                    },
                    timeout=3,
                )
                if videos_resp.status_code in (403, 429):
                    YouTubeAPIClient._quota_exceeded = True
                    _set_quota_exceeded_persistent(
                        True, key_hash=_get_key_hash(self.api_key)
                    )
                    return {
                        "youtube_viewers": 0,
                        "stream_count": 0,
                        "top_streamers": [],
                    }
                videos_resp.raise_for_status()
            except Exception as err:
                logger.warning(
                    f"YouTube videos request failed for '{game_name}': {err}"
                )
                time.sleep(0.5)
                return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}

            videos_data = videos_resp.json()

            total_viewers = 0
            stream_count = 0
            streams_list = []
            for video in videos_data.get("items", []):
                details = video.get("liveStreamingDetails", {})
                snippet = video.get("snippet", {})
                viewers_str = details.get("concurrentViewers", "0")
                try:
                    v_count = int(viewers_str)
                    total_viewers += v_count
                    stream_count += 1
                except (ValueError, TypeError):
                    v_count = 0

                channel_title = snippet.get("channelTitle") or "Unknown YouTuber"
                channel_id = snippet.get("channelId") or ""
                video_title = snippet.get("title") or ""

                streams_list.append(
                    {
                        "user_name": channel_title,
                        "user_login": channel_id,
                        "title": video_title,
                        "viewer_count": v_count,
                        "platform": "youtube",
                    }
                )

            streams_list.sort(key=lambda x: x.get("viewer_count", 0), reverse=True)
            top_streamers = [s for s in streams_list if s.get("viewer_count", 0) > 0][
                :3
            ]
            if not top_streamers and streams_list:
                top_streamers = streams_list[:3]

            logger.info(
                f"YouTube viewers via API for '{game_name}': {total_viewers:,} "
                f"across {stream_count} streams."
            )
            time.sleep(0.5)
            return {
                "youtube_viewers": total_viewers,
                "stream_count": stream_count,
                "top_streamers": top_streamers,
            }


# ---------------------------------------------------------------------------
# Gemini Safe Content Generation with sequential fallback handling
# ---------------------------------------------------------------------------
