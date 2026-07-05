import logging
import random
import time

from ag_kaggle_5day.agents.scraper.steam import (
    get_steam_appid_by_name,
    get_steam_player_count,
)

logger = logging.getLogger("streamer_advisor.scraper")


def deduplicate_message_tokens(msg: str) -> str:
    """Removes consecutive duplicate words/tokens inside a single message.
    E.g. 'POG POG POG' -> 'POG'.
    """
    tokens = msg.split()
    if not tokens:
        return ""
    new_tokens = [tokens[0]]
    for t in tokens[1:]:
        if t.lower() != new_tokens[-1].lower():
            new_tokens.append(t)
    return " ".join(new_tokens)


def deduplicate_chat_messages(messages: list[str]) -> list[str]:
    """Applies deduplication techniques to a list of Twitch chat messages.
    Filters out duplicate or near-identical messages globally in the sample.
    """
    seen = set()
    deduped = []
    for msg in messages:
        cleaned_msg = deduplicate_message_tokens(msg)
        if not cleaned_msg:
            continue
        # Strip all punctuation and compare in lowercase to handle near-duplicates
        val = "".join(c for c in cleaned_msg.lower() if c.isalnum())
        key = val if val else cleaned_msg.strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(cleaned_msg)
    return deduped


def sample_live_chat(
    channel_name: str, duration: int = 30, source: str = "on-demand"
) -> dict:
    """Connects to irc.chat.twitch.tv on SSL port 6697, joins #channel_name,
    reads raw IRC lines for `duration` seconds, and calculates:
    - total_messages: count
    - msg_per_minute: float
    - sentiment: str (heuristics based on token count)
    - messages: sample list of strings
    """
    import socket
    import ssl

    from ag_kaggle_5day.agents.scraper import TwitchAPIClient, safe_generate_content

    logger.info(
        "Sampling live Twitch chat for channel '%s' (duration=%ds)...",
        channel_name,
        duration,
    )
    channel = channel_name.lower().strip()
    if not channel.startswith("#"):
        channel = f"#{channel}"

    messages = []
    start_time = time.time()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)

        context = ssl.create_default_context()
        ssl_sock = context.wrap_socket(sock, server_hostname="irc.chat.twitch.tv")
        ssl_sock.connect(("irc.chat.twitch.tv", 6697))

        anon_nick = f"justinfan{random.randint(10000, 99999)}"
        ssl_sock.sendall("PASS oauth:dummy\r\n".encode("utf-8"))
        ssl_sock.sendall(f"NICK {anon_nick}\r\n".encode("utf-8"))
        ssl_sock.sendall(f"JOIN {channel}\r\n".encode("utf-8"))

        ssl_sock.settimeout(1.0)

        buffer = ""
        while time.time() - start_time < duration:
            try:
                data = ssl_sock.recv(4096).decode("utf-8", errors="ignore")
                if not data:
                    break
                buffer += data
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    if line.startswith("PING"):
                        ssl_sock.sendall("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                    elif "PRIVMSG" in line:
                        parts = line.split(f"PRIVMSG {channel} :", 1)
                        if len(parts) == 2:
                            msg = parts[1].strip()
                            messages.append(msg)
            except socket.timeout:
                continue
            except Exception as e:
                logger.warning(f"Error reading from Twitch IRC: {e}")
                break
        try:
            ssl_sock.close()
        except Exception:
            pass
    except Exception as e:
        logger.warning(
            f"Failed to connect to Twitch IRC or sample chat for {channel_name}: {e}"
        )
        offline_res = {
            "total_messages": 0,
            "msg_per_minute": 0.0,
            "sentiment": "Offline",
            "messages": [],
        }
        try:
            from ag_kaggle_5day.agents.gcp_storage import store_streamer_sentiment

            store_streamer_sentiment(channel_name, offline_res, source)
        except Exception as save_err:
            logger.error(f"Failed to store offline sentiment: {save_err}")
        return offline_res

    total_msgs = len(messages)
    elapsed = time.time() - start_time
    msg_per_min = (total_msgs / elapsed) * 60 if elapsed > 0 else 0.0

    positive_words = {
        "hype",
        "lol",
        "gg",
        "love",
        "nice",
        "pog",
        "pogchamp",
        "wow",
        "great",
        "fun",
        "lmao",
        "clapped",
    }
    negative_words = {
        "mad",
        "sad",
        "fail",
        "bad",
        "hate",
        "boring",
        "toxic",
        "noob",
        "suck",
        "trash",
        "cringe",
        "rip",
    }

    pos_count = 0
    neg_count = 0
    for m in messages:
        m_lower = m.lower()
        for w in positive_words:
            if w in m_lower:
                pos_count += 1
        for w in negative_words:
            if w in m_lower:
                neg_count += 1

    if total_msgs == 0:
        sentiment = "Offline"
    elif pos_count > neg_count:
        sentiment = "Positive"
    elif neg_count > pos_count:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    deduped = deduplicate_chat_messages(messages)

    import os

    api_key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    summary = ""

    if api_key and deduped:
        transcript_text = "\n".join([f"- {m}" for m in deduped])
        prompt = (
            "Analyze the following live Twitch chat log and provide a concise, "
            "one-sentence summary of the main topics, user sentiment, or "
            f"reactions in the chat.\n\nChat Log:\n{transcript_text}\n\n"
            "Summary:"
        )
        try:
            response = safe_generate_content(
                api_key=api_key,
                model="gemma-4-31b-it",
                contents=prompt,
                chain_name="sentiment",
            )
            summary = response.text.strip()
        except Exception as e:
            logger.warning(f"Failed to generate chat summary using subagent: {e}")

    # Resolve Twitch Helix metadata if configured
    streamer_channel_url = f"https://twitch.tv/{channel_name.lower().strip()}"
    stream_url = streamer_channel_url
    game_name = "Unknown"
    top_streamers = []
    viewer_count = 0
    game_tags = []
    recent_clips = []
    spectator_ratio = None

    twitch_client = TwitchAPIClient()
    if twitch_client.is_configured:
        try:
            stream_info_list = twitch_client.get_online_streams([channel_name])
            if stream_info_list:
                stream_info = stream_info_list[0]
                game_id = stream_info.get("game_id", "")
                game_name = stream_info.get("game_name", "Unknown")
                viewer_count = stream_info.get("viewer_count", 0)

                if game_id:
                    top_streamers = twitch_client.get_top_streamers(game_id, limit=3)
                    game_tags = twitch_client.get_game_tags(game_id)

                user_details = twitch_client.get_channel_details(channel_name)
                if user_details:
                    user_id = user_details.get("id", "")
                    if user_id:
                        vods = twitch_client.get_recent_vods(user_id, limit=1)
                        if vods:
                            vod_id = vods[0].get("id")
                            if vod_id:
                                stream_url = f"https://twitch.tv/videos/{vod_id}"

                        clips = twitch_client.get_broadcaster_clips(user_id, 3)
                        if clips:
                            recent_clips = clips
        except Exception as api_err:
            logger.warning(
                f"Failed to query Twitch Helix metadata inside sample_live_chat "
                f"for '{channel_name}': {api_err}"
            )

    # Fetch keyless Steam active players to compute spectator_ratio
    if game_name and game_name.lower() not in ("unknown", "offline"):
        try:
            steam_id = get_steam_appid_by_name(game_name)
            if steam_id:
                players = get_steam_player_count(steam_id)
                if players > 0:
                    spectator_ratio = round(float(viewer_count) / float(players), 4)
        except Exception as steam_err:
            logger.warning(
                f"Failed to calculate Steam spectator ratio for "
                f"'{game_name}': {steam_err}"
            )

    res = {
        "total_messages": total_msgs,
        "msg_per_minute": round(msg_per_min, 2),
        "sentiment": sentiment,
        "messages": deduped[:50],
        "summary": summary,
        "streamer_channel_url": streamer_channel_url,
        "stream_url": stream_url,
        "game_name": game_name,
        "top_streamers_of_game": top_streamers,
        "viewer_count": viewer_count,
        "spectator_ratio": spectator_ratio,
        "recent_clips": recent_clips,
        "game_tags": game_tags,
    }
    try:
        from ag_kaggle_5day.agents.gcp_storage import store_streamer_sentiment

        store_streamer_sentiment(channel_name, res, source)
    except Exception as save_err:
        logger.error(f"Failed to automatically store sampled sentiment: {save_err}")
    return res
