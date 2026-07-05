import asyncio
import json
import logging
import os
import random
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from ag_kaggle_5day.security import (
    chat_stream_client_limiter,
    chat_stream_global_limiter,
    check_rate_limit,
    get_client_key,
    live_monitor_client_limiter,
    live_monitor_global_limiter,
)

logger = logging.getLogger("streamer_advisor.routes.monitoring")
router = APIRouter()


@router.post(
    "/api/streamers/{handle}/live-monitor",
    dependencies=[
        Depends(
            check_rate_limit(live_monitor_client_limiter, live_monitor_global_limiter)
        )
    ],
)
async def api_live_monitor_streamer(
    handle: str,
    client_key: str | None = Depends(get_client_key),
    x_gemini_analysis_model: str | None = Header(None),
):
    """
    Connects to the streamer's chat room, collects messages for 30s,
    runs Gemini sentiment analysis / summarization, and logs it to Firestore.
    """
    if not client_key or not client_key.strip():
        raise HTTPException(
            status_code=400, detail="API key required to run realtime chat radar."
        )

    from ag_kaggle_5day.agents.gcp_storage import (
        get_streamer_profile_fabric_from_fs,
        store_streamer_sentiment_moment,
    )
    from ag_kaggle_5day.agents.scraper import (
        async_live_monitor_twitch_chat,
        async_live_monitor_youtube_chat,
        safe_generate_content,
    )

    clean_handle = handle.strip().lstrip("@")
    is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", clean_handle))
    h = clean_handle if is_yt else clean_handle.lower()

    if is_yt and h.lower() == h:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_case_preserved_youtube_id,
            get_firestore_client,
        )

        db_client = get_firestore_client()
        if db_client:
            healed = get_case_preserved_youtube_id(h, None, db_client)
            if healed and healed != h:
                h = healed

    # 1. Monitor chat for 30 seconds
    if is_yt:
        messages = await async_live_monitor_youtube_chat(h, duration_sec=30.0)
    else:
        messages = await async_live_monitor_twitch_chat(h, duration_sec=30.0)

    if not messages:
        return {
            "status": "offline",
            "message": "No live chat activity detected. Streamer might be offline.",
            "messages_count": 0,
            "mpm": 0.0,
            "sentiment": "neutral",
            "summary": "No discussion detected.",
        }

    messages_count = len(messages)
    mpm = (messages_count / 30.0) * 60.0

    # 2. Analyze sentiment using Gemini
    transcript = "\n".join(messages[:100])
    prompt = (
        f"Here is a live chat transcript for streamer @{h}.\n"
        f"Transcript:\n{transcript}\n\n"
        "Analyze the chat and return a JSON object with keys:\n"
        "- 'summary': a single concise sentence (max 120 chars) "
        "summarizing the dominant topic/themes.\n"
        "- 'sentiment': a float between -1.0 (very negative) and "
        "1.0 (very positive) representing the average chat mood.\n"
        "Do not wrap in markdown code blocks. Return only raw valid JSON."
    )

    key = client_key or os.environ.get("GEMINI_API_KEY", "")

    res = safe_generate_content(
        api_key=key,
        model=x_gemini_analysis_model,
        contents=prompt,
        chain_name="sentiment",
    )

    summary = "Active discussion monitoring completed."
    sentiment_score = 0.0
    if res and res.text:
        text = res.text.strip()
        # Clean markdown wrap if any
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) >= 2:
                if lines[0].startswith("```json"):
                    text = "\n".join(lines[1:-1])
                else:
                    text = "\n".join(lines[1:-1])
        try:
            data = json.loads(text)
            summary = data.get("summary", summary)
            sentiment_score = float(data.get("sentiment", 0.0))
        except Exception:
            summary = text[:150]

    sentiment_label = (
        "positive"
        if sentiment_score > 0.1
        else "negative"
        if sentiment_score < -0.1
        else "neutral"
    )

    # Get current game name from profile if available
    game_name = "Unknown Game"
    profile = get_streamer_profile_fabric_from_fs(h)
    if profile and profile.get("game_name"):
        game_name = profile.get("game_name")

    # Store moment
    store_streamer_sentiment_moment(
        streamer_handle=h,
        game_name=game_name,
        trigger_type="live_monitor",
        trigger_value=sentiment_score,
        mpm=mpm,
        sentiment=sentiment_label,
        summary=summary,
        messages=messages[:20],
    )

    return {
        "status": "success",
        "messages_count": messages_count,
        "mpm": mpm,
        "sentiment": sentiment_label,
        "sentiment_score": sentiment_score,
        "summary": summary,
    }


@router.get(
    "/api/streamers/{handle}/chat-stream",
    dependencies=[
        Depends(
            check_rate_limit(chat_stream_client_limiter, chat_stream_global_limiter)
        )
    ],
)
async def api_stream_twitch_chat(handle: str):
    """
    Streams live Twitch or YouTube chat messages for a streamer in real-time
    using Server-Sent Events (SSE) via StreamingResponse.
    """
    clean_handle = handle.strip().lstrip("@")
    is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", clean_handle))
    h = clean_handle if is_yt else clean_handle.lower()

    if is_yt and h.lower() == h:
        from ag_kaggle_5day.agents.gcp_storage import (
            get_case_preserved_youtube_id,
            get_firestore_client,
        )

        db_client = get_firestore_client()
        if db_client:
            healed = get_case_preserved_youtube_id(h, None, db_client)
            if healed and healed != h:
                h = healed

    async def youtube_chat_generator():
        from ag_kaggle_5day.agents.scraper import (
            _scrape_youtube_live_chat,
            get_youtube_channel_live_video_id,
        )

        loop = asyncio.get_running_loop()
        video_id = await loop.run_in_executor(
            None, get_youtube_channel_live_video_id, h
        )
        if not video_id:
            payload = {
                "sender": "SYSTEM",
                "message": (
                    "Could not find an active livestream watch ID for "
                    f"YouTube channel {h}"
                ),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        payload = {
            "sender": "SYSTEM",
            "message": f"Connected to live chat stream for YouTube channel {h}",
        }
        yield f"data: {json.dumps(payload)}\n\n"

        seen_sigs = set()
        start_time = time.time()

        while True:
            if time.time() - start_time > 300.0:
                payload = {
                    "sender": "SYSTEM",
                    "message": (
                        "Maximum connection time reached (5 minutes). "
                        "Auto-disconnecting."
                    ),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                break

            new_msgs = await loop.run_in_executor(
                None, _scrape_youtube_live_chat, video_id
            )

            for m in new_msgs:
                if m.get("author") == "SYSTEM" and "Chat is disabled" in m.get(
                    "message", ""
                ):
                    payload = json.dumps({"sender": "SYSTEM", "message": m["message"]})
                    yield f"data: {payload}\n\n"
                    return

                msg_sig = f"{m['author']}:{m['timestamp']}:{m['message'][:20]}"
                if msg_sig not in seen_sigs:
                    seen_sigs.add(msg_sig)
                    payload = json.dumps(
                        {"sender": m["author"], "message": m["message"]}
                    )
                    yield f"data: {payload}\n\n"

            # Clean up signatures
            if len(seen_sigs) > 200:
                seen_sigs = set(list(seen_sigs)[-100:])

            await asyncio.sleep(4.0)

    async def chat_generator():
        writer = None
        start_time = time.time()
        try:
            reader, writer = await asyncio.open_connection(
                "irc.chat.twitch.tv", 6697, ssl=True
            )
            anon_nick = f"justinfan{random.randint(10000, 99999)}"
            writer.write("PASS oauth:dummy\r\n".encode("utf-8"))
            writer.write(f"NICK {anon_nick}\r\n".encode("utf-8"))
            await writer.drain()

            writer.write(f"JOIN #{h}\r\n".encode("utf-8"))
            await writer.drain()

            payload = {
                "sender": "SYSTEM",
                "message": f"Connected to live chat room for @{h}",
            }
            yield f"data: {json.dumps(payload)}\n\n"

            while True:
                if time.time() - start_time > 300.0:
                    payload = {
                        "sender": "SYSTEM",
                        "message": (
                            "Maximum connection time reached (5 minutes). "
                            "Auto-disconnecting."
                        ),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    break
                line_bytes = await asyncio.wait_for(reader.readline(), timeout=30.0)
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if line.startswith("PING"):
                    writer.write("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                    await writer.drain()
                elif "PRIVMSG" in line:
                    parts = line.split(" PRIVMSG #", 1)
                    if len(parts) == 2:
                        sender = parts[0].split("!", 1)[0].replace(":", "")
                        chan_part, msg_part = parts[1].split(" :", 1)
                        msg = msg_part.strip()
                        payload = json.dumps({"sender": sender, "message": msg})
                        yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            payload = {
                "sender": "SYSTEM",
                "message": "Connection timed out due to inactivity.",
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            payload = {
                "sender": "SYSTEM",
                "message": f"Connection lost: {str(e)}",
            }
            yield f"data: {json.dumps(payload)}\n\n"
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        youtube_chat_generator() if is_yt else chat_generator(),
        media_type="text/event-stream",
        headers=headers,
    )
