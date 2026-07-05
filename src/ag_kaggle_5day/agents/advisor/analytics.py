from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("streamer_advisor.advisor")


def get_streamer_profile_fabric(streamer_handle: str) -> Optional[dict]:
    """Retrieves a streamer's detailed profile fabric from the database."""
    from ag_kaggle_5day.agents.gcp_storage import get_streamer_profile_fabric_from_fs

    return get_streamer_profile_fabric_from_fs(streamer_handle)


def query_streamer_connections(filters: dict) -> list[dict]:
    """Queries DB to find similar or connected channels matching dimensions."""
    from ag_kaggle_5day.agents.gcp_storage import query_streamer_connections_from_fs

    return query_streamer_connections_from_fs(filters)


def get_unique_streamer_handles() -> list[str]:
    """Retrieves unique streamer handles from BigQuery or falls back to Firestore."""
    from ag_kaggle_5day.agents.advisor import get_cached_games

    handles = set()

    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq_client = get_bigquery_client()
    if bq_client:
        try:
            project = bq_client.project
            query = (
                "SELECT DISTINCT streamer_handle FROM "
                f"`{project}.streamer_metrics.sentiment_history`"
            )
            query_job = bq_client.query(query)
            for row in query_job:
                h = row.streamer_handle
                if h:
                    h_stripped = h.strip()
                    if h_stripped.lower().startswith("uc"):
                        if h_stripped.startswith("uc"):
                            h_stripped = "UC" + h_stripped[2:]
                        handles.add(h_stripped)
                    else:
                        handles.add(h_stripped.lower())
        except Exception as e:
            logger.error(f"Failed to query unique streamer handles from BigQuery: {e}")

    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs_client = get_firestore_client()
    if fs_client:
        try:
            docs = fs_client.collection("streamer_sentiment").stream()
            for doc in docs:
                h = doc.id
                if h:
                    data = doc.to_dict()
                    yt_id = data.get("youtube_channel_id")
                    if yt_id:
                        handles.add(yt_id.strip())
                    elif h.strip().lower().startswith("uc"):
                        cand = h.strip()
                        if cand.startswith("uc"):
                            cand = "UC" + cand[2:]
                        handles.add(cand)
                    else:
                        handles.add(h.strip().lower())
        except Exception as e:
            logger.error(f"Failed to get unique streamer handles from Firestore: {e}")

    # 3. Add active handles from cached games list
    try:
        games = get_cached_games() or []
        for g in games:
            for s in g.get("top_streamers") or []:
                login = s.get("user_login")
                if login:
                    login_stripped = login.strip()
                    if login_stripped.lower().startswith("uc"):
                        if login_stripped.startswith("uc"):
                            login_stripped = "UC" + login_stripped[2:]
                        handles.add(login_stripped)
                    else:
                        handles.add(login_stripped.lower())
    except Exception as e:
        logger.warning(f"Failed to load handles from cached games: {e}")

    if not handles:
        handles = {
            "ninja",
            "shroud",
            "pokimane",
            "xqc",
            "valkyrae",
            "tarik",
            "summit1g",
            "lirik",
            "criticalrole",
            "kaicenat",
        }

    # Get YouTube handles currently online in cached games list
    online_youtube_handles = set()
    try:
        games = get_cached_games() or []
        for g in games:
            for s in g.get("top_streamers") or []:
                login = s.get("user_login")
                if login and login.lower().startswith("uc"):
                    if login.startswith("uc"):
                        login = "UC" + login[2:]
                    online_youtube_handles.add(login)
    except Exception:
        pass

    # Get all document IDs in streamer_profiles to check for persistent accounts
    profile_ids = set()
    if fs_client:
        try:
            p_docs = fs_client.collection("streamer_profiles").select([]).stream()
            for doc in p_docs:
                profile_ids.add(doc.id.lower())
        except Exception as p_err:
            logger.warning(f"Failed to fetch streamer_profiles document IDs: {p_err}")

    # YouTube channels are only included if currently online in cached games list
    # or have a linked Twitch account
    filtered_handles = []
    from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

    online_youtube_lowercased = {x.lower() for x in online_youtube_handles}

    for h in handles:
        if h.lower().startswith("uc"):
            link_info = resolve_streamer_link(h, fs_client)
            has_twitch = link_info and link_info.get("twitch_handle")
            is_online = h.lower() in online_youtube_lowercased

            if is_online or has_twitch:
                filtered_handles.append(h)
        else:
            filtered_handles.append(h)

    return filtered_handles


def _process_single_streamer(
    handle: str, api_key: str, model: Optional[str] = None
) -> Optional[dict]:
    """Helper to process historical aggregation for a single streamer handle."""
    from ag_kaggle_5day.agents.advisor import (
        safe_generate_content,
    )
    from ag_kaggle_5day.agents.gcp_storage import (
        get_case_preserved_youtube_id,
        get_firestore_client,
        get_historical_sentiment_summary,
        store_daily_streamer_analytics_timeseries,
    )

    try:
        fs = get_firestore_client()
        if handle.lower().startswith("uc"):
            handle = get_case_preserved_youtube_id(handle.lower(), None, fs)
        else:
            handle = handle.lower()

        from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

        linked_youtube = None
        linked_twitch = None
        link_info = resolve_streamer_link(handle)

        friendly_name = handle
        if link_info and link_info.get("display_name"):
            friendly_name = link_info["display_name"]

        if link_info:
            linked_youtube = link_info.get("youtube_channel_id")
            linked_twitch = link_info.get("twitch_handle")

        history = get_historical_sentiment_summary(handle, limit=100)
        if linked_youtube:
            yt_history = get_historical_sentiment_summary(linked_youtube, limit=100)
            if yt_history:
                history.extend(yt_history)
                history.sort(key=lambda x: x.get("timestamp") or 0.0, reverse=True)
                history = history[:100]

        if not history:
            # First-time build: If currently live, do a quick 10s chat crawl to
            # bootstrap metrics!
            logger.info(
                f"First-time build for '{handle}' has no history. Checking live status to bootstrap metrics..."  # noqa: E501
            )
            try:
                from ag_kaggle_5day.agents.scraper import (
                    async_live_monitor_twitch_chat,
                    async_live_monitor_youtube_chat,
                    check_streamer_live_status_ondemand,
                )

                is_yt_channel = handle.lower().startswith("uc")
                twitch_handle = None if is_yt_channel else handle
                youtube_channel_id = handle if is_yt_channel else linked_youtube

                live_status = check_streamer_live_status_ondemand(
                    twitch_handle=twitch_handle,
                    youtube_channel_id=youtube_channel_id,
                )

                if live_status.get("is_live"):
                    logger.info(
                        f"Streamer '{handle}' is live. Running quick 10s chat crawl..."
                    )
                    import asyncio

                    loop = asyncio.new_event_loop()
                    if is_yt_channel:
                        msgs = loop.run_until_complete(
                            async_live_monitor_youtube_chat(handle, duration_sec=10.0)
                        )
                    else:
                        msgs = loop.run_until_complete(
                            async_live_monitor_twitch_chat(handle, duration_sec=10.0)
                        )
                    loop.close()

                    if msgs:
                        logger.info(
                            f"Collected {len(msgs)} chat messages. Synthesizing sentiment..."  # noqa: E501
                        )

                        prompt = (
                            f"Analyze the following chat log from streamer '{friendly_name}' and classify the overall sentiment (Positive, Negative, Mixed, or Neutral).\n"  # noqa: E501
                            "Provide a short summary bullet (1 sentence) of the chat's vibe and topic.\n\n"  # noqa: E501
                            "Chat Log:\n"
                            + "\n".join(f"- {m}" for m in msgs[:30])
                            + "\n\n"
                            'Format the output exactly as JSON: {"sentiment": "Positive/Negative/Mixed/Neutral", "summary": "your 1-sentence summary"}'  # noqa: E501
                        )

                        res = safe_generate_content(
                            api_key=api_key,
                            model=model,
                            contents=prompt,
                            system_instruction="You are a chat sentiment analyzer. Always respond with valid JSON matching the requested structure.",  # noqa: E501
                            chain_name="sentiment",
                        )

                        try:
                            import json

                            res_json = json.loads(
                                res.text.strip().strip("`").strip("json").strip()
                            )
                            sentiment_label = res_json.get("sentiment", "Neutral")
                            summary_text = res_json.get("summary", "Cozy chat vibes.")
                        except Exception:
                            sentiment_label = "Neutral"
                            summary_text = "Standard chat activity."

                        import time

                        from ag_kaggle_5day.agents.gcp_storage import (
                            store_streamer_sentiment_moment,
                        )

                        moment_data = {
                            "streamer_handle": handle,
                            "viewer_count": live_status.get("viewer_count", 0),
                            "msg_per_minute": len(msgs) * 6.0,
                            "chat_volatility": 0.5,
                            "sentiment": sentiment_label,
                            "summary": summary_text,
                            "game_name": live_status.get("game_name", "Unknown"),
                            "source": "youtube" if is_yt_channel else "twitch",
                            "timestamp": time.time(),
                            "language": live_status.get("language", "en"),
                        }
                        store_streamer_sentiment_moment(handle, moment_data)
                        history = [moment_data]
            except Exception as monitor_err:
                logger.warning(
                    f"Failed to run quick chat monitor for {handle}: {monitor_err}",
                    exc_info=True,
                )

        if not history:
            logger.info(
                f"No historical sentiment checks found for '{handle}'. "
                "Proceeding with default metrics and fetching profile metadata."
            )
            avg_velocity = 0.0
            std_velocity = 0.0
            avg_volatility = 0.0
            std_volatility = 0.0
            dominant_sentiment = "Neutral"
            consolidated_summary = "No live chat history collected yet."
            composite_summary = "No live chat history collected yet."
            primary_game = "Unknown"
            top_games = ["Unknown"]
            avg_viewers = 0
            time_active_cluster = "evening"
            fabric_status = "preliminary"
            total_checks = 0
        else:
            total_checks = len(history)
            fabric_status = "established" if total_checks >= 5 else "preliminary"

            time_bins = {"morning": 0, "afternoon": 0, "evening": 0, "latenight": 0}
            game_freq = {}
            sentiments = []
            msg_speeds = []
            viewer_counts = []

            for check in history:
                ts = check.get("timestamp", 0)
                if ts:
                    import datetime

                    dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                    hour = dt.hour
                    if 6 <= hour < 12:
                        time_bins["morning"] += 1
                    elif 12 <= hour < 18:
                        time_bins["afternoon"] += 1
                    elif 18 <= hour < 24:
                        time_bins["evening"] += 1
                    else:
                        time_bins["latenight"] += 1

                game = check.get("game_name", "Unknown")
                if game and game != "Unknown":
                    game_freq[game] = game_freq.get(game, 0) + 1

                sent = check.get("sentiment")
                if sent and sent != "Offline":
                    sentiments.append(sent)

                speed = check.get("msg_per_minute", 0.0)
                if speed > 0:
                    msg_speeds.append(speed)

                vc = check.get("viewer_count", 0)
                if vc > 0:
                    viewer_counts.append(vc)

            time_active_cluster = (
                max(time_bins, key=time_bins.get)
                if any(time_bins.values())
                else "evening"
            )

            sorted_games = sorted(game_freq.items(), key=lambda x: x[1], reverse=True)
            primary_game = sorted_games[0][0] if sorted_games else "Variety"
            top_games = [g[0] for g in sorted_games[:5]]
            if not top_games:
                top_games = ["Variety"]

            import numpy as np

            # Calculate msg_per_minute statistics
            if msg_speeds:
                avg_velocity = float(np.mean(msg_speeds))
                std_velocity = float(np.std(msg_speeds)) if len(msg_speeds) > 1 else 3.0
            else:
                avg_velocity = 10.0
                std_velocity = 3.0

            # Calculate chat_volatility statistics
            chat_volatilities = [
                float(check["chat_volatility"])
                for check in history
                if check.get("chat_volatility") is not None
            ]
            if chat_volatilities:
                avg_volatility = float(np.mean(chat_volatilities))
                std_volatility = (
                    float(np.std(chat_volatilities))
                    if len(chat_volatilities) > 1
                    else 0.15
                )
            else:
                avg_volatility = 0.5
                std_volatility = 0.15

            avg_viewers = (
                int(sum(viewer_counts) / len(viewer_counts)) if viewer_counts else 0
            )
            from collections import Counter

            dominant_sentiment = (
                Counter(sentiments).most_common(1)[0][0] if sentiments else "Neutral"
            )

            summaries = [
                check.get("summary", "") for check in history if check.get("summary")
            ]
            consolidated_summary = " | ".join(summaries[:5])

            moments = summaries
            recent_summaries = moments if moments else summaries[:20]
            composite_summary = ""

            # Optimization: avoid LLM calls for quiet streams
            if not moments and len(recent_summaries) < 5:
                composite_summary = (
                    f"(averaging {avg_velocity:.1f} msg/min) and "
                    f"mostly {dominant_sentiment.lower()} sentiment."
                )
            elif recent_summaries:
                prompt_name = friendly_name

                summary_bullets = "\n".join(f"- {s}" for s in recent_summaries)
                prompt = (
                    "Synthesize the following recent chat logs and highlight summaries for "  # noqa: E501
                    f"the streamer '{prompt_name}' into a cohesive, detailed "
                    "paragraph that captures specific events, discussion topics, game events, "  # noqa: E501
                    "and notable moments instead of a generic vibe summary:\n\n"
                    f"{summary_bullets}\n\n"
                    "Return ONLY the detailed synthesized paragraph. Do not include "
                    "markdown, bullet points, introductory phrases, or conversational filler."  # noqa: E501
                )
                try:
                    res = safe_generate_content(
                        api_key=api_key,
                        model=model,
                        contents=prompt,
                        system_instruction=(
                            "You are an expert chat analyst. Output a detailed paragraph "  # noqa: E501
                            "detailing specific events, discussion topics, and sentiment shifts."  # noqa: E501
                        ),
                        chain_name="sentiment",
                    )
                    composite_summary = res.text.strip()
                except Exception as llm_err:
                    logger.warning(
                        f"Failed to generate composite summary for '{handle}' via LLM: "
                        f"{llm_err}. Using fallback concatenated summary."
                    )
                    composite_summary = " | ".join(recent_summaries[:5])

        yt_stats = {}
        target_yt_channel = None
        if handle.lower().startswith("uc"):
            target_yt_channel = handle
        elif linked_youtube:
            target_yt_channel = linked_youtube

        if target_yt_channel:
            try:
                from ag_kaggle_5day.agents.scraper import YouTubeAPIClient

                yt_client = YouTubeAPIClient(api_key=api_key)
                yt_stats = yt_client.get_channel_stats(target_yt_channel)
            except Exception as yt_err:
                logger.warning(
                    f"Failed to fetch YouTube stats during profile aggregation: {yt_err}"  # noqa: E501
                )

        recent_yt_video = None
        if target_yt_channel:
            try:
                from ag_kaggle_5day.agents.scraper import YouTubeAPIClient

                yt_client = YouTubeAPIClient(api_key=api_key)
                recent_yt_video = yt_client.get_most_recent_video(target_yt_channel)
            except Exception as yt_vid_err:
                logger.warning(
                    f"Failed to fetch recent YouTube video for {target_yt_channel}: {yt_vid_err}"  # noqa: E501
                )

        recent_twitch_video = None
        twitch_details = {}
        recent_clips = []
        twitch_schedule = None
        try:
            from ag_kaggle_5day.agents.scraper import TwitchAPIClient

            twitch_client = TwitchAPIClient()
            if twitch_client.is_configured:
                twitch_handle = handle
                if handle.lower().startswith("uc") and linked_twitch:
                    twitch_handle = linked_twitch
                if not twitch_handle.lower().startswith("uc"):
                    twitch_details = (
                        twitch_client.get_channel_details(twitch_handle) or {}
                    )
                    recent_twitch_video = twitch_client.get_most_recent_video(
                        twitch_handle
                    )
                    broadcaster_id = twitch_details.get("id")
                    if broadcaster_id:
                        recent_clips = twitch_client.get_broadcaster_clips(
                            broadcaster_id, limit=3
                        )
                        twitch_schedule = twitch_client.get_schedule(broadcaster_id)
        except Exception as tw_err:
            logger.warning(
                f"Failed to fetch Twitch details/video/clips/schedule during profile aggregation: {tw_err}"  # noqa: E501
            )

        # Resolve language from history checks (most recent check wins)
        language = None
        for check in history:
            if check.get("language"):
                language = check["language"]
                break

        # Fallback to checking most recent Twitch VOD language if still None or "en"
        if (not language or language == "en") and not handle.lower().startswith("uc"):
            try:
                from ag_kaggle_5day.agents.scraper import TwitchAPIClient

                twitch_client = TwitchAPIClient()
                if twitch_client.is_configured:
                    v_info = twitch_client.get_most_recent_video(handle)
                    if v_info and v_info.get("language"):
                        language = v_info["language"]
            except Exception:
                pass

        if (not language or language == "en") and linked_twitch:
            try:
                from ag_kaggle_5day.agents.scraper import TwitchAPIClient

                twitch_client = TwitchAPIClient()
                if twitch_client.is_configured:
                    v_info = twitch_client.get_most_recent_video(linked_twitch)
                    if v_info and v_info.get("language"):
                        language = v_info["language"]
            except Exception:
                pass

        if not language:
            language = "en"

        from ag_kaggle_5day.agents.scraper.feature_library import (
            normalize_language_code,
        )

        language = normalize_language_code(language)

        profile = {
            "streamer_handle": handle,
            "twitch_display_name": twitch_details.get("display_name"),
            "average_msg_per_minute": avg_velocity,
            "std_msg_per_minute": std_velocity,
            "average_chat_volatility": avg_volatility,
            "std_chat_volatility": std_volatility,
            "dominant_sentiment": dominant_sentiment,
            "consolidated_chat_summary": consolidated_summary,
            "composite_chat_summary": composite_summary,
            "primary_game": primary_game,
            "top_games": top_games,
            "viewer_count": avg_viewers,
            "time_active_cluster": time_active_cluster,
            "fabric_status": fabric_status,
            "total_checks": total_checks,
            "youtube_subscribers": yt_stats.get("youtube_subscribers"),
            "youtube_views": yt_stats.get("youtube_views"),
            "youtube_videos": yt_stats.get("youtube_videos"),
            "youtube_avatar": yt_stats.get("youtube_avatar"),
            "youtube_description": yt_stats.get("youtube_description"),
            "youtube_title": yt_stats.get("youtube_title"),
            "twitch_description": twitch_details.get("description"),
            "twitch_avatar": twitch_details.get("profile_image_url"),
            "recent_youtube_video_title": recent_yt_video.get("title")
            if recent_yt_video
            else None,
            "recent_youtube_video_url": recent_yt_video.get("url")
            if recent_yt_video
            else None,
            "recent_twitch_video_title": recent_twitch_video.get("title")
            if recent_twitch_video
            else None,
            "recent_twitch_video_url": recent_twitch_video.get("url")
            if recent_twitch_video
            else None,
            "language": language,
            "schedule": twitch_schedule,
            "recent_clips": recent_clips,
        }

        store_daily_streamer_analytics_timeseries(
            handle,
            {
                "average_msg_per_minute": avg_velocity,
                "dominant_sentiment": dominant_sentiment,
                "consolidated_chat_summary": consolidated_summary,
                "primary_game": primary_game,
                "top_games": top_games,
                "viewer_count": avg_viewers,
            },
        )
        return profile
    except Exception as e:
        logger.error(
            f"Failed to aggregate timeseries for '{handle}': {e}", exc_info=True
        )
        return None


def _classify_single_streamer_archetype(
    p: dict, api_key: str, model: Optional[str] = None
) -> dict:
    """Helper to classify a single streamer into archetype."""

    handle = p["streamer_handle"]
    friendly_name = p.get("youtube_title") or p.get("twitch_display_name") or handle
    if friendly_name.lower().startswith("uc"):
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(handle)
            if link_info and link_info.get("display_name"):
                friendly_name = link_info["display_name"]
        except Exception:
            pass

    try:
        prompt = (
            f"Classify the streamer '{friendly_name}' into exactly one of "
            "these standardized archetypes:\n"
            "- Cozy_Social_Interactive (slow, friendly chat, "
            "high viewer interaction, chill gameplay)\n"
            "- Highly_Competitive_Sweat (fast chat, shooter/esports "
            "games, gameplay focus, hype/rage vibe)\n"
            "- Informational_Guide (speedruns, tutorial, explaining "
            "mechanics, structured chat)\n"
            "- Variety_Entertainment (reacting, humor, high chat "
            "velocity, multiple games, meme-heavy)\n\n"
            f"Streamer details:\n"
            f"- Primary game category: {p['primary_game']}\n"
            f"- Top categories: {p['top_games']}\n"
            f"- Chat velocity: {p['average_msg_per_minute']} messages/minute\n"
            f"- Dominant sentiment: {p['dominant_sentiment']}\n"
            f"- Recent chat summaries: {p['consolidated_chat_summary']}\n\n"
            "Return ONLY the exact archetype name as a single string "
            "(no markdown, no quotes, no extra words)."
        )

        archetype_cluster = "Cozy_Social_Interactive"
        try:
            from ag_kaggle_5day.agents.scraper import safe_generate_content

            response = safe_generate_content(
                api_key=api_key,
                model=model,
                contents=prompt,
                system_instruction=(
                    "You are a classifier. Output only the archetype name."
                ),
            )
            res_text = response.text.strip()
            valid_archetypes = {
                "Cozy_Social_Interactive",
                "Highly_Competitive_Sweat",
                "Informational_Guide",
                "Variety_Entertainment",
            }
            if res_text in valid_archetypes:
                archetype_cluster = res_text
            else:
                for a in valid_archetypes:
                    if a.lower() in res_text.lower():
                        archetype_cluster = a
                        break
        except Exception as llm_err:
            logger.warning(
                f"Failed to query archetype for '{handle}' via LLM: "
                f"{llm_err}. Using default."
            )

        p["archetype_cluster"] = archetype_cluster
    except Exception as e:
        logger.error(f"Failed to classify archetype for '{handle}': {e}")
        p["archetype_cluster"] = "Cozy_Social_Interactive"
    return p


def run_daily_analytics_aggregation(api_key: str, model: str = None) -> None:
    """Runs daily analytics pipeline: aggregates timeseries & builds
    fabrics in parallel.
    """

    logger.info("Starting daily analytics aggregation pipeline...")

    from concurrent.futures import ThreadPoolExecutor

    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        store_streamer_profile_fabric,
    )

    # 1. Fetch all unique handles
    handles = get_unique_streamer_handles()

    # 2. Restrict to the 25 stalest/missing profiles that have >= 5
    # events since last update
    profile_updates = {}
    fs_client = get_firestore_client()
    if fs_client:
        try:
            docs = (
                fs_client.collection("streamer_profiles")
                .select(["last_aggregated"])
                .stream()
            )
            for doc in docs:
                data = doc.to_dict()
                ts = data.get("last_aggregated")
                ts_val = 0.0
                if ts:
                    if hasattr(ts, "timestamp"):
                        ts_val = ts.timestamp()
                    else:
                        try:
                            ts_val = float(ts)
                        except Exception:
                            pass
                profile_updates[doc.id.strip().lower()] = ts_val
        except Exception as e:
            logger.warning(
                f"Daily Analytics: Failed to fetch profile update times: {e}"
            )

    # Fetch new moments count per streamer
    from ag_kaggle_5day.agents.gcp_storage import (
        get_new_moments_counts_from_bq,
        get_new_moments_counts_from_fs,
    )

    moments_counts = get_new_moments_counts_from_bq()
    if not moments_counts:
        moments_counts = get_new_moments_counts_from_fs()

    candidates = []
    from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

    for h in handles:
        h_clean = h.strip().lower()

        # Exclude linked YouTube channels from standalone profile candidates to avoid
        # duplicates
        if h_clean.startswith("uc"):
            link_info = resolve_streamer_link(h_clean)
            if link_info and link_info.get("twitch_handle"):
                continue

        last_update = profile_updates.get(h_clean, 0.0)
        new_moments_count = moments_counts.get(h_clean, 0)

        # Skip standalone YouTube accounts with zero or very low activity
        # to avoid log flooding
        if h_clean.startswith("uc") and new_moments_count < 5:
            continue

        if (last_update > 0.0) or (last_update == 0.0 and new_moments_count >= 5):
            candidates.append((h_clean, last_update, new_moments_count))

    # Sort: oldest/never updated first (last_update ascending), then
    # highest event count (descending)
    candidates.sort(key=lambda x: (x[1], -x[2]))
    handles_to_process = [x[0] for x in candidates[:50]]

    logger.info(
        f"Daily Analytics: Found {len(candidates)} candidates with "
        f">= 5 events since last update. Selected top "
        f"{len(handles_to_process)} stalest for aggregation: "
        f"{handles_to_process}"
    )

    # 3. Process streamer histories and timeseries in parallel (10 workers)
    raw_profiles = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_process_single_streamer, h, api_key, model)
            for h in handles_to_process
        ]
        for f in futures:
            try:
                res = f.result()
                if res:
                    raw_profiles.append(res)
            except Exception as e:
                logger.error(f"Daily Analytics: Profile task error: {e}")

    # 4. Classify archetypes in parallel (10 workers)
    classified_profiles = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_classify_single_streamer_archetype, p, api_key, model)
            for p in raw_profiles
        ]
        for f in futures:
            try:
                res = f.result()
                if res:
                    classified_profiles.append(res)
            except Exception as e:
                logger.error(f"Daily Analytics: Classification task error: {e}")

    # Map back to raw_profiles
    raw_profiles = classified_profiles

    # 5. Compute peer correlations (in memory, fast)
    from ag_kaggle_5day.agents.advisor import calculate_similarity_nvar

    for p in raw_profiles:
        handle = p["streamer_handle"]
        scored_peers = []
        try:
            other_profiles = [x for x in raw_profiles if x["streamer_handle"] != handle]
            for op in other_profiles:
                score, metrics, why = calculate_similarity_nvar(p, op)
                scored_peers.append((op["streamer_handle"], score, why))

            scored_peers.sort(key=lambda x: x[1], reverse=True)
            p["peer_connections"] = [x[0] for x in scored_peers[:3]]
            p["peer_details"] = [
                {"handle": x[0], "similarity": round(x[1], 2), "why": x[2]}
                for x in scored_peers[:3]
            ]
        except Exception as e:
            logger.error(
                f"Daily Analytics: Failed to compute peers for '{handle}': {e}"
            )
            p["peer_connections"] = []
            p["peer_details"] = []

    # 6. Store profile fabrics in Firestore in parallel
    def _store_single_fabric(p: dict) -> None:
        handle = p["streamer_handle"]
        try:
            store_streamer_profile_fabric(handle, p)
        except Exception as store_err:
            logger.error(
                f"Daily Analytics: Failed to store fabric for '{handle}': {store_err}"
            )

    # Build pairwise similarities list to write to BQ
    pairs_to_store = []
    for i, p in enumerate(raw_profiles):
        handle = p["streamer_handle"]
        try:
            other_profiles = [x for x in raw_profiles if x["streamer_handle"] != handle]
            for op in other_profiles:
                score, metrics, why = calculate_similarity_nvar(p, op)
                if handle < op["streamer_handle"]:
                    pairs_to_store.append(
                        {
                            "streamer_a": handle,
                            "streamer_b": op["streamer_handle"],
                            "similarity_score": score,
                            "game_jaccard_overlap": metrics["jaccard_overlap"],
                            "engagement_density_diff": metrics[
                                "engagement_density_diff"
                            ],
                            "polarization_diff": metrics["polarization_diff"],
                            "why_explanation": why,
                        }
                    )
        except Exception as sim_err:
            logger.error(
                f"Daily Analytics: Failed to compute pair similarity: {sim_err}"
            )

    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(_store_single_fabric, raw_profiles)

    # 7. Write similarity matrix to BigQuery
    if pairs_to_store:
        try:
            from ag_kaggle_5day.agents.gcp_storage import (
                store_streamer_similarity_history,
            )

            store_streamer_similarity_history(pairs_to_store)
        except Exception as bq_err:
            logger.error(f"Failed to write similarity history to BQ: {bq_err}")

    # Pre-generate and cache category-specific comparison reports daily (disabled)
    logger.info(
        "Daily Analytics: Pre-generating category comparison reports is disabled."
    )

    # Record daily analytics execution time in system_cache
    try:
        from ag_kaggle_5day.agents.gcp_storage import store_app_cache_state

        store_app_cache_state("daily_analytics_status", {"last_run": time.time()})
        logger.info(
            "Daily Analytics: Successfully recorded "
            "daily_analytics_status in system_cache."
        )
    except Exception as cache_err:
        logger.error(
            f"Daily Analytics: Failed to record daily analytics status: {cache_err}"
        )

    logger.info("Daily analytics aggregation pipeline complete.")


def check_and_run_daily_analytics_if_stale(api_key: str) -> None:
    """Checks if daily analytics has been updated in the last 12 hours.
    If not, or if cache is missing, triggers the aggregation pipeline inline.
    """
    logger.info("Checking if daily streamer analytics cache is stale...")
    from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

    try:
        latest_ts = 0.0
        status = get_app_cache_state("daily_analytics_status")
        if status:
            latest_ts = status.get("last_run", 0.0)

        import time

        age = time.time() - latest_ts
        if age > 12 * 3600 or latest_ts == 0.0:
            logger.info(
                f"Daily analytics cache is stale (age: {age:.2f}s). "
                "Triggering aggregation..."
            )
            run_daily_analytics_aggregation(api_key)
        else:
            logger.info(
                f"Daily analytics cache is fresh (age: {age:.2f}s). Skipping trigger."
            )
    except Exception as e:
        logger.warning(
            "Error checking daily analytics freshness: "
            f"{e}. Running aggregation as fallback."
        )
        run_daily_analytics_aggregation(api_key)


def get_archetype_analytics() -> list[dict]:
    """Retrieves aggregate metrics grouped by streamer archetype from BQ/Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import get_archetype_analytics_from_db

    return get_archetype_analytics_from_db()


def get_game_sentiment_metrics(game_name: str = None) -> list[dict]:
    """Retrieves aggregate sentiment and velocity metrics for a game or

    top games from BQ/Firestore.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_game_sentiment_metrics_from_db

    return get_game_sentiment_metrics_from_db(game_name)
