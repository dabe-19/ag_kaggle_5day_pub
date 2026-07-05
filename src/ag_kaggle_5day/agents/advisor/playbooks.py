from __future__ import annotations

import datetime
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("streamer_advisor.advisor")


def get_affiliate_playbook(
    vibe: str,
    scale: str,
    stream_goal: str,
    api_key: Optional[str] = None,
    previous_playbooks: Optional[list[dict]] = None,
) -> dict:
    """
    Generates the affiliate playbook dictionary.

    If api_key is provided, uses Gemini with Google Search grounding to
    dynamically recommend 3 gear items and search for deals on Amazon/Best Buy,
    incorporating any previous playbooks' setup/hardware recommendations as
    context.

    Falls back to static affiliate products from config if no api_key or on
    error.
    """
    from ag_kaggle_5day.agents.advisor import (
        parse_json_response,
        safe_generate_content,
    )
    from ag_kaggle_5day.agents.scraper import load_model_config

    now_local = datetime.datetime.now(datetime.timezone.utc).astimezone()
    generated_at_iso = now_local.isoformat()
    formatted_time = now_local.strftime("%I:%M %p %Z")

    config = load_model_config()
    static_products = config.get("affiliate_products", [])

    # Default static fallback content
    hook = (
        "Level up your hardware and production value to stand out from the competition."
    )
    advice = (
        "Using professional hardware and peripherals not only enhances your "
        "viewer's experience, but also streamlines your workflow. "
        "Streamlining your OBS control, audio mixing, and video clarity "
        "makes growing your channel much more natural."
    )
    products = static_products

    # Format previous playbooks' preparation context if available
    previous_context = ""
    if previous_playbooks:
        context_lines = []
        for p in previous_playbooks:
            game_name = p.get("game", "Unknown Game")
            prep = p.get("preparation", "None")
            context_lines.append(f"- Game '{game_name}' preparation needs: {prep}")
        previous_context = (
            "\n### Recommended Setup & Hardware from Preceding Playbooks:\n"
            + "\n".join(context_lines)
            + "\n"
        )

    if api_key:
        system_instruction = (
            "You are an expert streaming setup consultant and affiliate "
            "marketer. Your goal is to recommend 3 specific, highly suitable "
            "pieces of gear, hardware, or software tailored to the streamer's "
            "profile (vibe, channel scale, and stream goal).\n"
            "You must search Google to find the best current deals, real "
            "prices, and shopping links from Amazon, Best Buy, or other "
            "major online retailers for these items.\n"
            "Format your response as a raw JSON object with these keys:\n"
            "- 'hook': a 1-sentence engaging title/hook for this gear "
            "recommendation showcase.\n"
            "- 'advice': a 2-3 sentence strategic explanation of how this "
            "combination of gear helps the streamer.\n"
            "- 'products': a list of 3 objects, each having:\n"
            "  - 'name': the exact name of the product.\n"
            "  - 'price': the lowest price found (e.g. '$149.99' or 'Check Site').\n"
            "  - 'link': the shopping URL to purchase the item.\n"
            "  - 'benefit': a 1-sentence description of how this product "
            "benefits their stream specifically.\n"
            "Do NOT wrap output in markdown code fences, return only the "
            "raw JSON object string."
        )

        prompt = (
            f"Streamer Profile:\n"
            f"- Vibe: {vibe}\n"
            f"- Channel Scale: {scale}\n"
            f"- Stream Goal: {stream_goal}\n"
            f"{previous_context}\n"
            "Generate the customized gear recommendation and search Google "
            "for the best deals/prices. "
            "If prior recommendations are provided in the context above, "
            "ensure you recommend complementary "
            "or specific matching gear to address those needs."
        )

        try:
            logger.info(
                "Generating dynamic affiliate playbook using Gemini search grounding..."
            )
            # We use safe_generate_content with chain_name="affiliate" and
            # enable Google Search grounding
            response = safe_generate_content(
                api_key=api_key,
                model=None,
                contents=prompt,
                system_instruction=system_instruction,
                use_google_search=True,
                chain_name="affiliate",
            )
            data = parse_json_response(response.text)
            if (
                isinstance(data, dict)
                and "hook" in data
                and "advice" in data
                and "products" in data
                and isinstance(data["products"], list)
            ):
                hook = data["hook"]
                advice = data["advice"]
                products = data["products"]
                logger.info("Successfully generated dynamic affiliate playbook.")
            else:
                raise ValueError("Dynamic playbook parsed but missing keys.")
        except Exception as e:
            logger.warning(
                f"Dynamic affiliate playbook search grounding failed: {e}. "
                "Retrying without search grounding..."
            )
            try:
                response = safe_generate_content(
                    api_key=api_key,
                    model=None,
                    contents=prompt,
                    system_instruction=system_instruction,
                    use_google_search=False,
                    chain_name="affiliate",
                )
                data = parse_json_response(response.text)
                if (
                    isinstance(data, dict)
                    and "hook" in data
                    and "advice" in data
                    and "products" in data
                    and isinstance(data["products"], list)
                ):
                    hook = data["hook"]
                    advice = data["advice"]
                    products = data["products"]
                    logger.info(
                        "Successfully generated dynamic affiliate playbook "
                        "without search grounding."
                    )
                else:
                    logger.warning(
                        "Dynamic playbook without search grounding parsed "
                        "but missing keys. Using static fallback."
                    )
            except Exception as e_retry:
                logger.error(
                    "Error generating dynamic affiliate playbook: "
                    f"{e_retry}. Using static fallback."
                )

    # Format the products into the preparation markdown string
    products_list = []
    for p in products:
        price_str = f" ({p['price']})" if p.get("price") else ""
        name_link = f"**[{p['name']}]({p['link']})**"
        products_list.append(f"- {name_link}{price_str}: {p['benefit']}")

    prep_str = (
        "To supercharge your setup for high-quality production, "
        "consider the following recommended gear and peripherals:\n\n"
        + "\n".join(products_list)
    )

    # If we have preceding recommendations, inject them in the preparation
    if previous_playbooks:
        prep_str += "\n\n### Prior Stream Setup Recommendations:\n"
        for p in previous_playbooks:
            prep_str += f"- For **{p['game']}**: {p['preparation']}\n"

    return {
        "game": "Stream Gear & Setup",
        "category": "Setup Recommendations",
        "score": 100,
        "platform": "Universal (Improves Stream Quality & Engagement)",
        "hook": hook,
        "advice": advice,
        "preparation": prep_str,
        "news": [],
        "stream_goal": stream_goal,
        "generated_at": generated_at_iso,
        "formatted_time": formatted_time,
        "twitch_viewers": 0,
        "youtube_viewers": 0,
        "total_viewers": 0,
        "is_affiliate": True,
    }


def calculate_compatibility_score(
    g: dict, vibe: str, scale: str, duration: float
) -> float:
    """Calculates compatibility score (50-100) for a game based on gamer profile."""
    comp_score = 50.0  # baseline compatibility

    category = g.get("category", "").lower()
    title = g.get("title", "").lower()

    # Vibe Match
    vibe_type = vibe.lower()
    if vibe_type == "chill":
        if (
            any(
                term in category
                for term in [
                    "sandbox",
                    "rpg",
                    "sim",
                    "strategy",
                    "adventure",
                    "puzzle",
                    "indie",
                    "card",
                ]
            )
            or "hades" in title
        ):
            comp_score += 25
    elif vibe_type == "competitive":
        if any(
            term in category
            for term in [
                "fps",
                "battle royale",
                "moba",
                "rpg",
                "roguelike",
                "fighting",
                "sports",
                "action",
            ]
        ):
            comp_score += 25
    elif vibe_type == "community":
        if any(
            term in category
            for term in [
                "sandbox",
                "fps",
                "party",
                "survival",
                "simulation",
                "co-op",
                "multiplayer",
            ]
        ):
            comp_score += 25
    elif vibe_type == "story":
        if any(
            term in category
            for term in [
                "rpg",
                "adventure",
                "roguelike",
                "story",
                "horror",
                "action",
                "narrative",
            ]
        ):
            comp_score += 25

    # Scale Match (viewership thresholds)
    total_viewers = (g.get("twitch_viewers", 0) or 0) + (
        g.get("youtube_viewers", 0) or 0
    )
    if total_viewers == 0:
        total_viewers = g.get("avg_viewers", 0) or 0

    scale_type = scale.lower()
    if scale_type == "starting":
        # Prefer low-saturation directories (viewers < 80k)
        if total_viewers < 80000:
            comp_score += 20
        elif total_viewers < 150000:
            comp_score += 10
    elif scale_type == "affiliate":
        # Prefer medium directories (80k - 200k)
        if 80000 <= total_viewers < 200000:
            comp_score += 20
        else:
            comp_score += 10
    elif scale_type == "partner":
        # Prefer high-saturation directories (viewers >= 150k)
        if total_viewers >= 150000:
            comp_score += 20
        elif total_viewers >= 80000:
            comp_score += 10

    # Duration Match
    avg_len = g.get("avg_length_hours", 3.0)
    len_diff = abs(avg_len - duration)
    if len_diff <= 1.0:
        comp_score += 15
    elif len_diff <= 2.0:
        comp_score += 10

    # Add basic weight from original advisory score
    comp_score += g.get("score", 50) / 10.0

    return min(100.0, comp_score)


def generate_stream_playbook(
    vibe: str,
    scale: str,
    duration: float,
    stream_goal: str = "growth",
    api_key: str = None,
    model: str = None,
    game: str = None,
    custom_context: str = "",
) -> dict:
    """
    Generates a personalized stream playbook for the best matching games.
    """
    from ag_kaggle_5day.agents.advisor import (
        NEWS_CACHE_FILE,
        get_affiliate_playbook,
        get_cached_games,
        parse_json_response,
        parse_news_markdown,
        safe_generate_content,
    )

    logger.info(
        f"Generating stream playbook for vibe={vibe}, scale={scale}, "
        f"duration={duration}h"
    )
    games = get_cached_games()

    # 1. Scoring algorithm
    scored_games = []
    for g in games:
        comp_score = calculate_compatibility_score(g, vibe, scale, duration)
        scored_games.append((comp_score, g))

    if game:
        matched_game = None
        for g in games:
            if g.get("title", "").lower() == game.lower():
                matched_game = dict(g)
                break
        if not matched_game:
            matched_game = {
                "title": game,
                "category": "Custom",
                "twitch_viewers": 0,
                "youtube_viewers": 0,
                "avg_length_hours": duration,
                "score": 50,
                "tier": "custom",
                "custom": True,
            }
        matched_game["playbook_score"] = calculate_compatibility_score(
            matched_game, vibe, scale, duration
        )
        top_matches = [matched_game]
    else:
        # Separate custom and non-custom games
        custom_games = []
        non_custom_scored = []

        for comp_score, g in scored_games:
            g_with_score = dict(g)
            g_with_score["playbook_score"] = comp_score

            # Check if it is a custom game
            if g.get("custom") or g.get("tier") == "custom":
                custom_games.append(g_with_score)
            else:
                non_custom_scored.append((comp_score, g_with_score))

        # Sort and take top 3 non-custom matches
        non_custom_scored.sort(key=lambda x: x[0], reverse=True)
        top_non_custom = [item[1] for item in non_custom_scored[:3]]

        # Combine (top 3 best-fit + all custom games)
        top_matches = top_non_custom + custom_games

    # 2. Call Gemini (or use offline fallback if no API key)
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    import random

    if not game and len(top_matches) >= 2:
        insert_idx = random.randint(2, len(top_matches))
    elif not game:
        insert_idx = len(top_matches)
    else:
        insert_idx = -1
    affiliate_appended = False

    playbooks = []
    for idx, g in enumerate(top_matches):
        if not game and idx == insert_idx and not affiliate_appended:
            try:
                from ag_kaggle_5day.agents.scraper import load_model_config

                config = load_model_config()
                if config.get("enable_affiliate_playbook", False):
                    aff_playbook = get_affiliate_playbook(
                        vibe=vibe,
                        scale=scale,
                        stream_goal=stream_goal,
                        api_key=api_key,
                        previous_playbooks=list(playbooks),
                    )
                    playbooks.append(aff_playbook)
                    affiliate_appended = True
            except Exception as aff_err:
                logger.error(f"Error appending affiliate playbook: {aff_err}")
        title = g["title"]
        category = g["category"]
        twitch_v = g.get("twitch_viewers", 0) or 0
        youtube_v = g.get("youtube_viewers", 0) or 0
        total_v = twitch_v + youtube_v

        # Get news for this game if available
        news_data = parse_news_markdown(NEWS_CACHE_FILE)
        game_news = news_data.get(title.lower(), {}).get("articles", [])
        news_list = []
        if game_news:
            for art in game_news[:2]:
                news_list.append(
                    {
                        "title": art.get("title", ""),
                        "summary": art.get("summary", ""),
                        "url": art.get("url", "#"),
                    }
                )

        news_str = ""
        if game_news:
            news_str = "\n".join(
                [f"- {art.get('title')}: {art.get('summary')}" for art in game_news[:2]]
            )
        else:
            news_str = "- No recent news updates."

        category_lower = category.lower()
        title_lower = title.lower()
        if "sandbox" in category_lower or "minecraft" in title_lower:
            prep_val = (
                "Prepare your sandbox world and seed beforehand. Check that "
                "custom textures/mods are loaded and update your overlays so "
                "they do not block inventory or crafting screens."
            )
        elif (
            "rpg" in category_lower
            or "elden ring" in title_lower
            or "story" in category_lower
        ):
            prep_val = (
                "Test your audio balance so dialogue is crisp and clear over "
                "game music. Prepare a short recap of past game events for the "
                "audience, and configure a warm camera angle."
            )
        elif (
            "fps" in category_lower
            or "valorant" in title_lower
            or "competitive" in vibe.lower()
        ):
            prep_val = (
                "Set game settings to maximize frame rate (144Hz+). Configure "
                "stream latency to 'low' for real-time play-by-play interaction, "
                "and have a Stream Deck ready to trigger replays."
            )
        elif "racing" in category_lower or "forza" in title_lower:
            prep_val = (
                "Check wheel calibration or controller response. Set up engine "
                "sound filters to avoid drowning out your microphone, and prepare "
                "an on-screen speed/input overlay."
            )
        else:
            prep_val = (
                "Optimize stream latency settings for real-time Q&A. Ensure "
                "stream overlays are configured with clean boundaries, and "
                "perform a microphone sound check before going live."
            )

        now_local = datetime.datetime.now(datetime.timezone.utc).astimezone()
        generated_at_iso = now_local.isoformat()
        formatted_time = now_local.strftime("%I:%M %p %Z")

        if not api_key:
            plat_rec = "Twitch" if twitch_v >= youtube_v else "YouTube"
            playbooks.append(
                {
                    "game": title,
                    "category": category,
                    "score": min(100, round(g.get("playbook_score", 80))),
                    "platform": f"{plat_rec} (based on current audience numbers)",
                    "hook": (
                        f"Host a themed stream for {title} focusing on "
                        f"{vibe} style gameplay."
                    ),
                    "advice": (
                        f"Set up clean UI layouts. Stream for {duration} hours. "
                        f"Interact closely with viewers to optimize your {scale} "
                        f"channel growth with {stream_goal} goal."
                    ),
                    "preparation": prep_val,
                    "news": news_list,
                    "stream_goal": stream_goal,
                    "generated_at": generated_at_iso,
                    "formatted_time": formatted_time,
                    "twitch_viewers": twitch_v,
                    "youtube_viewers": youtube_v,
                    "total_viewers": total_v,
                }
            )
            continue

        system_instruction = (
            "You are an expert streaming playbook designer. Based on the "
            "video game, stream vibe, channel scale, duration, and stream goal, "
            "generate highly strategic, brief, actionable streaming playbooks. "
            "Do NOT provide generic game descriptions.\n"
            "Produce output in JSON format with exactly four keys:\n"
            "- 'platform': a string representing the target platform "
            "recommendation and 1-sentence reason (Twitch, YouTube, or Both).\n"
            "- 'hook': a 1-sentence audience engagement hook/stream concept "
            "(e.g. challenges, interactive elements, overlay ideas).\n"
            "- 'advice': a detailed 2-3 sentence strategic plan specifying "
            "target hours, standing out, and growing based on current game "
            "status and recent news.\n"
            "- 'preparation': a detailed 2-3 sentence guide on how to prepare "
            "for this stream, focusing on specific hardware (e.g. lighting, "
            "microphone), software (e.g. overlays, plugins), or peripherals "
            "suitable for this game and vibe.\n"
            "Do NOT wrap output in markdown code fences, return only the raw "
            "JSON object string."
        )

        # Retrieve similar past playbooks and news articles for RAG context
        from ag_kaggle_5day.agents.gcp_storage import (
            search_similar_news,
            search_similar_playbooks,
        )

        past_playbooks_context = ""
        try:
            similar_pbs = search_similar_playbooks(title, api_key, limit=1)
            similar_news_items = search_similar_news(title, api_key, limit=1)
            parts = []
            if similar_pbs:
                parts.append(
                    "Past Hook: "
                    f"{similar_pbs[0].get('hook')} | Past Advice: "
                    f"{similar_pbs[0].get('advice')}"
                )
            if similar_news_items:
                parts.append(
                    "Past News: "
                    f"{similar_news_items[0].get('headline')} - "
                    f"{similar_news_items[0].get('summary')}"
                )
            if parts:
                past_playbooks_context = (
                    "\n### Past Reference Memories:\n"
                    + "\n".join(f"- {p}" for p in parts)
                    + "\n"
                )
        except Exception as e:
            logger.debug(
                f"Failed to retrieve past memories for playbook '{title}': {e}"
            )

        context_str = ""
        if custom_context and custom_context.strip():
            context_str = f"Custom Gamer/Channel Context: {custom_context.strip()}\n"

        prompt = (
            f"Game: {title} ({category})\n"
            f"Metrics: Twitch Viewers={twitch_v:,} | "
            f"YouTube Viewers={youtube_v:,} | Total Viewers={total_v:,}\n"
            f"Gamer Profile: Vibe={vibe} | Channel Scale={scale} | "
            f"Stream Duration={duration} hours | Stream Goal={stream_goal}\n"
            f"{context_str}"
            f"Current Local Time: {formatted_time}\n"
            f"Recent News Context:\n{news_str}\n"
            f"{past_playbooks_context}\n"
            "Generate the strategic playbook in the requested JSON format."
        )

        try:
            response = safe_generate_content(
                api_key=api_key,
                model=model,
                contents=prompt,
                system_instruction=system_instruction,
                use_google_search=False,
            )
            data = parse_json_response(response.text)
            if (
                isinstance(data, dict)
                and "platform" in data
                and "hook" in data
                and "advice" in data
                and "preparation" in data
            ):
                playbook_item = {
                    "game": title,
                    "category": category,
                    "score": min(100, round(g.get("playbook_score", 80))),
                    "platform": data["platform"],
                    "hook": data["hook"],
                    "advice": data["advice"],
                    "preparation": data["preparation"],
                    "news": news_list,
                    "stream_goal": stream_goal,
                    "generated_at": generated_at_iso,
                    "formatted_time": formatted_time,
                    "twitch_viewers": twitch_v,
                    "youtube_viewers": youtube_v,
                    "total_viewers": total_v,
                }
                playbooks.append(playbook_item)

                # Store playbook vector in Firestore
                from ag_kaggle_5day.agents.gcp_storage import store_playbook_vector

                text_content = (
                    f"Game: {title}. Category: {category}. "
                    f"Vibe: {vibe}. Scale: {scale}. Duration: {duration} hours. "
                    f"Stream Goal: {stream_goal}. "
                    f"Platform Recommendation: {data['platform']}. "
                    f"Audience Engagement Hook: {data['hook']}. "
                    f"Strategic Advice: {data['advice']}. "
                    f"Preparation: {data['preparation']}"
                )
                try:
                    store_playbook_vector(playbook_item, text_content, api_key)
                except Exception as store_err:
                    logger.error(
                        f"Failed to store playbook vector for {title}: {store_err}"
                    )
            else:
                raise ValueError(
                    "JSON parsing succeeded but missing required playbook keys."
                )
        except Exception as e:
            logger.error(f"Failed to generate playbook via Gemini for '{title}': {e}")
            plat_rec = "Twitch" if twitch_v >= youtube_v else "YouTube"
            playbooks.append(
                {
                    "game": title,
                    "category": category,
                    "score": min(100, round(g.get("playbook_score", 80))),
                    "platform": f"{plat_rec} (local fallback)",
                    "hook": (
                        f"Host a themed stream for {title} focusing on "
                        f"{vibe} style gameplay."
                    ),
                    "advice": (
                        "Interact closely with viewers. Stream for "
                        f"{duration} hours to optimize your {scale} channel growth."
                    ),
                    "preparation": prep_val,
                    "news": news_list,
                    "stream_goal": stream_goal,
                    "generated_at": generated_at_iso,
                    "formatted_time": formatted_time,
                    "twitch_viewers": twitch_v,
                    "youtube_viewers": youtube_v,
                    "total_viewers": total_v,
                }
            )

    if not game and not affiliate_appended and insert_idx >= 0:
        try:
            from ag_kaggle_5day.agents.scraper import load_model_config

            config = load_model_config()
            if config.get("enable_affiliate_playbook", False):
                aff_playbook = get_affiliate_playbook(
                    vibe=vibe,
                    scale=scale,
                    stream_goal=stream_goal,
                    api_key=api_key,
                    previous_playbooks=list(playbooks),
                )
                playbooks.append(aff_playbook)
                affiliate_appended = True
        except Exception as aff_err:
            logger.error(f"Error appending affiliate playbook at end: {aff_err}")

    return {
        "vibe": vibe,
        "scale": scale,
        "duration": duration,
        "stream_goal": stream_goal,
        "playbooks": playbooks,
    }


def _run_workflow_in_thread(
    runner, input_str: str, user_id: str, session_id: str
) -> list:
    """Helper to execute Google ADK workflow run_debug within a separate thread

    to prevent blocking the main asyncio event loop.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            runner.run_debug(
                input_str,
                user_id=user_id,
                session_id=session_id,
                quiet=True,
            )
        )
    finally:
        loop.close()


async def get_or_generate_medium_form_article(
    streamer_handle: str, api_key: str | None = None, model: str | None = None
) -> dict:
    """Executes the medium-form article workflow using the InMemoryRunner.
    Checks the Firestore cache first. If cached, no API key is required.
    If not cached, enforces that a valid api_key is provided for generation.
    """
    import logging

    from ag_kaggle_5day.agents.gcp_storage import get_cached_medium_form_article

    logger = logging.getLogger("workflows")
    handle = streamer_handle.strip().lower()

    # 1. Check cache first
    cached = get_cached_medium_form_article(handle)
    if cached:
        logger.log(
            25,
            "[EXPOSE] Cache hit: Returning cached medium-form article "
            f"for streamer '{handle}'",
        )
        return cached

    # 2. Enforce personal API key for generation
    if not api_key or not api_key.strip():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Personal Gemini API Key is required to analyze streamer handles.",
        )

    logger.log(
        25,
        "[EXPOSE] Session initiated expose building request (medium-form) "
        f"for streamer '{handle}'",
    )

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import (
        medium_form_article_workflow,
    )

    runner = InMemoryRunner(node=medium_form_article_workflow)
    session_id = f"medium_session_{int(time.time())}"
    input_data = {"streamer_handle": handle, "model": model}

    # Set personal API key for execution environment
    os.environ["GEMINI_API_KEY"] = api_key.strip()

    import asyncio

    loop = asyncio.get_running_loop()
    events = await loop.run_in_executor(
        None,
        _run_workflow_in_thread,
        runner,
        json.dumps(input_data),
        "default_user",
        session_id,
    )
    if events and events[-1].output:
        res = events[-1].output
        if isinstance(res, dict) and "article" in res:
            return res["article"]

    raise RuntimeError("Failed to generate medium-form article via workflow.")


async def trigger_daily_expose_job(
    api_key: str, check_24h_interval: bool = False
) -> dict:
    """Executes the daily expose workflow using the InMemoryRunner."""
    import time

    if check_24h_interval:
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_latest_expose_article

            latest = get_latest_expose_article()
            if latest:
                latest_ts = latest.get("timestamp", 0.0)
                if isinstance(latest_ts, str):
                    try:
                        import datetime

                        dt = datetime.datetime.fromisoformat(
                            latest_ts.replace("Z", "+00:00")
                        )
                        latest_ts = dt.timestamp()
                    except Exception:
                        latest_ts = 0.0
                elif not isinstance(latest_ts, (int, float)):
                    latest_ts = 0.0

                age = time.time() - latest_ts
                if age < 23 * 3600:
                    logger.info(
                        "Daily Expose: Fresh expose exists "
                        f"(age: {age:.1f}s < 23h). Skipping execution."
                    )
                    return latest
        except Exception as check_err:
            logger.warning(
                "Daily Expose: Freshness check failed, proceeding to "
                f"generate: {check_err}"
            )

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import daily_expose_workflow

    runner = InMemoryRunner(node=daily_expose_workflow)
    session_id = f"expose_session_{int(time.time())}"
    input_data = {}

    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key

    import asyncio

    loop = asyncio.get_running_loop()
    events = await loop.run_in_executor(
        None,
        _run_workflow_in_thread,
        runner,
        json.dumps(input_data),
        "admin_system_task",
        session_id,
    )
    if events and events[-1].output:
        res = events[-1].output
        if isinstance(res, dict) and "article" in res:
            return res["article"]

    raise RuntimeError("Failed to run daily expose workflow.")
