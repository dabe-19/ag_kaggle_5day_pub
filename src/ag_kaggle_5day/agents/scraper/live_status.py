import logging
import time
from typing import Optional

from ag_kaggle_5day.agents.scraper.twitch import TwitchAPIClient

logger = logging.getLogger("streamer_advisor.scraper")


def discover_and_profile_micro_streamers(count: int = 5, api_key: str = None) -> list:
    """
    Called by the hourly cron refresh.
    1. Selects games from cache.json that are live.
    2. Queries Twitch /streams endpoint for those games.
    3. Filters for channels with viewer_count < 10.
    4. Connects to IRC to sample chat for 180s.
    5. Stores the profiles in Firestore with unified schema.
    """
    logger.info("Starting discover_and_profile_micro_streamers task...")
    try:
        from ag_kaggle_5day.agents.advisor import get_cached_games
        from ag_kaggle_5day.agents.gcp_storage import (
            get_firestore_client,
            store_streamer_profile_fabric,
        )
        from ag_kaggle_5day.agents.scraper import (
            TwitchAPIClient,
            sample_live_chat,
        )

        fs = get_firestore_client()
        if not fs:
            logger.error(
                "discover_and_profile_micro_streamers: Firestore client not available"
            )
            return []

        twitch = TwitchAPIClient()
        if not twitch.is_configured:
            logger.warning(
                "discover_and_profile_micro_streamers: Twitch client not configured"
            )
            return []

        # Step 1: Gather candidate games from cache
        games = get_cached_games()
        if not games:
            # Fallback to some basic default games if empty
            games = [
                {"title": "Forza Horizon 5"},
                {"title": "Just Chatting"},
                {"title": "Minecraft"},
            ]

        import random

        # Shuffle to get different games each hour
        random.shuffle(games)

        discovered_micro_streamers = []
        candidates = []
        seen_logins = set()

        for g in games:
            if len(candidates) >= count:
                break

            title = g.get("title")
            game_id = twitch.get_game_id(title)
            if not game_id:
                continue

            # Step 2: Query Twitch Helix streams for this game_id
            try:
                # Get the first 100 streams of the game
                data = twitch._helix_get("/streams", {"game_id": game_id, "first": 100})
                streams = data.get("data", [])
            except Exception as stream_err:
                logger.warning(f"Failed to fetch streams for '{title}': {stream_err}")
                continue

            # Filter for streams where viewer_count < 10 and viewer_count > 0
            micro_pool = [s for s in streams if 0 < s.get("viewer_count", 0) < 10]
            if not micro_pool:
                continue

            # Shuffle micro pool to get random ones
            random.shuffle(micro_pool)

            for stream in micro_pool:
                if len(candidates) >= count:
                    break
                login = stream.get("user_login")
                if login in seen_logins:
                    continue
                seen_logins.add(login)
                candidates.append((stream, title))

        if not candidates:
            return []

        # Step 3: Concurrently sample chat for all candidates using ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor

        logger.info(
            f"Concurrently sampling live chat for {len(candidates)} micro-streamers..."
        )
        samples = {}
        with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            futures = {
                executor.submit(sample_live_chat, item[0].get("user_login"), 180): item[
                    0
                ].get("user_login")
                for item in candidates
            }
            for fut in futures:
                login = futures[fut]
                try:
                    samples[login] = fut.result()
                except Exception as sample_err:
                    logger.error(
                        f"Error sampling chat for micro-streamer {login}: {sample_err}"
                    )
                    samples[login] = {}

        # Step 4: Process samples and store profiles in Firestore
        for stream, title in candidates:
            login = stream.get("user_login")
            name = stream.get("user_name")
            viewers = stream.get("viewer_count", 1)

            chat_sample = samples.get(login) or {}
            mpm = chat_sample.get("msg_per_minute", 0.0)

            # Calculate IDR
            idr = mpm / viewers if viewers > 0 else 0.0

            # Calculate a rough sentiment volatility and polarity
            avg_volatility = 0.15

            # Fetch Twitch details, recent VOD, clips, schedule
            twitch_details = {}
            recent_twitch_video = None
            recent_clips = []
            twitch_schedule = None
            try:
                twitch_details = twitch.get_channel_details(login) or {}
                recent_twitch_video = twitch.get_most_recent_video(login)
                broadcaster_id = twitch_details.get("id")
                if broadcaster_id:
                    recent_clips = twitch.get_broadcaster_clips(broadcaster_id, limit=3)
                    twitch_schedule = twitch.get_schedule(broadcaster_id)
            except Exception as tw_err:
                logger.warning(
                    f"Failed to fetch Twitch details for "
                    f"micro-streamer {login}: {tw_err}"
                )

            # Build profile fabric dictionary
            profile_dict = {
                "streamer_handle": login,
                "twitch_display_name": twitch_details.get("display_name") or name,
                "archetype_cluster": "Cozy_Social_Interactive"
                if idr < 0.3
                else "Variety_Interactive",
                "primary_game": title,
                "top_games": [title],
                "fabric_status": "active_signal",
                "average_msg_per_minute": mpm,
                "std_msg_per_minute": 0.5,
                "average_chat_volatility": avg_volatility,
                "std_chat_volatility": 0.05,
                "youtube_title": None,
                "twitch_description": twitch_details.get("description")
                or stream.get("title", ""),
                "twitch_avatar": twitch_details.get("profile_image_url"),
                "recent_twitch_video_title": recent_twitch_video.get("title")
                if recent_twitch_video
                else None,
                "recent_twitch_video_url": recent_twitch_video.get("url")
                if recent_twitch_video
                else None,
                "recent_clips": recent_clips,
                "schedule": twitch_schedule,
                "tier": "micro_streamer",
                "interaction_density": {
                    "msg_per_minute": mpm,
                    "chat_volatility": avg_volatility,
                    "interactive_density_rate": idr,
                },
                "starfield_coordinates": {
                    "x": random.uniform(-0.8, 0.8),
                    "y": random.uniform(-0.8, 0.8),
                    "z": random.uniform(-0.8, 0.8),
                },
                "current_vibe_tribe": "0",  # Default cluster
                "last_updated": time.time(),
            }

            # Store profile to Firestore
            try:
                store_streamer_profile_fabric(login, profile_dict)
                logger.info(f"Successfully profiled and saved micro-streamer: {login}")
                discovered_micro_streamers.append({"login": login, "name": name})
            except Exception as save_err:
                logger.error(f"Failed to save micro-streamer profile: {save_err}")

        return discovered_micro_streamers
    except Exception as e:
        logger.error(
            f"Error in discover_and_profile_micro_streamers: {e}", exc_info=True
        )
        return []


def get_youtube_channel_live_status(channel_id: str) -> dict:
    """Checks if a YouTube channel is live on-demand using HTML scraping.

    Returns a dict with keys: is_live (bool), viewer_count (int), game_name
    (str), title (str).
    """
    import json
    import re

    import requests

    result = {
        "is_live": False,
        "viewer_count": 0,
        "game_name": "YouTube Live",
        "title": "",
    }

    cid = channel_id.strip().lstrip("@")
    # Heal case-preserved channel ID using Firestore cache if available
    try:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_case_preserved_youtube_id,
            get_firestore_client,
        )

        db_client = get_firestore_client()
        if db_client:
            healed = get_case_preserved_youtube_id(cid, None, db_client)
            if healed and healed != cid:
                cid = healed
    except Exception as e:
        logger.warning(f"YouTube live status check healing failed: {e}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa: E501
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Helper to parse viewer count from string like "8.5K watching", "8,504 watching",
    # "120 watching now"
    def parse_watching_text(text: str) -> int:
        text = (
            text.lower()
            .replace("watching", "")
            .replace("now", "")
            .replace("viewers", "")
            .strip()
        )
        num_str = text.replace(",", "")
        multiplier = 1
        if "k" in num_str:
            multiplier = 1000
            num_str = num_str.replace("k", "")
        elif "m" in num_str:
            multiplier = 1000000
            num_str = num_str.replace("m", "")

        match = re.search(r"[\d\.]+", num_str)
        if match:
            try:
                return int(float(match.group(0)) * multiplier)
            except ValueError:
                pass
        return 0

    # 1. Try `/streams` tab HTML scraping
    try:
        streams_url = f"https://www.youtube.com/channel/{cid}/streams"
        resp = requests.get(streams_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = None
            for marker in [
                "window['ytInitialData']",
                'window["ytInitialData"]',
                "var ytInitialData",
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
            if data:
                found_live = False

                def find_live_lockup(obj):
                    nonlocal found_live
                    if found_live:
                        return
                    if isinstance(obj, dict):
                        if "lockupViewModel" in obj:
                            vm = obj["lockupViewModel"]
                            is_live = False
                            viewers = 0
                            title = ""
                            try:
                                metadata_rows = vm["metadata"][
                                    "lockupMetadataViewModel"
                                ]["metadata"]["contentMetadataViewModel"][
                                    "metadataRows"
                                ]
                                for row in metadata_rows:
                                    for part in row.get("metadataParts", []):
                                        text = part.get("text", {}).get("content", "")
                                        if "watching" in text.lower():
                                            is_live = True
                                            viewers = parse_watching_text(text)
                            except KeyError:
                                pass

                            if is_live:
                                try:
                                    title = vm["metadata"]["lockupMetadataViewModel"][
                                        "title"
                                    ]["content"]
                                except KeyError:
                                    pass
                                result["is_live"] = True
                                result["viewer_count"] = viewers
                                result["title"] = title
                                found_live = True
                                return
                        for k, v in obj.items():
                            find_live_lockup(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_live_lockup(item)

                find_live_lockup(data)
                if result["is_live"]:
                    return result
    except Exception as e:
        logger.warning(f"YouTube status check `/streams` tab scraping exception: {e}")

    # 2. Fall back to `/live` page redirect
    url = f"https://www.youtube.com/channel/{cid}/live"
    try:
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        is_live = (
            '"isLive":true' in resp.text
            or 'itemprop="isLiveBroadcast" content="True"' in resp.text
            or 'itemprop="isLiveBroadcast" content="true"' in resp.text
        )
        if is_live:
            result["is_live"] = True
            # Try to find viewer count in HTML
            match = re.search(r'"concurrentViewers"\s*:\s*"(\d+)"', resp.text)
            if match:
                result["viewer_count"] = int(match.group(1))
            else:
                match = re.search(
                    r'"text"\s*:\s*"([^"]+watching[^"]*)"',
                    resp.text,
                    re.IGNORECASE,
                )
                if match:
                    result["viewer_count"] = parse_watching_text(match.group(1))

            # Try to find stream title
            match = re.search(
                r'<meta\s+name=["\']title["\']\s+content=["\']([^"\']+)["\']',
                resp.text,
            )
            if match:
                result["title"] = match.group(1)
            else:
                match = re.search(r"<title>([^<]+)</title>", resp.text)
                if match:
                    result["title"] = match.group(1).replace("- YouTube", "").strip()
            return result
    except Exception as e:
        logger.warning(f"YouTube status check `/live` scraping exception: {e}")

    return result


def check_streamer_live_status_ondemand(
    twitch_handle: Optional[str] = None,
    youtube_channel_id: Optional[str] = None,
) -> dict:
    """Checks if a streamer is currently live on Twitch and/or YouTube.

    Merges their live status and viewer count.
    """
    twitch_live = False
    twitch_viewers = 0
    twitch_game = ""
    twitch_title = ""
    twitch_language = "en"

    yt_live = False
    yt_viewers = 0
    yt_title = ""

    # Check Twitch
    if twitch_handle:
        try:
            client = TwitchAPIClient()
            if client.is_configured:
                streams = client.get_online_streams([twitch_handle])
                if streams:
                    stream = streams[0]
                    twitch_live = True
                    twitch_viewers = stream.get("viewer_count", 0)
                    twitch_game = stream.get("game_name", "")
                    twitch_title = stream.get("title", "")
                    twitch_language = stream.get("language", "en")
        except Exception as e:
            logger.warning(f"On-demand Twitch check failed for {twitch_handle}: {e}")

    # Check YouTube
    if youtube_channel_id:
        try:
            yt_status = get_youtube_channel_live_status(youtube_channel_id)
            if yt_status["is_live"]:
                yt_live = True
                yt_viewers = yt_status["viewer_count"]
                yt_title = yt_status["title"]
        except Exception as e:
            logger.warning(
                f"On-demand YouTube check failed for {youtube_channel_id}: {e}"
            )

    is_live = twitch_live or yt_live
    total_viewers = twitch_viewers + yt_viewers

    # Determine game name and source
    game_name = "Offline"
    source = "cache"
    if twitch_live and yt_live:
        game_name = twitch_game or "Multiplatform Live"
        source = "both"
    elif twitch_live:
        game_name = twitch_game or "Twitch Live"
        source = "twitch"
    elif yt_live:
        game_name = "YouTube Live"
        source = "youtube"

    resolved_language = "en"
    if twitch_live:
        resolved_language = twitch_language
    else:
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

            fs = get_firestore_client()
            if fs:
                lookup_handles = []
                if twitch_handle:
                    lookup_handles.append(twitch_handle.strip().lower())
                if youtube_channel_id:
                    lookup_handles.append(youtube_channel_id.strip().lower())
                for h in lookup_handles:
                    p_doc = fs.collection("streamer_profiles").document(h).get()
                    if p_doc.exists:
                        p_data = p_doc.to_dict()
                        if p_data.get("language"):
                            resolved_language = p_data["language"]
                            break
        except Exception:
            pass

        if resolved_language == "en" and twitch_handle:
            try:
                client = TwitchAPIClient()
                if client.is_configured:
                    vid = client.get_most_recent_video(twitch_handle)
                    if vid and vid.get("language"):
                        resolved_language = vid["language"]
            except Exception:
                pass

    return {
        "is_live": is_live,
        "viewer_count": total_viewers,
        "game_name": game_name,
        "title": twitch_title or yt_title or "",
        "source": source,
        "twitch_viewers": twitch_viewers,
        "youtube_viewers": yt_viewers,
        "language": resolved_language,
    }
