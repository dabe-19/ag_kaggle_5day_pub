import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from typing import Optional

from ag_kaggle_5day.agents.scraper.chat import (
    deduplicate_chat_messages,
)
from ag_kaggle_5day.agents.scraper.feature_library import (
    negative_words_set,
    positive_words_set,
)
from ag_kaggle_5day.agents.scraper.steam import (
    get_steam_appid_by_name,
    get_steam_player_count,
)
from ag_kaggle_5day.agents.scraper.twitch import TwitchAPIClient

logger = logging.getLogger("streamer_advisor.scraper")

_sentinel_running = False
_sentinel_tasks: list[asyncio.Task] = []
_sentinel_boot_time: float = 0.0

# Memory buffers for lexicon and triggers
_rolling_windows: dict[
    str, deque[tuple[float, int]]
] = {}  # channel -> deque of (timestamp, score)
_message_rates: dict[str, deque[float]] = {}  # channel -> deque of message timestamps
_ring_buffers: dict[str, deque[str]] = {}  # channel -> deque of raw messages (last 150)
_last_highlight_time: dict[str, float] = {}  # channel -> last highlight timestamp
_channel_games: dict[str, str] = {}  # channel -> game name
_channel_archetypes: dict[str, str] = {}  # channel -> archetype cluster name
_channel_profiles_cache: dict[str, dict] = {}  # channel -> full profile dict
_channel_adaptive_metrics: dict[
    str, dict
] = {}  # channel -> adaptive metrics state dict
_channel_events: dict[str, list[dict]] = {}  # channel -> list of event dictionaries


def apply_adaptive_decay_filter(
    channel: str, new_obs: dict, current_time: float
) -> dict:
    """Applies a continuous-time first-order lag filter to raw metrics,

    using variable exponential decay based on delta time.
    """
    import math

    handle = channel.strip().lower()
    prior = _channel_adaptive_metrics.get(handle, {})

    # Time constants in seconds
    TAUS = {
        "msg_per_minute": 3 * 3600.0,  # 3 hours
        "chat_volatility": 6 * 3600.0,  # 6 hours
        "rolling_sentiment_score": 12 * 3600.0,  # 12 hours
        "viewer_count": 3 * 3600.0,  # 3 hours
    }

    updated_metrics = {}
    for metric, tau in TAUS.items():
        m_prior = prior.get(metric, {})
        state_val = float(m_prior.get("state_val", 0.0))
        state_ts = float(m_prior.get("state_ts", current_time))

        dt = max(0.0, current_time - state_ts)
        alpha = math.exp(-dt / tau)

        new_val = new_obs.get(metric)
        if new_val is not None:
            new_val = float(new_val)
            next_state_val = alpha * state_val + (1.0 - alpha) * new_val
            next_state_ts = current_time
            last_impulse = new_val
            last_impulse_ts = current_time
        else:
            if metric == "viewer_count":
                # Do not decay viewer count when it is absent from new observations
                next_state_val = state_val
                next_state_ts = state_ts
            else:
                # Decay towards 0.0 baseline
                next_state_val = alpha * state_val
                next_state_ts = current_time
            last_impulse = float(m_prior.get("last_impulse", 0.0))
            last_impulse_ts = float(m_prior.get("last_impulse_ts", current_time))

        updated_metrics[metric] = {
            "last_impulse": last_impulse,
            "last_impulse_ts": last_impulse_ts,
            "state_val": next_state_val,
            "state_ts": next_state_ts,
        }

    return updated_metrics


def get_current_decayed_state(channel: str, current_time: float) -> dict:
    """Computes the decayed metrics for a channel on-the-fly without

    modifying the stored state.
    """
    import math

    handle = channel.strip().lower()
    prior = _channel_adaptive_metrics.get(handle, {})
    TAUS = {
        "msg_per_minute": 3 * 3600.0,
        "chat_volatility": 6 * 3600.0,
        "rolling_sentiment_score": 12 * 3600.0,
        "viewer_count": 3 * 3600.0,
    }

    current_state = {}
    for metric, tau in TAUS.items():
        m_prior = prior.get(metric, {})
        state_val = float(m_prior.get("state_val", 0.0))
        state_ts = float(m_prior.get("state_ts", current_time))

        dt = max(0.0, current_time - state_ts)
        alpha = math.exp(-dt / tau)

        if metric == "viewer_count":
            current_state[metric] = state_val
        else:
            current_state[metric] = alpha * state_val

    return current_state


def _calculate_volatility_and_mean(scores: list[int]) -> tuple[float, float]:
    """Calculates mean sentiment (mu) and standard deviation (sigma) of scores."""
    if not scores:
        return 0.0, 0.0
    mu = sum(scores) / len(scores)
    variance = sum((s - mu) ** 2 for s in scores) / len(scores)
    sigma = variance**0.5
    return round(mu, 3), round(sigma, 3)


def store_streamer_moment_sync(
    channel: str,
    game_name: str,
    trigger_type: str,
    trigger_value: float,
    mpm: float,
    summary: str,
    messages: Optional[list[str]] = None,
) -> None:
    from ag_kaggle_5day.agents.gcp_storage import store_streamer_sentiment_moment

    store_streamer_sentiment_moment(
        channel,
        game_name,
        trigger_type,
        trigger_value,
        mpm,
        "Neutral",
        summary,
        messages,
    )


async def _record_trigger_moment_async(
    channel: str,
    game_name: str,
    trigger_type: str,
    trigger_value: float,
    mpm: float,
    mu: float,
    sigma: float,
    now: float,
) -> None:
    import asyncio

    from ag_kaggle_5day.agents.gcp_storage import (
        store_streamer_sentiment,
        update_streamer_adaptive_metrics,
    )

    # Retrieve and deduplicate recent chat messages to log chat content
    buffer = list(_ring_buffers.get(channel, []))
    from ag_kaggle_5day.agents.scraper import deduplicate_chat_messages

    deduped = deduplicate_chat_messages(buffer)
    chat_snippet = deduped[:15]

    # 1. Log raw moment to BigQuery/Firestore moments collection (non-blocking)
    try:
        loop = asyncio.get_running_loop()
        summary = (
            f"Spike event ({trigger_type}) detected with chat speed at "
            f"{mpm:.1f} msg/min."
        )
        await loop.run_in_executor(
            None,
            store_streamer_moment_sync,
            channel,
            game_name,
            trigger_type,
            trigger_value,
            mpm,
            summary,
            chat_snippet,
        )
    except Exception as e:
        logger.error(f"Error logging raw moment async: {e}")

    # 2. Update intermediate numeric metrics in Firestore cache (non-blocking)
    try:
        vibe_str = "Neutral"
        if mu > 0.2:
            vibe_str = "Positive"
        elif mu < -0.2:
            vibe_str = "Negative"

        # Apply continuous lag decay filter
        new_obs = {
            "msg_per_minute": mpm,
            "chat_volatility": sigma,
            "rolling_sentiment_score": mu,
        }
        updated_adaptive = apply_adaptive_decay_filter(channel, new_obs, now)
        _channel_adaptive_metrics[channel.strip().lower()] = updated_adaptive

        res_data = {
            "total_messages": len(buffer),
            "msg_per_minute": mpm,
            "sentiment": vibe_str,
            "messages": deduped[:50],
            "game_name": game_name,
            "chat_volatility": sigma,
            "rolling_sentiment_score": mu,
            "last_highlight": {
                "timestamp": now,
                "summary": f"Spike event ({trigger_type}) detected.",
                "trigger_type": trigger_type,
            },
            "adaptive_metrics": updated_adaptive,
        }

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, store_streamer_sentiment, channel, res_data, "sentinel_realtime"
        )
        await loop.run_in_executor(
            None, update_streamer_adaptive_metrics, channel, updated_adaptive
        )
    except Exception as e:
        logger.error(f"Error updating intermediate telemetry: {e}")


def _process_sentinel_message(
    channel: str,
    msg: str,
    key: str,
    timestamp: Optional[float] = None,
    tags: Optional[dict] = None,
) -> None:
    """Processes an incoming IRC chat message, updating rolling stats and

    checking triggers.
    """
    from collections import deque

    now = timestamp if timestamp is not None else time.time()

    # 1. Update ring buffer
    if channel not in _ring_buffers:
        _ring_buffers[channel] = deque(maxlen=150)
    _ring_buffers[channel].append(msg)

    # 2. Update message velocity
    if channel not in _message_rates:
        _message_rates[channel] = deque()
    _message_rates[channel].append(now)

    # Cleanup old message rates (> 60 seconds)
    while _message_rates[channel] and now - _message_rates[channel][0] > 60.0:
        _message_rates[channel].popleft()

    # 3. Calculate score locally
    score = 0
    msg_lower = msg.lower()

    # Word matching
    for w in positive_words_set:
        if w in msg_lower:
            score += 1
    for w in negative_words_set:
        if w in msg_lower:
            score -= 1

    # Import unified emojis and emotes from feature library
    from ag_kaggle_5day.agents.scraper.feature_library import (
        negative_emojis,
        negative_emotes_set,
        positive_emojis,
        positive_emotes_set,
    )

    for char in msg:
        if char in positive_emojis:
            score += 1
        elif char in negative_emojis:
            score -= 1

    emotes_str = tags.get("emotes") if tags else None
    if emotes_str and emotes_str.strip():
        for entry in emotes_str.split("/"):
            if ":" in entry:
                emote_id, ranges_str = entry.split(":", 1)
                first_range = ranges_str.split(",")[0]
                if "-" in first_range:
                    try:
                        start_idx, end_idx = map(int, first_range.split("-"))
                        if 0 <= start_idx <= end_idx < len(msg):
                            emote_name = msg[start_idx : end_idx + 1].lower()
                            if emote_name in positive_emotes_set:
                                score += 2  # Higher weight for express emotes
                            elif emote_name in negative_emotes_set:
                                score -= 2
                    except Exception:
                        pass

    # Clip score to -1, 0, 1
    if score > 0:
        score = 1
    elif score < 0:
        score = -1

    if channel not in _rolling_windows:
        _rolling_windows[channel] = deque()
    _rolling_windows[channel].append((now, score))

    # Cleanup old rolling scores (> 180 seconds)
    while _rolling_windows[channel] and now - _rolling_windows[channel][0][0] > 180.0:
        _rolling_windows[channel].popleft()

    # 4. Calculate rolling stats
    mpm = len(_message_rates[channel])
    scores = [s for _, s in _rolling_windows[channel]]
    mu, sigma = _calculate_volatility_and_mean(scores)

    # 5. Dynamic Trigger Check
    # Avoid spamming trigger updates: cool-down of 5 minutes (300s)
    last_trigger = _last_highlight_time.get(channel, 0)
    if now - last_trigger < 180.0:
        return

    # Avoid triggers during the first 60 seconds of Sentinel boot (warm-up phase)
    if time.time() - _sentinel_boot_time < 60.0:
        return

    # 1. Load profile from cache or default values
    profile = _channel_profiles_cache.get(channel, {})
    if not profile and channel.lower().startswith("uc"):
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(channel)
            if link_info:
                twitch_handle = link_info.get("twitch_handle")
                if twitch_handle:
                    profile = _channel_profiles_cache.get(
                        twitch_handle.strip().lower(), {}
                    )
                    if profile:
                        _channel_profiles_cache[channel] = profile
        except Exception:
            pass

    # 2. Extract baseline stats
    baseline_mpm = profile.get("average_msg_per_minute", 10.0)
    std_mpm = profile.get("std_msg_per_minute", 3.0)
    baseline_vol = profile.get("average_chat_volatility", 0.5)
    std_vol = profile.get("std_chat_volatility", 0.15)

    # 3. Establish statistical thresholds
    # Volume spike threshold: 3-sigma above baseline (min 1.5x baseline)
    mpm_threshold = max(baseline_mpm * 1.5, baseline_mpm + 3 * std_mpm)

    # Vibe shift threshold: 2-sigma above baseline (clamped between 0.4 and 0.9)
    vol_threshold = max(0.4, min(0.9, baseline_vol + 2 * std_vol))

    # Check trigger conditions
    triggered = False
    trigger_type = ""
    trigger_value = 0.0

    # Trigger 1: Volume Spike
    if mpm > mpm_threshold:
        triggered = True
        trigger_type = "VOLUME_SPIKE"
        trigger_value = mpm

    # Trigger 2: Vibe Shift (Polarization)
    if not triggered and sigma > vol_threshold and len(scores) >= 15:
        triggered = True
        trigger_type = "VIBE_SHIFT"
        trigger_value = sigma

    if triggered:
        _last_highlight_time[channel] = now
        game_name = _channel_games.get(channel, "Unknown")

        # Buffer event details in memory for final end-of-run LLM synthesis
        buffer = list(_ring_buffers.get(channel, []))
        from ag_kaggle_5day.agents.scraper import deduplicate_chat_messages

        deduped = deduplicate_chat_messages(buffer)

        if channel not in _channel_events:
            _channel_events[channel] = []
        _channel_events[channel].append(
            {
                "timestamp": now,
                "trigger_type": trigger_type,
                "mpm": mpm,
                "mu": mu,
                "sigma": sigma,
                "chat_snippet": deduped[:15],
            }
        )

        # Spawn background task to log moment and update numeric metrics
        # in Firestore asynchronously
        asyncio.create_task(
            _record_trigger_moment_async(
                channel, game_name, trigger_type, trigger_value, mpm, mu, sigma, now
            )
        )


def _process_sentinel_usernotice(line: str, key: str) -> None:
    """Parses Twitch USERNOTICE to detect raid events and trigger summaries."""
    if "msg-id=raid" not in line:
        return

    try:
        # Extract raider, target, and viewer count from notice tags
        # e.g., @msg-id=raid;msg-param-displayName=RaiderName;
        # msg-param-viewerCount=120 USERNOTICE #targetchannel
        raider = "unknown_raider"
        viewer_count = 0
        target = "unknown_target"

        tags_part = line.split(" USERNOTICE #", 1)
        if len(tags_part) == 2:
            target = tags_part[1].strip().lower()
            tags = tags_part[0].split(";")
            for t in tags:
                if t.startswith("msg-param-displayName="):
                    raider = t.split("=", 1)[1].strip().lower()
                elif t.startswith("msg-param-viewerCount="):
                    viewer_count = int(t.split("=", 1)[1].strip())

        logger.info(
            "RaidSentinel: Detected incoming raid: "
            f"{raider} -> {target} ({viewer_count} viewers)"
        )

        # Save raid history to BigQuery
        try:
            from ag_kaggle_5day.agents.gcp_storage import store_streamer_raid_event

            store_streamer_raid_event(raider, target, viewer_count)
        except Exception as bq_err:
            logger.error(f"Failed to log raid event in BigQuery: {bq_err}")

        # Trigger RAID highlight for target channel
        now = time.time()
        _last_highlight_time[target] = now
        game_name = _channel_games.get(target, "Unknown")
        mpm = len(_message_rates.get(target, []))
        scores = [s for _, s in _rolling_windows.get(target, [])]
        mu, sigma = _calculate_volatility_and_mean(scores)

        # Buffer event details in memory for final end-of-run LLM synthesis
        buffer = list(_ring_buffers.get(target, []))
        from ag_kaggle_5day.agents.scraper import deduplicate_chat_messages

        deduped = deduplicate_chat_messages(buffer)

        if target not in _channel_events:
            _channel_events[target] = []
        _channel_events[target].append(
            {
                "timestamp": now,
                "trigger_type": f"RAID (Raider: {raider}, Viewers: {viewer_count})",
                "mpm": mpm,
                "mu": mu,
                "sigma": sigma,
                "chat_snippet": deduped[:15],
            }
        )

        # Spawn background task to log moment and update numeric metrics
        # in Firestore asynchronously
        asyncio.create_task(
            _record_trigger_moment_async(
                target, game_name, "RAID", float(viewer_count), mpm, mu, sigma, now
            )
        )
    except Exception as e:
        logger.error(f"Error parsing raid notice: {e}", exc_info=True)


async def _compile_and_store_moment(
    channel: str,
    game_name: str,
    trigger_type: str,
    trigger_value: float,
    mpm: float,
    mu: float,
    sigma: float,
    key: str,
    reason: str = None,
) -> None:
    """Async task that deduplicates ring buffer chat logs, runs LLM

    synthesis, and saves the moment highlight.
    """
    try:
        buffer = list(_ring_buffers.get(channel, []))
        if not buffer:
            return

        # Deduplicate chat logs
        deduped = deduplicate_chat_messages(buffer)
        transcript_text = "\n".join(f"- {m}" for m in deduped[:50])

        vibe_str = "Neutral"
        if mu > 0.2:
            vibe_str = "Positive"
        elif mu < -0.2:
            vibe_str = "Negative"

        # Build prompt
        context = (
            f"Streamer: {channel} | Game: {game_name}\n"
            f"Trigger Event: {trigger_type} ({trigger_value})\n"
            f"Vibe Coordinates: Sentiment = {mu}, Volatility = {sigma} ({vibe_str})\n"
            f"Average Velocity: {mpm} messages/min\n"
        )
        if reason:
            context += f"Context: {reason}\n"

        prompt = (
            f"Analyze this short Twitch chat snippet during a highlight event. "
            f"Generate a single, concise (exactly one sentence) summary describing "
            f"what the viewers are reacting to or what just happened on stream.\n\n"
            f"{context}\nChat Snippet:\n{transcript_text}\n\n"
            "Highlight Summary:"
        )

        summary = ""
        if key:
            try:
                from ag_kaggle_5day.agents.scraper import safe_generate_content

                res = safe_generate_content(
                    api_key=key,
                    model="gemma-4-31b-it",
                    contents=prompt,
                    system_instruction=(
                        "You are a stream highlight describer. "
                        "Output only the summarized highlight sentence."
                    ),
                    chain_name="sentiment",
                )
                summary = res.text.strip()
            except Exception as llm_err:
                logger.warning(
                    f"Failed to generate highlight summary for '{channel}': {llm_err}"
                )
                summary = (
                    f"Spike event ({trigger_type}) detected with chat speed "
                    f"at {mpm} msg/min."
                )

        # Save to BQ & Firestore moments collection
        from ag_kaggle_5day.agents.gcp_storage import (
            store_streamer_profile_fabric,
            store_streamer_sentiment,
            store_streamer_sentiment_moment,
        )

        # If no profile exists for this streamer (cache miss), trigger
        # initial preliminary profile creation in Firestore
        if channel not in _channel_archetypes:
            try:
                loop = asyncio.get_running_loop()
                # Use run_in_executor to avoid blocking the loop
                await loop.run_in_executor(
                    None,
                    store_streamer_profile_fabric,
                    channel,
                    {
                        "archetype_cluster": "Cozy_Social_Interactive",
                        "fabric_status": "preliminary",
                        "primary_game": game_name,
                    },
                )
                _channel_archetypes[channel] = "Cozy_Social_Interactive"
                logger.info(
                    "RaidSentinel: Created initial preliminary profile for "
                    f"discovered streamer '{channel}'"
                )
            except Exception as p_err:
                logger.warning(
                    "RaidSentinel: Failed to create preliminary profile "
                    f"for discovered streamer '{channel}': {p_err}"
                )

        store_streamer_sentiment_moment(
            channel, game_name, trigger_type, trigger_value, mpm, vibe_str, summary
        )

        # Update streamer_sentiment document's last_highlight in Firestore
        res_data = {
            "total_messages": len(buffer),
            "msg_per_minute": mpm,
            "sentiment": vibe_str,
            "messages": deduped[:50],
            "summary": summary,
            "game_name": game_name,
            "chat_volatility": sigma,
            "rolling_sentiment_score": mu,
            "last_highlight": {
                "timestamp": time.time(),
                "summary": summary,
                "trigger_type": trigger_type,
            },
        }
        # Compute and write adaptive metrics
        new_obs = {
            "msg_per_minute": mpm,
            "chat_volatility": sigma,
            "rolling_sentiment_score": mu,
        }
        updated_adaptive = apply_adaptive_decay_filter(channel, new_obs, time.time())
        _channel_adaptive_metrics[channel] = updated_adaptive
        res_data["adaptive_metrics"] = updated_adaptive

        # Update cache doc
        store_streamer_sentiment(channel, res_data, "sentinel_realtime")

        # Sync to Firestore profile fabric
        from ag_kaggle_5day.agents.gcp_storage import update_streamer_adaptive_metrics

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, update_streamer_adaptive_metrics, channel, updated_adaptive
            )
        except Exception as p_err:
            logger.warning(
                f"RaidSentinel: Failed to update adaptive metrics in Firestore: {p_err}"
            )

    except Exception as e:
        logger.error(
            f"Error compiling highlight moment for '{channel}': {e}", exc_info=True
        )


async def _run_sentinel_connection(pool: list[str], key: str):
    """Manages a single persistent SSL Twitch IRC connection for a

    sharded channel pool.
    """
    import asyncio

    # Store online streams metadata for game resolution
    twitch_client = TwitchAPIClient()
    if twitch_client.is_configured:
        try:
            streams = twitch_client.get_online_streams(pool)
            for s in streams:
                login = s.get("user_login").lower()
                game = s.get("game_name", "Unknown")
                _channel_games[login] = game
        except Exception as e:
            logger.warning(
                f"RaidSentinel: Failed to preload channel games metadata: {e}"
            )

    while _sentinel_running:
        writer = None
        try:
            reader, writer = await asyncio.open_connection(
                "irc.chat.twitch.tv", 6697, ssl=True
            )

            anon_nick = f"justinfan{random.randint(10000, 99999)}"
            writer.write("PASS oauth:dummy\r\n".encode("utf-8"))
            writer.write(f"NICK {anon_nick}\r\n".encode("utf-8"))
            writer.write(
                (
                    "CAP REQ :twitch.tv/tags twitch.tv/commands "
                    "twitch.tv/membership\r\n"
                ).encode("utf-8")
            )
            await writer.drain()

            # Join multiple channels in comma separated list
            channels_str = ",".join(f"#{ch.lower().strip()}" for ch in pool)
            writer.write(f"JOIN {channels_str}\r\n".encode("utf-8"))
            await writer.drain()

            logger.info(
                f"RaidSentinel: Joined sharded channel pool of size {len(pool)}"
            )

            while _sentinel_running:
                try:
                    line_bytes = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="ignore").strip()

                    if line.startswith("PING"):
                        writer.write("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                        await writer.drain()
                    elif "PRIVMSG" in line:
                        tags = {}
                        if line.startswith("@"):
                            tags_str, rest = line.split(" :", 1)
                            for tag in tags_str[1:].split(";"):
                                if "=" in tag:
                                    k, v = tag.split("=", 1)
                                    tags[k] = v
                            line_to_split = rest
                        else:
                            line_to_split = line

                        parts = line_to_split.split(" PRIVMSG #", 1)
                        if len(parts) == 2:
                            chan_part, msg_part = parts[1].split(" :", 1)
                            channel = chan_part.strip().lower()
                            msg = msg_part.strip()
                            _process_sentinel_message(channel, msg, key, tags=tags)
                    elif "USERNOTICE" in line:
                        _process_sentinel_usernotice(line, key)
                except asyncio.TimeoutError:
                    continue
                except Exception as read_err:
                    logger.warning(f"RaidSentinel: IRC socket closed/error: {read_err}")
                    break
        except Exception as conn_err:
            logger.warning(
                f"RaidSentinel: IRC connection lost: {conn_err}. Reconnecting in 5s..."
            )
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                raise
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await asyncio.shield(writer.wait_closed())
                except Exception:
                    pass


def get_active_sentinel_channels(fs_client=None) -> list[str]:
    """
    Finds unique candidate streamers and applies cohort rules (Tier 1, 2, 3)
    to select the top 100 prioritized channels.
    """
    all_candidates = set()
    try:
        from ag_kaggle_5day.agents.advisor import get_unique_streamer_handles

        for h in get_unique_streamer_handles():
            if h:
                h_stripped = h.strip()
                if h_stripped.lower().startswith("uc"):
                    all_candidates.add(h_stripped)
                else:
                    all_candidates.add(h_stripped.lower())
    except Exception as e:
        logger.warning(
            "get_active_sentinel_channels: Failed to fetch unique "
            f"streamer handles: {e}"
        )

    online_info = {}
    cached_games = []
    try:
        from ag_kaggle_5day.agents.advisor import get_cached_games

        cached_games = get_cached_games() or []
        for idx, game in enumerate(cached_games):
            is_dashboard = idx < 15
            top_s = game.get("top_streamers", [])
            for s in top_s:
                login = s.get("user_login")
                if login:
                    login_stripped = login.strip()
                    if (
                        login_stripped.lower().startswith("uc")
                        or s.get("platform") == "youtube"
                    ):
                        login_clean = login_stripped
                    else:
                        login_clean = login_stripped.lower()
                    viewers = int(s.get("viewer_count") or 0)
                    online_info[login_clean] = {
                        "viewers": viewers,
                        "game": game.get("title", "Unknown"),
                        "is_dashboard": is_dashboard,
                    }
                    all_candidates.add(login_clean)
    except Exception as e:
        logger.warning(
            "get_active_sentinel_channels: Failed to resolve online "
            f"streamers from cache: {e}"
        )

    historical_volatilities = {}
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = fs_client or get_firestore_client()
        if fs:
            docs = fs.collection("streamer_sentiment").stream()
            for doc in docs:
                d = doc.to_dict()
                h_id = doc.id
                historical_volatilities[h_id.strip().lower()] = d.get(
                    "chat_volatility", 0.0
                )
    except Exception as e:
        logger.warning(
            "get_active_sentinel_channels: Failed to stream "
            f"historical volatilities: {e}"
        )

    # Filter out unlinked YouTube channel IDs from candidate pool
    from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

    filtered_candidates = set()
    for cand in all_candidates:
        if cand.lower().startswith("uc"):
            if resolve_streamer_link(cand, fs):
                filtered_candidates.add(cand)
            else:
                logger.debug(
                    "get_active_sentinel_channels: Filtered out unlinked "
                    f"YouTube candidate '{cand}'"
                )
        else:
            filtered_candidates.add(cand)

    tier1 = []
    tier2 = []
    tier3 = []

    for cand in filtered_candidates:
        if cand in online_info:
            info = online_info[cand]
            if info["is_dashboard"]:
                tier1.append((cand, info["viewers"]))
            else:
                tier2.append((cand, info["viewers"]))

        vol = historical_volatilities.get(cand.lower(), 0.0)
        tier3.append((cand, vol))

    tier1.sort(key=lambda x: x[1], reverse=True)
    tier2.sort(key=lambda x: x[1], reverse=True)
    tier3.sort(key=lambda x: x[1], reverse=True)

    tier1_handles = [x[0] for x in tier1]
    tier2_handles = [x[0] for x in tier2]
    tier3_handles = [x[0] for x in tier3]

    selected = []
    selected.extend(tier1_handles[:50])
    selected.extend(tier2_handles[:30])

    t3_candidates = [h for h in tier3_handles if h not in selected]
    selected.extend(t3_candidates[:20])

    remaining_all = (
        [h for h in tier1_handles if h not in selected]
        + [h for h in tier2_handles if h not in selected]
        + [h for h in tier3_handles if h not in selected]
        + [h for h in filtered_candidates if h not in selected]
    )
    selected.extend(remaining_all)
    selected = list(dict.fromkeys(selected))[:100]
    return selected


def get_youtube_channel_live_video_id(channel_id: str) -> Optional[str]:
    import re

    import requests

    cid = channel_id.strip().lstrip("@")

    # Heal case-preserved channel ID using Firestore cache if available
    if cid.lower().startswith("uc") and len(cid) == 24 and cid.lower() == cid:
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
            logger.warning(
                f"YouTube: Failed to heal channel ID {cid} in live check: {e}"
            )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # 1. Try `/streams` tab HTML scraping first (more reliable for finding active live
    # stream with watching count)
    try:
        streams_url = f"https://www.youtube.com/channel/{cid}/streams"
        resp = requests.get(streams_url, headers=headers, timeout=5)
        import json

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
                        data, _ = json.JSONDecoder().raw_decode(resp.text[start_brace:])
                        break
                    except Exception:
                        pass
        if data:
            vids = []

            def find_lockups(obj):
                if isinstance(obj, dict):
                    if "lockupViewModel" in obj:
                        vm = obj["lockupViewModel"]
                        vid = None
                        try:
                            vid = vm["rendererContext"]["commandContext"]["onTap"][
                                "innertubeCommand"
                            ]["watchEndpoint"]["videoId"]
                        except KeyError:
                            pass
                        is_live = False
                        try:
                            metadata_rows = vm["metadata"]["lockupMetadataViewModel"][
                                "metadata"
                            ]["contentMetadataViewModel"]["metadataRows"]
                            for row in metadata_rows:
                                for part in row.get("metadataParts", []):
                                    text = part.get("text", {}).get("content", "")
                                    if "watching" in text.lower():
                                        is_live = True
                        except KeyError:
                            pass
                        if vid and is_live:
                            vids.append(vid)
                    for k, v in obj.items():
                        find_lockups(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_lockups(item)

            find_lockups(data)
            if vids:
                logger.info(
                    "YouTube Watch ID: Found active streams from "
                    f"`/streams` tab. Selected {vids[0]}."
                )
                return vids[0]
    except Exception as e:
        logger.warning(f"YouTube Watch ID: `/streams` tab scraping exception: {e}")

    # 1b. Fall back to `/live` page redirect if `/streams` tab didn't yield an active
    # stream
    url = f"https://www.youtube.com/channel/{cid}/live"
    try:
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        # Check for live stream indicators on the page
        # require "isLive":true or the isLiveBroadcast content=True meta tag to exclude
        # upcoming or archived streams
        is_live = (
            '"isLive":true' in resp.text
            or 'itemprop="isLiveBroadcast" content="True"' in resp.text
            or 'itemprop="isLiveBroadcast" content="true"' in resp.text
        )

        if is_live:
            # Try redirect URL
            if "watch?v=" in resp.url:
                match = re.search(r"v=([a-zA-Z0-9_-]{11})", resp.url)
                if match:
                    return match.group(1)

            # Try parsing canonical link in response text
            match = re.search(
                r'<link\s+rel=["\']canonical["\']\s+href=["\'][^"\']*watch\?v=([a-zA-Z0-9_-]{11})["\']',
                resp.text,
            )
            if match:
                return match.group(1)

            # Fallback to any watch?v= or videoId match
            match = re.search(r"\"videoId\"\:\"([a-zA-Z0-9_-]{11})\"", resp.text)
            if match:
                return match.group(1)
    except Exception:
        pass

    # 2. Try official YouTube Search API as a backup if API key is present
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        try:
            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "channelId": cid,
                "type": "video",
                "eventType": "live",
                "key": api_key,
            }
            resp = requests.get(search_url, params=params, timeout=5)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    video_id = items[0].get("id", {}).get("videoId")
                    if video_id:
                        return video_id
        except Exception:
            pass

    return None


def _scrape_youtube_live_chat(video_id: str) -> list[dict]:
    import os
    import time

    import requests

    # 1. Try HTML scraping first (0 quota cost, no API limits)
    url = f"https://www.youtube.com/live_chat?v={video_id}&cache_buster={time.time()}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        logger.info(
            "YouTube Chat Scraper: HTML request for video "
            f"{video_id} completed. Status={resp.status_code}, "
            f"URL={resp.url}"
        )

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
                        data, _ = json.JSONDecoder().raw_decode(resp.text[start_brace:])
                        break
                    except Exception as e:
                        logger.warning(
                            f"YouTube Chat Scraper: Failed to decode json brace: {e}"
                        )
        if data:
            # Check if chat is disabled
            if "contents" in data and "messageRenderer" in data["contents"]:
                renderer = data["contents"]["messageRenderer"]
                text_runs = renderer.get("text", {}).get("runs", [{}])
                text = text_runs[0].get("text", "") if text_runs else ""
                if "Chat is disabled" in text:
                    logger.warning(
                        f"YouTube Chat Scraper: Chat is disabled for video {video_id}."
                    )
                    import time

                    return [
                        {
                            "author": "SYSTEM",
                            "message": "Chat is disabled for this YouTube live stream.",
                            "timestamp": time.time(),
                        }
                    ]

            messages = []

            def find_chat_messages(obj):
                if isinstance(obj, dict):
                    if "liveChatTextMessageRenderer" in obj:
                        r = obj["liveChatTextMessageRenderer"]
                        author = r.get("authorName", {}).get("simpleText", "Unknown")
                        message_runs = r.get("message", {}).get("runs", [])
                        message_text = "".join(
                            run.get("text", "") for run in message_runs
                        )
                        timestamp_usec = r.get("timestampUsec", "0")
                        messages.append(
                            {
                                "author": author,
                                "message": message_text,
                                "timestamp": int(timestamp_usec) / 1000000,
                            }
                        )
                    for k, v in obj.items():
                        find_chat_messages(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_chat_messages(item)

            find_chat_messages(data)
            if messages:
                logger.info(
                    "YouTube Chat Scraper: Successfully parsed "
                    f"{len(messages)} messages via HTML."
                )
                return messages
            else:
                logger.warning(
                    "YouTube Chat Scraper: HTML parsed successfully "
                    "but found 0 chat messages."
                )
        else:
            logger.warning(
                "YouTube Chat Scraper: HTML scrape failed to find "
                f"ytInitialData marker. Body length={len(resp.text)}"
            )
    except Exception as e:
        logger.warning(f"YouTube Chat Scraper: HTML scrape exception: {e}")

    # 2. Try official YouTube liveChatMessages API as a backup if API key is present
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        logger.info(
            "YouTube Chat Scraper: Falling back to official YouTube "
            f"API for video {video_id}"
        )
        try:
            # Fetch activeLiveChatId from video details
            vid_url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "liveStreamingDetails",
                "id": video_id,
                "key": api_key,
            }
            v_resp = requests.get(vid_url, params=params, timeout=5)
            logger.info(
                f"YouTube Chat Scraper: API videos response status={v_resp.status_code}"
            )
            if v_resp.status_code == 200:
                items = v_resp.json().get("items", [])
                if items:
                    chat_id = (
                        items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
                    )
                    logger.info(f"YouTube Chat Scraper: API resolved chat_id={chat_id}")
                    if chat_id:
                        # Fetch live chat messages
                        msg_url = (
                            "https://www.googleapis.com/youtube/v3/liveChat/messages"
                        )
                        msg_params = {
                            "liveChatId": chat_id,
                            "part": "snippet,authorDetails",
                            "maxResults": 100,
                            "key": api_key,
                        }
                        m_resp = requests.get(msg_url, params=msg_params, timeout=5)
                        logger.info(
                            "YouTube Chat Scraper: API liveChatMessages "
                            f"status={m_resp.status_code}"
                        )
                        if m_resp.status_code == 200:
                            m_items = m_resp.json().get("items", [])
                            messages = []
                            for item in m_items:
                                snippet = item.get("snippet", {})
                                author = item.get("authorDetails", {}).get(
                                    "displayName", "Unknown"
                                )
                                message_text = snippet.get("displayMessage", "")
                                pub_at = snippet.get("publishedAt", "")
                                import datetime

                                try:
                                    dt = datetime.datetime.fromisoformat(
                                        pub_at.replace("Z", "+00:00")
                                    )
                                    ts = dt.timestamp()
                                except Exception:
                                    import time

                                    ts = time.time()
                                messages.append(
                                    {
                                        "author": author,
                                        "message": message_text,
                                        "timestamp": ts,
                                    }
                                )
                            logger.info(
                                "YouTube Chat Scraper: API successfully "
                                f"retrieved {len(messages)} messages."
                            )
                            return messages
                        else:
                            logger.warning(
                                "YouTube Chat Scraper: API liveChatMessages "
                                f"request failed. Body={m_resp.text}"
                            )
                else:
                    logger.warning(
                        "YouTube Chat Scraper: API videos returned empty "
                        f"items for video {video_id}. Body={v_resp.text}"
                    )
            else:
                logger.warning(
                    "YouTube Chat Scraper: API videos request failed. "
                    f"Body={v_resp.text}"
                )
        except Exception as e:
            logger.error(f"YouTube Chat Scraper: API fallback exception: {e}")

    return []


async def _run_youtube_sentinel_connection(pool: list[str], key: str):
    logger.info(f"RaidSentinel: Launched YouTube Sentinel for {len(pool)} channels")
    active_streams = {}
    loop = asyncio.get_running_loop()

    while _sentinel_running:
        for channel in pool:
            if not _sentinel_running:
                break

            actual_channel_id = channel
            target_handle = channel
            try:
                from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

                link_info = await loop.run_in_executor(
                    None, resolve_streamer_link, channel
                )
                if link_info:
                    yt_id = link_info.get("youtube_channel_id")
                    if yt_id:
                        actual_channel_id = yt_id

                    twitch_handle = link_info.get("twitch_handle")
                    if twitch_handle:
                        target_handle = twitch_handle.strip().lower()
            except Exception as e:
                logger.warning(
                    "YouTube Sentinel: Failed to resolve link details "
                    f"for '{channel}': {e}"
                )

            import time

            now = time.time()
            cached_stream = active_streams.get(channel)
            if (
                cached_stream
                and now - cached_stream.get("last_resolved_time", 0) < 300.0
            ):
                video_id = cached_stream["video_id"]
            else:
                video_id = await loop.run_in_executor(
                    None, get_youtube_channel_live_video_id, actual_channel_id
                )
                if cached_stream:
                    cached_stream["video_id"] = video_id
                    cached_stream["last_resolved_time"] = now
                else:
                    active_streams[channel] = {
                        "video_id": video_id,
                        "last_resolved_time": now,
                        "seen_message_signatures": set(),
                    }

            if not video_id:
                await asyncio.sleep(0.5)
                continue

            stream_state = active_streams[channel]
            new_msgs = await loop.run_in_executor(
                None, _scrape_youtube_live_chat, video_id
            )

            # Copy active game name (e.g. from Twitch if linked, or default to YouTube
            # Live)
            if target_handle in _channel_games:
                _channel_games[target_handle] = _channel_games[target_handle]
            elif channel in _channel_games:
                _channel_games[target_handle] = _channel_games[channel]
            else:
                _channel_games[target_handle] = "YouTube Live"

            for m in new_msgs:
                msg_sig = f"{m['author']}:{m['timestamp']}:{m['message'][:20]}"
                if msg_sig not in stream_state["seen_message_signatures"]:
                    stream_state["seen_message_signatures"].add(msg_sig)
                    _process_sentinel_message(
                        target_handle, m["message"], key, timestamp=m.get("timestamp")
                    )

            if len(stream_state["seen_message_signatures"]) > 200:
                stream_state["seen_message_signatures"] = set(
                    list(stream_state["seen_message_signatures"])[-100:]
                )

            await asyncio.sleep(1.0)

        for _ in range(10):
            if not _sentinel_running:
                break
            await asyncio.sleep(1.0)


async def start_raid_sentinel(key: str) -> None:
    """Starts the RaidSentinel async background listener, sharding top
    100 Twitch/YouTube streamers.
    """
    global _sentinel_running, _sentinel_tasks, _sentinel_boot_time
    import asyncio
    import time

    if _sentinel_running:
        logger.info("RaidSentinel: Already running. Skipping start.")
        return

    _sentinel_running = True
    _sentinel_tasks = []
    _sentinel_boot_time = time.time()

    # Pre-populate profiles/archetypes from Firestore
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if fs:
            docs = fs.collection("streamer_profiles").stream()
            for doc in docs:
                d = doc.to_dict()
                h_id = doc.id.strip().lower()
                _channel_profiles_cache[h_id] = d
                arch = d.get("archetype_cluster")
                if arch:
                    _channel_archetypes[h_id] = arch
                ad_m = d.get("adaptive_metrics")
                if ad_m:
                    _channel_adaptive_metrics[h_id] = ad_m
            logger.info(
                f"RaidSentinel: Pre-populated {len(_channel_profiles_cache)} "
                f"profiles, {len(_channel_archetypes)} archetypes and "
                f"{len(_channel_adaptive_metrics)} adaptive metrics from "
                "Firestore."
            )

            # Pre-populate streamer links cache
            try:
                from ag_kaggle_5day.agents.gcp_storage import (
                    prepopulate_streamer_links_cache,
                )

                prepopulate_streamer_links_cache(fs)
            except Exception as link_err:
                logger.warning(
                    f"RaidSentinel: Failed to pre-populate links cache: {link_err}"
                )
    except Exception as e:
        logger.warning(f"RaidSentinel: Failed to stream streamer profiles: {e}")

    handles = get_active_sentinel_channels(fs)
    logger.info(f"RaidSentinel: Selected active channels: {handles}")

    # Pre-resolve all active channel links to ensure they are memoized before
    # processing starts
    for h in handles:
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            resolve_streamer_link(h, fs)
        except Exception as pre_resolve_err:
            logger.warning(
                "RaidSentinel: Failed to pre-resolve links for "
                f"'{h}': {pre_resolve_err}"
            )

    youtube_handles = [h for h in handles if h.lower().startswith("uc")]
    twitch_handles = [h for h in handles if not h.lower().startswith("uc")]

    # 2. Shard Twitch channels across 2 pools (up to 50 channels each)
    chunk_size = (len(twitch_handles) + 1) // 2
    pool_a = twitch_handles[:chunk_size]
    pool_b = twitch_handles[chunk_size:]

    logger.info(
        "RaidSentinel: Launching Sentinel with sharded Twitch pools: "
        f"Pool A={len(pool_a)}, Pool B={len(pool_b)} | "
        f"YouTube channels={len(youtube_handles)}"
    )

    if pool_a:
        _sentinel_tasks.append(
            asyncio.create_task(_run_sentinel_connection(pool_a, key))
        )
    if pool_b:
        _sentinel_tasks.append(
            asyncio.create_task(_run_sentinel_connection(pool_b, key))
        )
    if youtube_handles:
        _sentinel_tasks.append(
            asyncio.create_task(_run_youtube_sentinel_connection(youtube_handles, key))
        )


async def _resolve_and_store_sentiment(
    channel: str, res_data: dict, key: str, is_shutdown: bool = False
) -> None:
    # Compute multi-dimensional sentiment breakdown from ring buffer messages
    buffer = list(_ring_buffers.get(channel, []))
    if buffer:
        try:
            from ag_kaggle_5day.agents.scraper.feature_library import (
                calculate_multidimensional_sentiment,
            )

            res_data["sentiment_breakdown"] = calculate_multidimensional_sentiment(
                buffer
            )
        except Exception as err:
            logger.warning(f"Failed to calculate multidimensional sentiment: {err}")

    from ag_kaggle_5day.agents.gcp_storage import (
        store_streamer_profile_fabric,
        store_streamer_sentiment,
    )

    spectator_ratio = None
    recent_clips = []
    game_tags = []
    game_name = res_data.get("game_name", "Unknown")
    viewer_count = res_data.get("viewer_count", 0)

    twitch_client = TwitchAPIClient()
    user_details = None
    if twitch_client.is_configured and not is_shutdown:
        try:
            loop = asyncio.get_running_loop()
            # 1. Resolve channel info to get user id
            user_details = await loop.run_in_executor(
                None, twitch_client.get_channel_details, channel
            )
            language = "en"
            schedule = None
            if user_details:
                user_id = user_details.get("id")
                if user_id:
                    clips = await loop.run_in_executor(
                        None, twitch_client.get_broadcaster_clips, user_id, 3
                    )
                    if clips:
                        recent_clips = clips
                        for clip in clips:
                            clipper_handle = clip.get("creator_name")
                            if clipper_handle and clipper_handle.strip():
                                clipper_lower = clipper_handle.strip().lower()
                                if clipper_lower not in _channel_profiles_cache:
                                    try:
                                        clipper_details = await loop.run_in_executor(
                                            None,
                                            twitch_client.get_channel_details,
                                            clipper_lower,
                                        )
                                        if clipper_details:
                                            b_type = clipper_details.get(
                                                "broadcaster_type"
                                            )
                                            if b_type in ["partner", "affiliate"]:
                                                import random

                                                av = clipper_details.get(
                                                    "profile_image_url"
                                                )
                                                desc = clipper_details.get(
                                                    "description"
                                                )
                                                new_profile = {
                                                    "streamer_handle": clipper_lower,
                                                    "twitch_avatar": av,
                                                    "twitch_description": desc,
                                                    "tier": "micro_streamer",
                                                    "primary_game": "Variety",
                                                    "top_games": ["Variety"],
                                                    "archetype_cluster": (
                                                        "Cozy_Social_Interactive"
                                                    ),
                                                    "fabric_status": "bootstrapped",
                                                    "starfield_coordinates": {
                                                        "x": random.uniform(-0.8, 0.8),
                                                        "y": random.uniform(-0.8, 0.8),
                                                        "z": random.uniform(-0.8, 0.8),
                                                    },
                                                    "current_vibe_tribe": "0",
                                                    "last_updated": time.time(),
                                                }
                                                await loop.run_in_executor(
                                                    None,
                                                    store_streamer_profile_fabric,
                                                    clipper_lower,
                                                    new_profile,
                                                )
                                                _channel_profiles_cache[
                                                    clipper_lower
                                                ] = new_profile
                                                msg = (
                                                    "Clipper Discovery: "
                                                    "Bootstrapped "
                                                    f"@{clipper_lower}"
                                                )
                                                logger.info(msg)
                                    except Exception as clip_disc_err:
                                        logger.warning(
                                            "Clipper Discovery: Failed to "
                                            f"check/bootstrap '{clipper_lower}': "
                                            f"{clip_disc_err}"
                                        )

                    # Fetch schedule
                    sched = await loop.run_in_executor(
                        None, twitch_client.get_schedule, user_id
                    )
                    if sched:
                        schedule = sched

            # 2. Get active stream details (viewers and game tags)
            stream_info_list = await loop.run_in_executor(
                None, twitch_client.get_online_streams, [channel]
            )
            if stream_info_list:
                stream_info = stream_info_list[0]
                viewer_count = stream_info.get("viewer_count", viewer_count)
                game_name = stream_info.get("game_name", game_name)
                language = stream_info.get("language", "en")
                game_id = stream_info.get("game_id")
                if game_id:
                    tags = await loop.run_in_executor(
                        None, twitch_client.get_game_tags, game_id
                    )
                    if tags:
                        game_tags = tags

            res_data["language"] = language
            res_data["schedule"] = schedule
        except Exception as api_err:
            logger.warning(
                f"RaidSentinel: Failed to fetch Twitch metadata for "
                f"'{channel}': {api_err}"
            )

    # 3. Resolve Steam appid and player counts
    if (
        game_name
        and game_name.lower() not in ("unknown", "offline")
        and not is_shutdown
    ):
        try:
            loop = asyncio.get_running_loop()
            steam_id = await loop.run_in_executor(
                None, get_steam_appid_by_name, game_name
            )
            if steam_id:
                players = await loop.run_in_executor(
                    None, get_steam_player_count, steam_id
                )
                if players > 0:
                    spectator_ratio = round(float(viewer_count) / float(players), 4)
        except Exception as steam_err:
            logger.warning(
                f"RaidSentinel: Failed to calculate Steam ratio for "
                f"'{game_name}': {steam_err}"
            )

    res_data["viewer_count"] = viewer_count
    res_data["game_name"] = game_name
    if not is_shutdown:
        res_data["spectator_ratio"] = spectator_ratio
        res_data["recent_clips"] = recent_clips
        res_data["game_tags"] = game_tags
    else:
        # On shutdown, preserve values already populated in res_data
        if "spectator_ratio" not in res_data:
            res_data["spectator_ratio"] = None
        if "recent_clips" not in res_data:
            res_data["recent_clips"] = []
        if "game_tags" not in res_data:
            res_data["game_tags"] = []

    # Calculate and store adaptive metrics
    new_obs = {
        "msg_per_minute": res_data.get("msg_per_minute"),
        "chat_volatility": res_data.get("chat_volatility"),
        "rolling_sentiment_score": res_data.get("rolling_sentiment_score"),
        "viewer_count": viewer_count,
    }
    updated_adaptive = apply_adaptive_decay_filter(channel, new_obs, time.time())
    _channel_adaptive_metrics[channel] = updated_adaptive
    res_data["adaptive_metrics"] = updated_adaptive

    # Resolve display name and user name for YouTube/Twitch
    link_info = None
    try:
        from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

        link_info = resolve_streamer_link(channel)
        if link_info:
            res_data["display_name"] = link_info.get("display_name")
            res_data["user_name"] = link_info.get("display_name")
    except Exception:
        pass

    try:
        from ag_kaggle_5day.agents.gcp_storage import update_streamer_adaptive_metrics

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, store_streamer_sentiment, channel, res_data, "sentinel_flush"
        )
        await loop.run_in_executor(
            None, update_streamer_adaptive_metrics, channel, updated_adaptive
        )

        # Update the streamer_profiles collection fabric as well with rich metadata
        try:
            profile = dict(_channel_profiles_cache.get(channel.lower()) or {})
            profile["streamer_handle"] = channel
            if user_details:
                profile["twitch_avatar"] = user_details.get("profile_image_url")
                profile["twitch_description"] = user_details.get("description")
            profile["language"] = res_data.get("language")
            profile["schedule"] = res_data.get("schedule")
            profile["recent_clips"] = res_data.get("recent_clips")
            profile["primary_game"] = game_name

            # Update metrics
            profile["interaction_density"] = {
                "msg_per_minute": res_data.get("msg_per_minute") or 0.0,
                "chat_volatility": res_data.get("chat_volatility") or 0.0,
                "interactive_density_rate": (res_data.get("msg_per_minute") or 0.0)
                / max(viewer_count, 1),
            }

            is_promoted = True
            if channel.lower().startswith("uc"):
                # YouTube channel: only save persistent profile if linked
                # or has >= 5 messages
                if not (link_info or res_data.get("total_messages", 0) >= 5):
                    is_promoted = False
                    logger.info(
                        "RaidSentinel: Skipping persistent profile store for "
                        f"unlinked/inactive YouTube channel '{channel}'"
                    )

            if is_promoted:
                from ag_kaggle_5day.agents.gcp_storage import (
                    store_streamer_profile_fabric,
                )

                await loop.run_in_executor(
                    None, store_streamer_profile_fabric, channel, profile
                )
        except Exception as prof_err:
            logger.warning(
                "RaidSentinel: Failed to update profile fabric for "
                f"'{channel}': {prof_err}"
            )
    except Exception as save_err:
        logger.error(
            "RaidSentinel: Failed to store sentiment/adaptive metrics "
            f"for '{channel}': {save_err}"
        )


async def _synthesize_and_flush_sentiment(
    channel: str, res_data: dict, prompt: str, key: str
) -> None:
    """Helper to run the Gemini synthesis call and flush the final state

    to Firestore and BigQuery.
    """
    import asyncio

    summary = "Active stream with stable chat velocity."
    if key:
        try:
            from ag_kaggle_5day.agents.scraper import safe_generate_content

            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: safe_generate_content(
                    api_key=key,
                    model="gemma-4-31b-it",
                    contents=prompt,
                    system_instruction=(
                        "You are a stream highlight describer. "
                        "Output only the summarized highlight sentence."
                    ),
                    chain_name="sentiment",
                ),
            )
            if res and res.text:
                summary = res.text.strip()
        except Exception as e:
            logger.warning(
                f"Failed to generate synthesized highlight summary for '{channel}': {e}"
            )
            summary = "Spike events detected with normal chat activity."

    res_data["summary"] = summary
    from ag_kaggle_5day.agents.scraper import _resolve_and_store_sentiment

    await _resolve_and_store_sentiment(channel, res_data, "", is_shutdown=True)


async def async_live_monitor_youtube_chat(
    channel_id: str, duration_sec: float = 30.0
) -> list[str]:
    """Scrapes YouTube live chat messages for a channel for duration_sec and

    returns them.
    """
    import asyncio
    import time

    loop = asyncio.get_running_loop()
    video_id = await loop.run_in_executor(
        None, get_youtube_channel_live_video_id, channel_id
    )
    if not video_id:
        return []

    messages = []
    seen_sigs = set()
    start_time = time.time()

    while time.time() - start_time < duration_sec:
        new_msgs = await loop.run_in_executor(None, _scrape_youtube_live_chat, video_id)
        for m in new_msgs:
            msg_sig = f"{m['author']}:{m['timestamp']}:{m['message'][:20]}"
            if msg_sig not in seen_sigs:
                seen_sigs.add(msg_sig)
                messages.append(m["message"])
        await asyncio.sleep(3.0)

    return messages


async def async_live_monitor_twitch_chat(
    handle: str, duration_sec: float = 30.0
) -> list[str]:
    """Connects to Twitch IRC, joins handle's channel, collects messages for

    duration_sec, and returns them.
    """
    import asyncio
    import time

    messages = []
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("irc.chat.twitch.tv", 6697, ssl=True), timeout=5.0
        )
        anon_nick = f"justinfan{random.randint(10000, 99999)}"
        writer.write("PASS oauth:dummy\r\n".encode("utf-8"))
        writer.write(f"NICK {anon_nick}\r\n".encode("utf-8"))
        writer.write(
            (
                "CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\r\n"
            ).encode("utf-8")
        )
        await writer.drain()

        channel = handle.lower().strip()
        writer.write(f"JOIN #{channel}\r\n".encode("utf-8"))
        await writer.drain()

        start_time = time.time()
        while time.time() - start_time < duration_sec:
            remaining = duration_sec - (time.time() - start_time)
            if remaining <= 0:
                break
            try:
                line_bytes = await asyncio.wait_for(
                    reader.readline(), timeout=min(remaining, 5.0)
                )
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if line.startswith("PING"):
                    writer.write("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                    await writer.drain()
                elif "PRIVMSG" in line:
                    parts = line.split(" PRIVMSG #", 1)
                    if len(parts) == 2:
                        chan_part, msg_part = parts[1].split(" :", 1)
                        msg = msg_part.strip()
                        messages.append(msg)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
    except Exception as e:
        logger.warning(f"Live monitor connection failed for {handle}: {e}")
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
    return messages


async def stop_raid_sentinel(key: Optional[str] = None) -> None:
    """Stops the RaidSentinel background listener and flushes all

    current metrics to the database cache.
    """
    global _sentinel_running, _sentinel_tasks
    if not _sentinel_running:
        return

    logger.info("RaidSentinel: Stopping background listener and flushing metrics...")
    _sentinel_running = False

    # Cancel tasks
    for task in _sentinel_tasks:
        try:
            task.cancel()
        except Exception:
            pass

    # Flush latest rolling coordinates for all active channels to Firestore cache
    try:
        import datetime
        import os

        # Resolve backup key if present
        backup_key = os.environ.get("GEMINI_API_KEY_BACKUP", "")
        sem = asyncio.Semaphore(5)

        async def _sem_synthesize_and_flush(channel, res_data, prompt, active_key):
            async with sem:
                await _synthesize_and_flush_sentiment(
                    channel, res_data, prompt, active_key
                )

        # Resolve active channel online metadata by querying Twitch Helix directly
        online_metadata = {}
        active_channels = list(_rolling_windows.keys())
        twitch_client = TwitchAPIClient()
        if twitch_client.is_configured and active_channels:
            try:
                # Helix allows querying up to 100 logins in a single request
                for chunk_idx in range(0, len(active_channels), 100):
                    chunk = active_channels[chunk_idx : chunk_idx + 100]
                    streams = twitch_client.get_online_streams(chunk)
                    for s in streams:
                        login = s.get("user_login", "").strip().lower()
                        if login:
                            viewer_count = int(s.get("viewer_count") or 0)
                            game_name = s.get("game_name", "Unknown")
                            online_metadata[login] = {
                                "viewer_count": viewer_count,
                                "game_name": game_name,
                                "spectator_ratio": None,
                                "game_tags": s.get("game_tags", []),
                            }
                # Resolve Steam appid and player counts for online streams
                for login, meta in online_metadata.items():
                    g_name = meta["game_name"]
                    if g_name and g_name.lower() not in ("unknown", "offline"):
                        try:
                            steam_id = get_steam_appid_by_name(g_name)
                            if steam_id:
                                players = get_steam_player_count(steam_id)
                                if players > 0:
                                    meta["spectator_ratio"] = round(
                                        float(meta["viewer_count"]) / float(players), 4
                                    )
                        except Exception:
                            pass
            except Exception as api_err:
                logger.warning(
                    "RaidSentinel: Failed to query Twitch Helix for active "
                    f"channels: {api_err}"
                )

        # Fallback to pre-loaded cached games for channels not resolved by direct query
        try:
            from ag_kaggle_5day.agents.advisor import get_cached_games

            cached_games = get_cached_games()
            for game in cached_games:
                title = game.get("title", "Unknown")
                players = int(game.get("steam_player_count") or 0)
                top_s = game.get("top_streamers", [])
                for s in top_s:
                    login = s.get("user_login")
                    if login:
                        login_clean = login.strip()
                        if not login_clean.lower().startswith("uc"):
                            login_clean = login_clean.lower()
                        if login_clean not in online_metadata:
                            viewer_count = int(s.get("viewer_count") or 0)
                            spec_ratio = None
                            if players > 0:
                                spec_ratio = round(
                                    float(viewer_count) / float(players), 4
                                )
                            online_metadata[login_clean] = {
                                "viewer_count": viewer_count,
                                "game_name": title,
                                "spectator_ratio": spec_ratio,
                                "game_tags": s.get("game_tags", []),
                            }
        except Exception as cache_err:
            logger.warning(
                f"RaidSentinel: Failed to preload cached games fallback: {cache_err}"
            )

        flush_tasks = []
        synthesis_count = 0

        for channel in list(_rolling_windows.keys()):
            buffer = list(_ring_buffers.get(channel, []))
            if len(buffer) < 5:
                continue
            scores = [s for _, s in _rolling_windows.get(channel, [])]
            if not scores:
                continue
            mu, sigma = _calculate_volatility_and_mean(scores)
            mpm = len(_message_rates.get(channel, []))

            vibe_str = "Neutral"
            if mu > 0.2:
                vibe_str = "Positive"
            elif mu < -0.2:
                vibe_str = "Negative"

            deduped = deduplicate_chat_messages(buffer)

            meta = online_metadata.get(channel, {})
            res_data = {
                "total_messages": len(buffer),
                "msg_per_minute": mpm,
                "sentiment": vibe_str,
                "messages": deduped[:50],
                "summary": "",
                "game_name": meta.get("game_name")
                or _channel_games.get(channel, "Unknown"),
                "chat_volatility": sigma,
                "rolling_sentiment_score": mu,
                "viewer_count": meta.get("viewer_count", 0),
                "spectator_ratio": meta.get("spectator_ratio"),
                "game_tags": meta.get("game_tags", []),
            }

            events = _channel_events.get(channel, [])
            if events:
                # Compile chronological timeline of events
                timeline_lines = []
                for idx, ev in enumerate(events):
                    time_str = datetime.datetime.fromtimestamp(
                        ev["timestamp"], datetime.timezone.utc
                    ).strftime("%H:%M:%S")
                    timeline_lines.append(
                        f"- [{time_str}] {ev['trigger_type']} "
                        f"(Speed: {ev['mpm']:.1f} msg/min, "
                        f"Volatility: {ev['sigma']:.2f})"
                    )
                    snippet_text = " | ".join(ev["chat_snippet"][:5])
                    timeline_lines.append(f'  Snippet: "{snippet_text}"')

                timeline_text = "\n".join(timeline_lines)
                prompt = (
                    "Analyze this chronological sequence of highlight "
                    f"events and chat snippets for streamer '{channel}' "
                    "during a 15-minute logging run. "
                    "Generate a single, concise (exactly one sentence) "
                    "summary describing the overall stream activity, "
                    "highlights, or vibe transitions.\n\n"
                    f"Event Timeline:\n{timeline_text}\n\n"
                    f"Summary:"
                )

                # Shard keys proactively across even/odd synthesis requests
                active_key = key
                if synthesis_count % 2 == 1 and backup_key:
                    active_key = backup_key

                synthesis_count += 1

                # Perform LLM call asynchronously inside the gather pool
                # with semaphore control
                flush_tasks.append(
                    _sem_synthesize_and_flush(channel, res_data, prompt, active_key)
                )
            else:
                # Default summary for quiet channels
                archetype = _channel_archetypes.get(channel, "Cozy_Social_Interactive")
                if archetype == "Cozy_Social_Interactive":
                    res_data["summary"] = "Cozy chat session with stable message rate."
                elif archetype == "Highly_Competitive_Sweat":
                    res_data["summary"] = (
                        "Competitive stream with normal activity level."
                    )
                else:
                    res_data["summary"] = "Active stream with stable chat velocity."

                # Direct flush with is_shutdown=True
                from ag_kaggle_5day.agents.scraper import _resolve_and_store_sentiment

                flush_tasks.append(
                    _resolve_and_store_sentiment(
                        channel, res_data, "", is_shutdown=True
                    )
                )

        if flush_tasks:
            await asyncio.gather(*flush_tasks, return_exceptions=True)
            logger.info(
                f"RaidSentinel: Flushed sentiment data for {len(flush_tasks)} channels."
            )
    except Exception as e:
        logger.error(f"RaidSentinel: Failed to flush metrics on shutdown: {e}")

    _sentinel_tasks = []
