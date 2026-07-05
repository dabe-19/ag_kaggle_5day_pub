import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from filelock import FileLock  # noqa: F401
from google.adk.workflow import START, JoinNode, RetryConfig, Workflow, node

from ag_kaggle_5day.agents.advisor import (
    NEWS_CACHE_FILE,
    _generate_comparison_report,
    _store,
    calculate_compatibility_score,
    get_cached_games,
    get_visible_trending_games,
    parse_news_markdown,
    prefetch_news_for_games,
)
from ag_kaggle_5day.agents.gcp_storage import (
    search_similar_comparison_reports,
    search_similar_news,
    search_similar_playbooks,
    store_comparison_report_vector,
    store_playbook_vector,
)
from ag_kaggle_5day.agents.scraper import (
    SPONSORED_GAMES,
    discover_top_games,
    parse_json_response,
    safe_generate_content,
    scrape_viewership_for_games,
)

logger = logging.getLogger("workflows")

# --- Retry Configurations ---
llm_retry_config = RetryConfig(max_attempts=3, initial_delay=2.0, backoff_factor=2.0)

# ===========================================================================
# 1. Comparative Report Workflow Nodes
# ===========================================================================


@node(name="scrape_custom_metrics")
def scrape_custom_metrics_node(node_input: Any) -> dict:
    """Scrapes metrics for custom games, discovers category-specific trending
    games, and merges with sponsored games.
    """
    custom_games = []
    category = "overall"
    visible_games = []
    if node_input and hasattr(node_input, "parts") and node_input.parts:
        try:
            data = json.loads(node_input.parts[0].text)
            if isinstance(data, dict):
                custom_games = data.get("custom_games", [])
                category = data.get("category", "overall")
                visible_games = data.get("visible_games", [])
        except Exception:
            pass
    elif isinstance(node_input, dict):
        custom_games = node_input.get("custom_games", [])
        category = node_input.get("category", "overall")
        visible_games = node_input.get("visible_games", [])
    elif isinstance(node_input, list):
        custom_games = node_input
    elif isinstance(node_input, str):
        try:
            data = json.loads(node_input)
            if isinstance(data, dict):
                custom_games = data.get("custom_games", [])
                category = data.get("category", "overall")
                visible_games = data.get("visible_games", [])
        except Exception:
            pass

    api_key = os.environ.get("GEMINI_API_KEY")
    search_model = None

    if visible_games:
        # Enforce using visible_games directly, enriched by cache metrics
        all_cached = get_cached_games()
        cached_by_title = {g["title"].lower(): g for g in all_cached}

        combined_games = []
        for vg in visible_games:
            title = vg.get("title")
            if not title:
                continue
            g_enriched = cached_by_title.get(title.lower())
            if not g_enriched:
                g_enriched = dict(vg)
            else:
                g_enriched = dict(g_enriched)
            if "tier" in vg:
                g_enriched["tier"] = vg["tier"]
            if "custom" in vg:
                g_enriched["custom"] = vg["custom"]
            combined_games.append(g_enriched)
    else:
        custom_results = []
        if custom_games:
            try:
                custom_results = scrape_viewership_for_games(
                    custom_games, api_key=api_key, model=search_model
                )
                for g in custom_results:
                    g["custom"] = True
                    g["tier"] = "custom"
            except Exception as e:
                logger.error(f"Error scraping custom metrics: {e}")

        # Discover trending games dynamically for the selected category
        trending = []
        try:
            trending = discover_top_games(
                api_key=api_key,
                model=search_model,
                category=category,
                limit=10,
            )
        except Exception as e:
            logger.error(f"Error discovering top games for category '{category}': {e}")

        # Fetch sponsored games (rebranded from staples)
        sponsored = []
        sponsored_titles = [g["title"] for g in SPONSORED_GAMES]
        try:
            sponsored = scrape_viewership_for_games(
                sponsored_titles, api_key=api_key, model=search_model
            )
            for g in sponsored:
                g["tier"] = "sponsored"
        except Exception as e:
            logger.error(f"Error scraping sponsored metrics: {e}")

        # Deduplicate trending > custom > sponsored
        seen_titles = set()
        combined_games = []
        for g in trending + custom_results + sponsored:
            key = g["title"].lower()
            if key not in seen_titles:
                seen_titles.add(key)
                combined_games.append(g)

    return {
        "combined_games": combined_games,
        "custom_games": custom_games,
        "category": category,
    }


@node(name="prefetch_news")
def prefetch_news_node(node_input: dict) -> dict:
    """Pre-fetches news articles for combined games asynchronously."""
    combined_games = node_input["combined_games"]
    api_key = os.environ.get("GEMINI_API_KEY")

    trending = [g for g in combined_games if g.get("tier") == "trending"]
    custom = [g for g in combined_games if g.get("custom") or g.get("tier") == "custom"]
    sponsored = [g for g in combined_games if g.get("tier") == "sponsored"]

    visible_trending = get_visible_trending_games(trending, limit=10)
    news_targets = []
    seen = set()
    for g in visible_trending + custom + sponsored:
        title = g.get("title", "").strip().lower()
        if title and title not in seen:
            seen.add(title)
            news_targets.append(g)

    try:
        # Asynchronous non-blocking pre-fetch using the background pool
        prefetch_news_for_games(news_targets, api_key=api_key)
    except Exception as e:
        logger.error(f"Error pre-fetching news: {e}")
    return node_input


@node(name="retrieve_past_reports")
def retrieve_past_reports_node(node_input: dict) -> dict:
    """Retrieves similar past comparison reports from Firestore for RAG context."""
    combined_games = node_input["combined_games"]
    api_key = os.environ.get("GEMINI_API_KEY")

    games_list = []
    for g in combined_games:
        games_list.append(f"- {g['title']} ({g['category']})")
    games_summary = "\n".join(games_list)

    past_reports_context = ""
    try:
        similar_reports = search_similar_comparison_reports(
            games_summary[:500], api_key, limit=1
        )
        if similar_reports:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(
                similar_reports[0].get("report_html", ""), "html.parser"
            )
            clean_text = soup.get_text(separator=" ").strip()
            past_reports_context = (
                f"\n### Reference Memory (Past Comparison Report Snippet):\n"
                f"{clean_text[:400]}...\n"
            )
    except Exception as e:
        logger.debug(f"Failed to retrieve past reports: {e}")

    node_input["past_reports_context"] = past_reports_context
    return node_input


join_metrics_and_rag = JoinNode(name="join_metrics_and_rag")


@node(name="generate_report", retry_config=llm_retry_config)
def generate_report_node(node_input: dict) -> dict:
    """Calls Gemini to generate the HTML report using merged metrics and news."""
    news_out = node_input["prefetch_news"]
    rag_out = node_input["retrieve_past_reports"]

    combined_games = news_out["combined_games"]
    custom_games = news_out["custom_games"]
    past_reports_context = rag_out["past_reports_context"]

    api_key = os.environ.get("GEMINI_API_KEY")
    analysis_model = None

    category = news_out.get("category", "overall")

    report = _generate_comparison_report(
        combined_games, api_key=api_key, model=analysis_model, category=category
    )
    return {
        "report": report,
        "custom_games": custom_games,
        "past_reports_context": past_reports_context,
        "category": category,
    }


@node(name="store_report")
def store_report_node(node_input: dict) -> str:
    """Stores the generated report in Firestore and updates the cached

    comparison report.
    """
    report = node_input["report"]
    custom_games = node_input["custom_games"]
    category = node_input.get("category", "overall")
    api_key = os.environ.get("GEMINI_API_KEY")

    try:
        store_comparison_report_vector(report, custom_games, api_key)
    except Exception as store_err:
        logger.error(f"Failed to store custom comparison report vector: {store_err}")

    data = {
        "custom_games": custom_games,
        "category": category,
        "report": report,
        "status": "success",
        "generated_at": time.time(),
    }
    try:
        from ag_kaggle_5day.app import store_custom_report_state

        store_custom_report_state(custom_games, category, data)
    except Exception as store_err:
        logger.error(f"Failed to store custom report cache state: {store_err}")

    if not custom_games:
        _store.comparison_report = report

    return report


# ===========================================================================
# 2. Stream Playbook Workflow Nodes
# ===========================================================================


@node(name="select_top_games")
def select_top_games_node(node_input: Any) -> dict:
    """Scores cached games against gamer profile and selects top matches."""
    vibe = "chill"
    scale = "starting"
    duration = 3.0
    stream_goal = "growth"
    game_name = None
    custom_context = ""
    if node_input and hasattr(node_input, "parts") and node_input.parts:
        try:
            data = json.loads(node_input.parts[0].text)
            if isinstance(data, dict):
                vibe = data.get("vibe", "chill")
                scale = data.get("scale", "starting")
                duration = float(data.get("duration", 3.0))
                stream_goal = data.get("stream_goal", "growth")
                game_name = data.get("game")
                custom_context = data.get("custom_context") or ""
        except Exception:
            pass
    elif isinstance(node_input, dict):
        vibe = node_input.get("vibe", "chill")
        scale = node_input.get("scale", "starting")
        duration = float(node_input.get("duration", 3.0))
        stream_goal = node_input.get("stream_goal", "growth")
        game_name = node_input.get("game")
        custom_context = node_input.get("custom_context") or ""
    elif isinstance(node_input, str):
        try:
            data = json.loads(node_input)
            if isinstance(data, dict):
                vibe = data.get("vibe", "chill")
                scale = data.get("scale", "starting")
                duration = float(data.get("duration", 3.0))
                stream_goal = data.get("stream_goal", "growth")
                game_name = data.get("game")
                custom_context = data.get("custom_context") or ""
        except Exception:
            pass

    games = get_cached_games()

    if game_name:
        matched_game = None
        for g in games:
            if g.get("title", "").lower() == game_name.lower():
                matched_game = dict(g)
                break
        if not matched_game:
            matched_game = {
                "title": game_name,
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
        scored_games = []
        for g in games:
            comp_score = calculate_compatibility_score(g, vibe, scale, duration)
            scored_games.append((comp_score, g))

        custom_games = []
        non_custom_scored = []
        for comp_score, g in scored_games:
            g_with_score = dict(g)
            g_with_score["playbook_score"] = comp_score
            if g.get("custom") or g.get("tier") == "custom":
                custom_games.append(g_with_score)
            else:
                non_custom_scored.append((comp_score, g_with_score))

        non_custom_scored.sort(key=lambda x: x[0], reverse=True)
        top_non_custom = [item[1] for item in non_custom_scored[:3]]
        top_matches = top_non_custom + custom_games

    return {
        "vibe": vibe,
        "scale": scale,
        "duration": duration,
        "stream_goal": stream_goal,
        "top_matches": top_matches,
        "game": game_name,
        "custom_context": custom_context,
    }

    return {
        "vibe": vibe,
        "scale": scale,
        "duration": duration,
        "stream_goal": stream_goal,
        "top_matches": top_matches,
    }


def generate_and_store_single_playbook_sync(
    vibe: str,
    scale: str,
    duration: float,
    stream_goal: str,
    g: dict,
    api_key: str,
    custom_context: str = "",
) -> dict:
    """Helper that generates a playbook for a single game and uploads it

    to Firestore.
    """
    title = g["title"]
    category = g["category"]
    twitch_v = g.get("twitch_viewers", 0) or 0
    youtube_v = g.get("youtube_viewers", 0) or 0
    total_v = twitch_v + youtube_v

    # Generate timestamping details
    import datetime

    now_local = datetime.datetime.now(datetime.timezone.utc).astimezone()
    generated_at_iso = now_local.isoformat()
    formatted_time = now_local.strftime("%I:%M %p %Z")

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

    if not api_key:
        plat_rec = "Twitch" if twitch_v >= youtube_v else "YouTube"
        return {
            "game": title,
            "category": category,
            "score": min(100, round(g.get("playbook_score", 80))),
            "platform": f"{plat_rec} (local fallback)",
            "hook": (
                f"Host a themed stream for {title} focusing on {vibe} style gameplay."
            ),
            "advice": (
                f"Interact closely with viewers. Stream for {duration} "
                f"hours to optimize your {scale} channel growth "
                f"with {stream_goal} goal."
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

    past_playbooks_context = ""
    try:
        similar_pbs = search_similar_playbooks(title, api_key, limit=1)
        similar_news_items = search_similar_news(title, api_key, limit=1)
        parts = []
        if similar_pbs:
            parts.append(
                f"Past Hook: {similar_pbs[0].get('hook')} | "
                f"Past Advice: {similar_pbs[0].get('advice')}"
            )
        if similar_news_items:
            parts.append(
                f"Past News: {similar_news_items[0].get('headline')} - "
                f"{similar_news_items[0].get('summary')}"
            )
        if parts:
            past_playbooks_context = (
                "\n### Past Reference Memories:\n"
                + "\n".join(f"- {p}" for p in parts)
                + "\n"
            )
    except Exception as e:
        logger.debug(f"Failed to retrieve past memories for playbook '{title}': {e}")

    context_str = ""
    if custom_context and custom_context.strip():
        context_str = f"Custom Gamer/Channel Context: {custom_context.strip()}\n"

    # Query Firestore for streamers who have the target game in their top_games
    streamer_context = ""
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs_client = get_firestore_client()
        if fs_client:
            # Fetch Vibe Tribe assignments
            corr_doc = (
                fs_client.collection("streamer_correlation").document("current").get()
            )
            tribe_assignments = {}
            vibe_tribes = {}
            convergence_velocity = []
            if corr_doc.exists:
                corr_data = corr_doc.to_dict()
                tribe_assignments = corr_data.get("tribe_assignments", {})
                vibe_tribes = corr_data.get("vibe_tribes", {})
                convergence_velocity = corr_data.get("convergence_velocity", [])

            docs = fs_client.collection("streamer_profiles").stream()
            matching_streamers = []
            for doc in docs:
                p = doc.to_dict()
                games = [g.lower().strip() for g in p.get("top_games", [])]
                if title.lower().strip() in games:
                    matching_streamers.append(p)

            if matching_streamers:
                lines = [
                    "\n### Successful Streamers Playing This Game "
                    "(Real Reference Context):"
                ]
                for ms in matching_streamers[
                    :3
                ]:  # Limit to top 3 to manage prompt token size
                    handle = ms.get("streamer_handle", "Unknown")
                    arch = ms.get("archetype_cluster", "Unknown")
                    time_active = ms.get("time_active_cluster", "Unknown")
                    status = ms.get("fabric_status", "preliminary")

                    # Fetch average messages/minute from timeseries cache if available
                    mpm = 0.0
                    ts_doc = (
                        fs_client.collection("streamer_analytics_timeseries")
                        .document(handle.lower())
                        .get()
                    )
                    if ts_doc.exists:
                        mpm = ts_doc.to_dict().get("average_msg_per_minute", 0.0)

                    # Look up Vibe Tribe membership
                    tribe_label = "Unknown Tribe"
                    if tribe_assignments and vibe_tribes:
                        t_id = str(tribe_assignments.get(handle, ""))
                        t_info = vibe_tribes.get(t_id, {})
                        tribe_label = t_info.get("label", "Unknown Tribe")

                    # Extract rolling sentiment score and chat volatility
                    adaptive = ms.get("adaptive_metrics", {})
                    rolling_sentiment = adaptive.get("rolling_sentiment_score", 0.0)
                    chat_vol = adaptive.get("chat_volatility", 0.0)

                    # Extract peer connections
                    peer_details = []
                    raw_peer_details = ms.get("peer_details")
                    if raw_peer_details and isinstance(raw_peer_details, list):
                        for p_conn in raw_peer_details:
                            if isinstance(p_conn, dict):
                                h_val = p_conn.get("handle") or p_conn.get("streamer")
                                score_val = p_conn.get("similarity") or p_conn.get(
                                    "combined_score"
                                )
                                why_val = p_conn.get("why") or p_conn.get("tag")
                                if h_val:
                                    vel_str = ""
                                    for link in convergence_velocity:
                                        sa = link.get("streamer_a", "").lower()
                                        sb = link.get("streamer_b", "").lower()
                                        h_lower = h_val.lower()
                                        curr_lower = handle.lower()
                                        if (sa == curr_lower and sb == h_lower) or (
                                            sb == curr_lower and sa == h_lower
                                        ):
                                            v_val = link.get("velocity", 0.0)
                                            a_val = link.get("acceleration", 0.0)
                                            vel_str = (
                                                f", velocity: {v_val:.2f}/h, "
                                                f"acceleration: {a_val:.2f}/h²"
                                            )
                                            break

                                    detail_str = f"@{h_val}"
                                    if score_val is not None:
                                        detail_str += (
                                            f" (similarity: {score_val:+.2f}{vel_str}"
                                        )
                                        if why_val:
                                            detail_str += f", {why_val}"
                                        detail_str += ")"
                                    elif why_val:
                                        detail_str += f" ({why_val}{vel_str})"
                                    elif vel_str:
                                        detail_str += f" ({vel_str[2:]})"
                                    peer_details.append(detail_str)
                            elif isinstance(p_conn, str):
                                peer_details.append(f"@{p_conn}")
                    else:
                        peers = ms.get("peer_connections", [])
                        if isinstance(peers, list):
                            for p_conn in peers:
                                if isinstance(p_conn, dict):
                                    h_val = p_conn.get("streamer") or p_conn.get(
                                        "handle"
                                    )
                                    tag_val = p_conn.get("tag") or p_conn.get("why", "")
                                    score_val = p_conn.get(
                                        "combined_score"
                                    ) or p_conn.get("similarity", 0.0)
                                    if h_val:
                                        vel_str = ""
                                        for link in convergence_velocity:
                                            sa = link.get("streamer_a", "").lower()
                                            sb = link.get("streamer_b", "").lower()
                                            h_lower = h_val.lower()
                                            curr_lower = handle.lower()
                                            if (sa == curr_lower and sb == h_lower) or (
                                                sa == h_lower and sb == curr_lower
                                            ):
                                                v_val = link.get("velocity", 0.0)
                                                a_val = link.get("acceleration", 0.0)
                                                vel_str = (
                                                    f", velocity: {v_val:.2f}/h, "
                                                    f"acceleration: {a_val:.2f}/h²"
                                                )
                                                break
                                        peer_details.append(
                                            f"@{h_val} ({tag_val}{vel_str}, "
                                            f"score: {score_val:+.2f})"
                                        )
                                elif isinstance(p_conn, str):
                                    peer_details.append(f"@{p_conn}")

                    peer_details_str = (
                        ", ".join(peer_details) if peer_details else "None"
                    )

                    # Extract composite chat summary
                    comp_summary = ms.get(
                        "composite_chat_summary", "No summary available."
                    )

                    lines.append(
                        f"- **{handle}**:\n"
                        f"  - Vibe Tribe: {tribe_label}\n"
                        f"  - Archetype: {arch}\n"
                        f"  - Active Hours: {time_active}\n"
                        f"  - Chat Speed (Historical Mean): {mpm} messages/minute\n"
                        f"  - Chat Volatility: {chat_vol:.2f} | "
                        f"Sentiment: {rolling_sentiment:+.2f}\n"
                        f"  - Peer Connections: {peer_details_str}\n"
                        f'  - Qualitative Chat Summary: "{comp_summary}"\n'
                        f"  - Profile Status: {status}"
                    )
                streamer_context = "\n".join(lines) + "\n"
    except Exception as e:
        logger.warning(f"Failed to fetch matching streamers for playbook context: {e}")

    # Fetch game sentiment metrics
    game_sentiment_str = ""
    try:
        from ag_kaggle_5day.agents.advisor import get_game_sentiment_metrics

        game_sentiment_data = get_game_sentiment_metrics(title)
        if game_sentiment_data:
            if isinstance(game_sentiment_data, list) and len(game_sentiment_data) > 0:
                game_sentiment = game_sentiment_data[0]
            elif isinstance(game_sentiment_data, dict):
                game_sentiment = game_sentiment_data
            else:
                game_sentiment = None

            if game_sentiment and isinstance(game_sentiment, dict):
                avg_speed = game_sentiment.get("avg_msg_per_minute")
                if avg_speed is None:
                    avg_speed = game_sentiment.get("chat_speed", 0.0)

                archetypes_val = game_sentiment.get("archetypes", "")
                if isinstance(archetypes_val, list):
                    archetypes_str = ", ".join(archetypes_val)
                else:
                    archetypes_str = str(archetypes_val)

                game_sentiment_str = (
                    "\n### Game Sentiment Analytics:\n"
                    f"- Sentiment Breakdown: "
                    f"Positive={game_sentiment.get('positive_ratio', 0.0):.1%}, "
                    f"Neutral={game_sentiment.get('neutral_ratio', 0.0):.1%}, "
                    f"Negative={game_sentiment.get('negative_ratio', 0.0):.1%}, "
                    f"Mixed={game_sentiment.get('mixed_ratio', 0.0):.1%}\n"
                    f"- Average Chat Speed: "
                    f"{avg_speed:.1f} messages/minute\n"
                    f"- Dominant Archetypes: {archetypes_str}\n"
                )
    except Exception as e:
        logger.warning(
            f"Failed to fetch game sentiment metrics for playbook context: {e}"
        )

    prompt = (
        f"Game: {title} ({category})\n"
        f"Metrics: Twitch Viewers={twitch_v:,} | "
        f"YouTube Viewers={youtube_v:,} | Total Viewers={total_v:,}\n"
        f"Gamer Profile: Vibe={vibe} | Channel Scale={scale} | "
        f"Stream Duration={duration} hours | Stream Goal={stream_goal}\n"
        f"{context_str}"
        f"{game_sentiment_str}"
        f"{streamer_context}"
        f"Current Local Time: {formatted_time}\n"
        f"Recent News Context:\n{news_str}\n"
        f"{past_playbooks_context}\n"
        "Generate the strategic playbook in the requested JSON format."
    )

    system_instruction = (
        "You are an expert streaming playbook designer. Based on the "
        "video game, stream vibe, channel scale, duration, and stream goal, "
        "generate highly detailed, data-grounded, strategic, and "
        "actionable streaming playbooks. "
        "Do NOT provide generic game descriptions.\n"
        "Produce output in JSON format with exactly four keys:\n"
        "- 'platform': a string representing the target platform "
        "recommendation and detailed reasoning (Twitch, YouTube, or Both).\n"
        "- 'hook': a creative audience engagement hook/stream concept "
        "(e.g. challenges, interactive elements, overlay ideas).\n"
        "- 'advice': a detailed, comprehensive strategic plan specifying "
        "target hours, standing out, and growing based on current game "
        "status and recent news. Include specific collaboration or raid "
        "recommendations targeting streamers within the same Vibe Tribe "
        "cluster or connected clusters. Use the provided peer correlation metrics "
        "to differentiate your advice: recommend 'Safe Vibe Anchors' "
        "(high static similarity for stable co-streaming) and "
        "'Growth Catalysts' (positive velocity and acceleration for "
        "high-momentum viral growth spikes).\n"
        "- 'preparation': a detailed guide on how to prepare "
        "for this stream, focusing on specific hardware (e.g. lighting, "
        "microphone), software (e.g. overlays, plugins), or peripherals "
        "suitable for this game and vibe.\n"
        "Do NOT wrap output in markdown code fences, return only the raw "
        "JSON object string."
    )

    try:
        response = safe_generate_content(
            api_key=api_key,
            model=None,
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
            return playbook_item
        else:
            raise ValueError(
                "JSON parsing succeeded but missing required playbook keys."
            )
    except Exception as e:
        logger.error(f"Failed to generate playbook via Gemini for '{title}': {e}")
        plat_rec = "Twitch" if twitch_v >= youtube_v else "YouTube"
        return {
            "game": title,
            "category": category,
            "score": min(100, round(g.get("playbook_score", 80))),
            "platform": f"{plat_rec} (local fallback)",
            "hook": (
                f"Host a themed stream for {title} focusing on {vibe} style gameplay."
            ),
            "advice": (
                f"Interact closely with viewers. Stream for {duration} "
                f"hours to optimize your {scale} channel growth."
            ),
            "preparation": prep_val,
            "news": news_list,
        }


@node(name="generate_playbooks_parallel", retry_config=llm_retry_config)
def generate_playbooks_parallel_node(node_input: dict) -> dict:
    """Generates playbooks for all selected games in parallel using

    ThreadPoolExecutor.
    """
    vibe = node_input["vibe"]
    scale = node_input["scale"]
    duration = node_input["duration"]
    stream_goal = node_input["stream_goal"]
    top_matches = node_input["top_matches"]
    custom_context = node_input.get("custom_context", "")

    api_key = os.environ.get("GEMINI_API_KEY")

    playbooks = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(top_matches), 4))) as executor:
        futures = [
            executor.submit(
                generate_and_store_single_playbook_sync,
                vibe,
                scale,
                duration,
                stream_goal,
                game,
                api_key,
                custom_context,
            )
            for game in top_matches
        ]
        for future in futures:
            try:
                playbooks.append(future.result())
            except Exception as err:
                logger.error(f"Parallel playbook generation thread failed: {err}")

    node_input["playbooks"] = playbooks
    return node_input


@node(name="collect_playbooks")
def collect_playbooks_node(node_input: dict) -> dict:
    """Collects and shapes the final playbook response."""
    playbooks = list(node_input.get("playbooks", []))

    # Append affiliate playbook if enabled
    try:
        import random

        from ag_kaggle_5day.agents.advisor import get_affiliate_playbook
        from ag_kaggle_5day.agents.scraper import load_model_config

        config = load_model_config()
        if config.get("enable_affiliate_playbook", False):
            api_key = os.environ.get("GEMINI_API_KEY")
            vibe = node_input.get("vibe", "chill")
            scale = node_input.get("scale", "starting")
            stream_goal = node_input.get("stream_goal", "growth")

            # Determine random insertion index (except if a single game
            # lookup was requested)
            game_req = node_input.get("game")
            if not game_req:
                if len(playbooks) >= 2:
                    insert_idx = random.randint(2, len(playbooks))
                else:
                    insert_idx = len(playbooks)

                # Preceding playbooks context
                previous_playbooks = playbooks[:insert_idx]

                affiliate_playbook_dict = get_affiliate_playbook(
                    vibe=vibe,
                    scale=scale,
                    stream_goal=stream_goal,
                    api_key=api_key,
                    previous_playbooks=previous_playbooks,
                )

                # Insert at the random position
                playbooks.insert(insert_idx, affiliate_playbook_dict)
    except Exception as aff_err:
        logger.error(f"Error appending affiliate playbook in workflow: {aff_err}")

    return {
        "vibe": node_input["vibe"],
        "scale": node_input["scale"],
        "duration": node_input["duration"],
        "playbooks": playbooks,
    }


# ===========================================================================
# 3. Graph/Workflow Definitions
# ===========================================================================

comparative_report_workflow = None

stream_playbook_workflow = Workflow(
    name="stream_playbook_workflow",
    edges=[
        (START, select_top_games_node),
        (select_top_games_node, generate_playbooks_parallel_node),
        (generate_playbooks_parallel_node, collect_playbooks_node),
    ],
)


# ===========================================================================
# 4. Medium-Form Article Workflow Nodes
# ===========================================================================


def find_peers_for_streamer(streamer: str, dossier_text: str = "") -> list[str]:
    """Finds peer streamers in the same category from the dashboard cache."""
    from ag_kaggle_5day.agents.advisor import get_cached_games

    streamer_lower = streamer.strip().lower()
    cached_games = get_cached_games()

    # 1. Search if the streamer is already listed under a game's top_streamers
    for g in cached_games:
        top_streamers = g.get("top_streamers", [])
        for s in top_streamers:
            user_login = s.get("user_login", "").strip().lower()
            if user_login == streamer_lower:
                peers = []
                for peer_s in top_streamers:
                    peer_login = peer_s.get("user_login", "").strip().lower()
                    if peer_login != streamer_lower:
                        peers.append(peer_login)
                if peers:
                    return peers[:3]

    # 2. Match a game title in the dossier text
    dossier_lower = dossier_text.lower()
    for g in cached_games:
        game_title = g.get("title", "").lower()
        if game_title in dossier_lower:
            top_streamers = g.get("top_streamers", [])
            peers = [s.get("user_login", "").strip().lower() for s in top_streamers]
            peers = [p for p in peers if p and p != streamer_lower]
            if peers:
                return peers[:3]

    # 3. Fallback: Use top streamers of the first cached game
    if cached_games:
        top_streamers = cached_games[0].get("top_streamers", [])
        peers = [s.get("user_login", "").strip().lower() for s in top_streamers]
        peers = [p for p in peers if p and p != streamer_lower]
        if peers:
            return peers[:3]

    return ["shroud", "ninja", "lirik"]


@node(name="check_and_research_streamer")
def check_and_research_streamer_node(node_input: Any) -> dict:
    """Checks if a medium-form article is already cached.

    If not, runs real-time Twitch Helix + Grounded Search research to build a
    dossier.
    """
    handle = ""
    model = None
    if node_input and hasattr(node_input, "parts") and node_input.parts:
        try:
            data = json.loads(node_input.parts[0].text)
            if isinstance(data, dict):
                handle = data.get("streamer_handle", "")
                model = data.get("model")
            else:
                handle = str(data)
        except Exception:
            try:
                handle = node_input.parts[0].text
            except Exception:
                pass
    elif isinstance(node_input, dict):
        handle = node_input.get("streamer_handle", "")
        model = node_input.get("model")
    elif isinstance(node_input, str):
        try:
            data = json.loads(node_input)
            if isinstance(data, dict):
                handle = data.get("streamer_handle", "")
                model = data.get("model")
            else:
                handle = node_input
        except Exception:
            handle = node_input

    handle = handle.strip().lower()
    if not handle:
        return {"error": "Empty streamer handle", "article": None}

    logger.log(
        25,
        f"[EXPOSE] Task 'check_and_research_streamer' started for streamer '{handle}'",
    )

    from ag_kaggle_5day.agents.gcp_storage import (
        get_cached_medium_form_article,
        get_cached_streamer_sentiment,
        get_historical_expose_context,
    )
    from ag_kaggle_5day.agents.scraper import sample_live_chat

    cached_article = get_cached_medium_form_article(handle)
    if cached_article:
        logger.log(
            25,
            f"[EXPOSE] Cache hit: Retrieved cached medium-form article for '{handle}'",
        )
        logger.log(
            25,
            "[EXPOSE] Success: Medium-form article generation finished "
            f"for streamer '{handle}'",
        )
        return {
            "streamer_handle": handle,
            "article": cached_article,
            "cached": True,
            "model": model,
        }

    logger.log(
        25,
        "[EXPOSE] Research Agent: Running channel detail scraper and "
        f"grounding search for streamer '{handle}'",
    )
    from ag_kaggle_5day.agents.scraper import TwitchAPIClient

    twitch = TwitchAPIClient()

    twitch_info = {}
    vods = []
    if twitch.is_configured:
        user_details = twitch.get_channel_details(handle)
        if user_details:
            twitch_info = user_details
            user_id = user_details.get("id")
            if user_id:
                vods = twitch.get_recent_vods(user_id, limit=5)

    api_key = os.environ.get("GEMINI_API_KEY")

    # RAG context injection
    history_context = get_historical_expose_context(handle, api_key)

    # Fetch/sample live chat sentiment and MPM
    chat_sample = get_cached_streamer_sentiment(handle)
    if not chat_sample:
        logger.info(f"[EXPOSE] Sentiment cache miss for '{handle}', sampling chat...")
        try:
            chat_sample = sample_live_chat(handle, duration=10, source="on-demand")
        except Exception as e:
            logger.error(f"Failed to sample live chat: {e}")
            chat_sample = {
                "total_messages": 0,
                "msg_per_minute": 0.0,
                "sentiment": "Offline",
                "messages": [],
            }

    # Find peer category streamers
    peers = find_peers_for_streamer(handle, dossier_text=history_context)

    # Retrieve comprehensive dossier (fabric, similarity, drift)
    comp_dossier = ""
    try:
        from ag_kaggle_5day.agents.advisor import get_streamer_comprehensive_dossier

        comp_dossier = get_streamer_comprehensive_dossier(handle)
    except Exception as e:
        logger.warning(f"Failed to fetch comprehensive dossier for '{handle}': {e}")

    grounding_prompt = (
        f"Perform a comprehensive web research about the Twitch/gaming "
        f"streamer '{handle}'. Find their main games played, stream schedules, "
        f"recent highlights, general community vibe, and any notable "
        f"achievements or events they participated in. Also explicitly search "
        f"for their official social and website links, including their Twitch channel "
        f"URL, YouTube channel URL, Twitter/X profile URL, and official merchandise or "
        f"online store URL if they have one. Synthesize this into "
        f"a structured dossier.\n\n"
        f"Contextual metrics & peers:\n"
        f"- Live Chat Vibe/Sentiment: {chat_sample.get('sentiment')}\n"
        f"- Chat Speed: {chat_sample.get('msg_per_minute')} messages/minute\n"
        f"- Category Peers for comparison: {', '.join(peers)}\n"
    )
    if comp_dossier:
        grounding_prompt += (
            "\n\n### Comprehensive Database Dossier "
            f"(Use this for precise facts):\n{comp_dossier}"
        )
    if history_context:
        grounding_prompt += (
            "\n\nUse the following historical exposes of this streamer or "
            "tangentially related streamers to inform your research:\n"
            f"{history_context}"
        )

    dossier_text = ""
    try:
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=grounding_prompt,
            system_instruction=(
                "You are a professional gaming journalist and streamer research agent."
            ),
            use_google_search=True,
            chain_name="default",
        )
        dossier_text = response.text
    except Exception as e:
        logger.warning(
            f"Grounded search failed for streamer '{handle}': {e}. "
            "Falling back to basic dossier."
        )
        dossier_text = (
            f"Dossier for streamer '{handle}' (Basic fallback due to search timeout)."
        )

    logger.log(
        25,
        "[EXPOSE] Hand-off: Research Agent -> Streamer Research Writer Agent "
        f"for streamer '{handle}'",
    )

    return {
        "streamer_handle": handle,
        "twitch_info": twitch_info,
        "vods": vods,
        "dossier": dossier_text,
        "cached": False,
        "model": model,
        "history_context": history_context,
        "chat_sample": chat_sample,
        "peers": peers,
    }


@node(name="generate_medium_article")
def generate_medium_article_node(node_input: dict) -> dict:
    """Generates a medium-form article based on the dossier and caches it."""
    if node_input.get("cached"):
        return node_input

    handle = node_input["streamer_handle"]
    twitch_info = node_input.get("twitch_info", {})
    vods = node_input.get("vods", [])
    dossier = node_input.get("dossier", "")
    model = node_input.get("model")
    history_context = node_input.get("history_context", "")
    chat_sample = node_input.get("chat_sample", {})
    peers = node_input.get("peers", [])

    logger.log(
        25, f"[EXPOSE] Task 'generate_medium_article' started for streamer '{handle}'"
    )

    api_key = os.environ.get("GEMINI_API_KEY")

    profile_fabric = {}
    try:
        from ag_kaggle_5day.agents.advisor import get_streamer_profile_fabric

        profile_fabric = get_streamer_profile_fabric(handle) or {}
    except Exception as e:
        logger.warning(
            f"Could not retrieve profile fabric for '{handle}' in workflow: {e}"
        )

    prompt = (
        f"Write a medium-form profile article about the streamer '{handle}'.\n"
        f"Use the following collected info:\n"
        f"- Twitch details: {json.dumps(twitch_info)}\n"
        f"- Recent VODs: {json.dumps(vods)}\n"
        f"- Research dossier:\n{dossier}\n"
        f"- Live Chat Vibe/Sentiment: {chat_sample.get('sentiment')}\n"
        f"- Chat Speed: {chat_sample.get('msg_per_minute')} messages/minute\n"
        f"- Category Peers for comparison: {', '.join(peers)}\n"
        "- Streamer Profile Fabric (archetype, active hours, peers, games): "
        f"{json.dumps(profile_fabric)}\n\n"
    )
    if history_context:
        prompt += (
            f"- Relevant past exposes / historical context:\n{history_context}\n\n"
        )

    fabric_status = profile_fabric.get("fabric_status", "preliminary")
    prompt += (
        "STYLE & TONE CONSTRAINTS:\n"
        "- Do NOT use corny, hyperbolic analogies, over-the-top similes, or "
        "exaggerated metaphorical language (e.g. 'blasting off to Mars').\n"
        "- Do weave comparative references and links to other relevant "
        f"category peer streamers (like {', '.join(peers)}) into the article. "
        "Each reference MUST be a clickable HTML link formatted exactly as: "
        '<a href="/spotlight?handle=peer_handle">peer_name</a>.\n'
        "- Do NOT use em dashes (— or --) under any circumstances in the "
        "article text. Use standard punctuation, colons, or parentheses "
        "instead.\n"
        "- TONE CONFIDENCE RULE: The streamer's chat profile status is "
        f"'{fabric_status}'. "
    )
    if fabric_status == "preliminary":
        prompt += (
            "Because historical chat data is limited, write all metrics/ "
            "sentiment claims using softer, 'early-telemetry' phrasing "
            "(e.g. 'Early telemetry suggests...', 'Initial chat metrics "
            "indicate...'). Rely more on the qualitative dossier than "
            "long-term statistical trends.\n\n"
        )
    else:
        prompt += (
            "Write all metrics/sentiment claims with high-confidence "
            "statistical authority, detailing stable sentiment trends "
            "and clear historical velocity patterns.\n\n"
        )

    prompt += (
        "The article must be highly engaging, styled for a premium "
        "retro-arcade newsletter/blog, and MUST be structured into "
        "exactly two main parts:\n"
        "1. **Behind the Cabinet (Spotlight Bio & Vibe)**: Written "
        "in a warm, friendly, community-oriented, "
        "'get-to-know-the-streamer' style. Detail their personality, "
        "community memes, active streaming times, and how they "
        "interact with chat.\n"
        "2. **The Strategic Grid (Performance & Metrics)**: Written "
        "in a sharp, professional, and data-grounded style. "
        "Analyze their primary game, top games, chat speed, sentiment "
        "trends, and strategic outlook.\n\n"
        "Return the article in a clean JSON format with three keys:\n"
        "- 'title': the article title (Do NOT use 'Streamer of the Day' "
        "in the title; it should reflect that this is a community profile "
        "or spotlight, e.g., 'Community Profile: [Streamer]', 'Spotlight: "
        "[Streamer]', or a custom creative title).\n"
        "- 'content': the HTML-formatted article body.\n"
        "- 'links': a JSON object containing the streamer's verified URLs. "
        "Supported keys are 'twitch', 'youtube', 'store', and 'twitter'. "
        f"If the Twitch channel URL is not found in the dossier, use "
        f"'https://twitch.tv/{handle}'. "
        "For 'youtube', 'store', and 'twitter', only include the key if a "
        "verified URL is found in the dossier; do not include the key if "
        "not found.\n\n"
        "Return ONLY the raw JSON string. Do not wrap in markdown code blocks."
    )

    article = {
        "streamer_handle": handle,
        "title": f"Streamer Spotlight: {handle}",
        "content": "<p>Article generation failed.</p>",
        "links": {"twitch": f"https://twitch.tv/{handle}"},
    }
    logger.log(
        25,
        "[EXPOSE] Streamer Research Writer Agent: Generating article draft "
        f"for '{handle}' using model '{model or 'default'}'",
    )
    try:
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            system_instruction=(
                "You are the Streamer Research Writer Agent. You output only raw JSON."
            ),
            use_google_search=False,
            chain_name="default",
        )
        parsed = parse_json_response(response.text)
        if isinstance(parsed, dict) and "title" in parsed and "content" in parsed:
            article = parsed
            if "links" not in article or not isinstance(article["links"], dict):
                article["links"] = {}
            if not article["links"].get("twitch"):
                article["links"]["twitch"] = f"https://twitch.tv/{handle}"
    except Exception as e:
        logger.error(f"Failed to generate medium article: {e}")

    article["streamer_handle"] = handle
    node_input["article"] = article
    return node_input


@node(name="edit_article")
def edit_article_node(node_input: dict) -> dict:
    """Performs an editing pass on the drafted article using the Editor Agent."""
    if node_input.get("cached"):
        return node_input

    article = node_input.get("article", {})
    title = article.get("title", "")
    content = article.get("content", "")
    links = article.get("links", {})
    peers = node_input.get("peers", [])
    if not peers and "selected_streamer" in node_input:
        selected = node_input["selected_streamer"]
        peers = node_input["dossiers"][selected].get("peers", [])

    logger.log(
        25,
        f"[EXPOSE] Editor Agent: Reviewing drafted article '{title}' for formatting, "
        "links, style violations, and tone.",
    )

    prompt = (
        "Review the following drafted profile article for a live streamer:\n\n"
        f"Title: {title}\n"
        f"Content:\n{content}\n"
        f"Verified Links: {json.dumps(links)}\n\n"
        "EDITORIAL CHECKS:\n"
        "1. Style Guide Compliance: Verify there are NO em dashes (— or --) "
        "and NO corny, exaggerated LLM metaphors/analogies "
        "(e.g. 'blasting off to Mars').\n"
        "2. Peer Linking: Verify that comparative references to peer streamers "
        f"({', '.join(peers)}) are properly formatted as HTML anchor tags "
        f'(e.g., <a href="/spotlight?handle=peer_handle">peer_name</a>) '
        "and that no links are broken or malformed.\n"
        "3. Tone & Grammar: Ensure the tone is sharp, analytical, "
        "retro-arcade style, and polished.\n\n"
        "Return a JSON object containing the following keys:\n"
        "- 'approved': boolean, true if the article passes all style, "
        "link, and tone checks with no changes required; false if "
        "edits/refinements are needed.\n"
        "- 'editorial_notes': string, summarizing the critique, style "
        "violations, or link issues.\n"
        "- 'suggestions': list of strings, providing specific revision "
        "points or corrections for the writer.\n\n"
        "Return ONLY the raw JSON string. Do not wrap in markdown code blocks."
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    model = node_input.get("model")

    editorial_pass = {
        "approved": True,
        "editorial_notes": "No issues found during editing pass.",
        "suggestions": [],
    }

    try:
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            system_instruction=("You are the Editor Agent. You output only raw JSON."),
            use_google_search=False,
            chain_name="editor",
        )
        parsed = parse_json_response(response.text)
        if isinstance(parsed, dict) and "approved" in parsed:
            editorial_pass = parsed
    except Exception as e:
        logger.error(f"Editor Agent failed to review article: {e}")

    logger.log(
        25,
        f"[EXPOSE] Editor Agent review complete. "
        f"Approved: {editorial_pass.get('approved')}. "
        f"Notes: {editorial_pass.get('editorial_notes')}",
    )
    node_input["editorial_pass"] = editorial_pass
    return node_input


@node(name="refine_article")
def refine_article_node(node_input: dict) -> dict:
    """Refines the drafted article if the Editor Agent requested changes."""
    if node_input.get("cached"):
        return node_input

    editorial_pass = node_input.get("editorial_pass", {})
    article = node_input.get("article", {})

    if editorial_pass.get("approved"):
        logger.log(25, "[EXPOSE] Article approved on first pass. Skipping refinement.")
        # Cache medium form article if it's the medium form workflow
        if "selected_streamer" not in node_input:
            handle = node_input["streamer_handle"]
            from ag_kaggle_5day.agents.gcp_storage import store_medium_form_article

            try:
                store_medium_form_article(handle, article)
                logger.log(
                    25, f"[EXPOSE] Success: Medium-form article cached for '{handle}'"
                )
            except Exception as cache_err:
                logger.error(f"Failed to store medium article in cache: {cache_err}")
        return node_input

    # Refine the article
    handle = node_input.get("streamer_handle") or node_input.get("selected_streamer")
    logger.log(
        25,
        f"[EXPOSE] Refining article for '{handle}' based on editor "
        f"suggestions: {editorial_pass.get('suggestions')}",
    )

    prompt = (
        f"Refine the drafted article for '{handle}' "
        "incorporating the Editor's feedback.\n\n"
        f"Original Draft:\n"
        f"Title: {article.get('title')}\n"
        f"Content:\n{article.get('content')}\n\n"
        f"Editor Critique:\n"
        f"- Notes: {editorial_pass.get('editorial_notes')}\n"
        f"- Suggestions:\n"
    )
    for sug in editorial_pass.get("suggestions", []):
        prompt += f"  * {sug}\n"

    prompt += (
        "\nSTRICT REQUIREMENTS:\n"
        "- Do NOT summarize or shorten the article into a single paragraph.\n"
        "- The refined article MUST preserve the high-word-count, "
        "retro-arcade newspaper/blog style.\n"
        "- The refined article MUST retain the exact two-part structure "
        "from the original draft:\n"
        "  1. **Behind the Cabinet (Spotlight Bio & Vibe)**: "
        "written in a warm, friendly, community-oriented style.\n"
        "  2. **The Strategic Grid (Performance & Metrics)**: "
        "written in a sharp, professional, data-grounded style.\n"
        "- Do NOT use em dashes (— or --) under any circumstances.\n"
        "- Do NOT use corny or hyperbolic LLM analogies "
        "(e.g. 'blasting off to Mars').\n"
        "- Fix any malformed HTML tags or peer spotlight links. "
        "Ensure they use exactly the format "
        '<a href="/spotlight?handle=peer_handle">peer_name</a>.\n\n'
        "Return the refined article in clean JSON with three keys:\n"
        "- 'title': the revised title (Do NOT use 'Streamer of the Day' "
        "in the title; it should reflect that this is a community profile "
        "or spotlight, e.g., 'Community Profile: [Streamer]', 'Spotlight: "
        "[Streamer]', or a custom creative title).\n"
        "- 'content': the HTML-formatted revised body\n"
        "- 'links': the JSON object containing verified URLs.\n\n"
        "Return ONLY the raw JSON string. Do not wrap in markdown code blocks."
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    model = node_input.get("model")

    try:
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=prompt,
            system_instruction=(
                "You are the Writer Agent (Refinement Mode). You output only raw JSON."
            ),
            use_google_search=False,
            chain_name="refinement",
        )
        parsed = parse_json_response(response.text)
        if isinstance(parsed, dict) and "title" in parsed and "content" in parsed:
            article = parsed
            if "links" not in article or not isinstance(article["links"], dict):
                article["links"] = {}
            # Merge with original links if any
            orig_links = node_input.get("article", {}).get("links", {}) or {}
            for k, v in orig_links.items():
                if k not in article["links"]:
                    article["links"][k] = v
            # Ensure Twitch channel link is always present
            if not article["links"].get("twitch"):
                article["links"]["twitch"] = f"https://twitch.tv/{handle}"
            article["streamer_handle"] = handle
            node_input["article"] = article
    except Exception as e:
        logger.error(f"Failed to refine article: {e}")

    # Cache medium form article if it's the medium form workflow
    if "selected_streamer" not in node_input:
        from ag_kaggle_5day.agents.gcp_storage import store_medium_form_article

        try:
            store_medium_form_article(handle, article)
            logger.log(
                25, f"[EXPOSE] Success: Medium-form article cached for '{handle}'"
            )
        except Exception as cache_err:
            logger.error(f"Failed to store medium article in cache: {cache_err}")

    return node_input


# ===========================================================================
# 5. Daily Long-Form Expose Workflow Nodes
# ===========================================================================


@node(name="select_expose_candidates")
def select_expose_candidates_node(node_input: Any) -> dict:
    """Selects 3 random streamers currently online in the top 100 on Twitch."""
    logger.log(25, "[EXPOSE] Task 'select_expose_candidates' started.")
    import random

    from ag_kaggle_5day.agents.scraper import TwitchAPIClient

    twitch = TwitchAPIClient()
    streamers = []
    if twitch.is_configured:
        try:
            live_streams = twitch.get_top_live_streams(limit=100)
            streamers = [
                s.get("user_login").lower() for s in live_streams if s.get("user_login")
            ]
        except Exception as e:
            logger.error(
                "[EXPOSE] Failed to fetch top live streams for daily "
                f"expose selection: {e}"
            )

    if len(streamers) < 3:
        # Fallback to defaults if Twitch client is not configured or fails
        defaults = ["shroud", "ninja", "pokimane", "lirik", "xqc", "summit1g"]
        for d in defaults:
            if d not in streamers:
                streamers.append(d)

    # Fetch bellwether scores for weighted selection
    bellwether_scores = {}
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if fs:
            doc = fs.collection("streamer_correlation").document("current").get()
            if doc.exists:
                bellwether_scores = doc.to_dict().get("bellwether_scores", {})
    except Exception as e:
        logger.warning(
            f"[EXPOSE] Failed to fetch bellwether scores for weighted selection: {e}"
        )

    # Build weights (default to 0.1 baseline so all candidates have a chance)
    weights = []
    for s in streamers:
        score = bellwether_scores.get(s.lower(), bellwether_scores.get(s, 0.0))
        weights.append(score + 0.1)

    # Weighted random sampling without replacement
    candidates = []
    pool = list(streamers)
    w_pool = list(weights)
    for _ in range(3):
        if not pool:
            break
        chosen = random.choices(pool, weights=w_pool, k=1)[0]
        idx = pool.index(chosen)
        candidates.append(chosen)
        pool.pop(idx)
        w_pool.pop(idx)

    if len(candidates) < 3:
        candidates = random.sample(streamers, 3)

    logger.log(25, f"[EXPOSE] Selected daily expose candidates: {candidates}")
    logger.log(25, "[EXPOSE] Hand-off: Scheduler -> Research Agent for dossiers")
    return {"candidates": candidates}


@node(name="build_candidate_dossiers")
def build_candidate_dossiers_node(node_input: dict) -> dict:
    """Gathers Helix API and grounded search metadata for the candidates."""
    candidates = node_input["candidates"]
    logger.log(
        25,
        "[EXPOSE] Task 'build_candidate_dossiers' started for candidates: "
        f"{candidates}",
    )
    api_key = os.environ.get("GEMINI_API_KEY")
    from ag_kaggle_5day.agents.gcp_storage import (
        get_cached_streamer_sentiment,
        get_historical_expose_context,
    )
    from ag_kaggle_5day.agents.scraper import TwitchAPIClient, sample_live_chat

    twitch = TwitchAPIClient()

    dossiers = {}
    for streamer in candidates:
        logger.log(
            25,
            f"[EXPOSE] Research Agent: Compiling dossier for candidate '{streamer}'",
        )
        twitch_info = {}
        vods = []
        if twitch.is_configured:
            user_details = twitch.get_channel_details(streamer)
            if user_details:
                twitch_info = user_details
                user_id = user_details.get("id")
                if user_id:
                    vods = twitch.get_recent_vods(user_id, limit=5)

        history_context = get_historical_expose_context(streamer, api_key)

        friendly_streamer = streamer
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(streamer)
            if link_info and link_info.get("display_name"):
                friendly_streamer = link_info["display_name"]
        except Exception:
            pass

        # Fetch/sample live chat sentiment and MPM
        chat_sample = get_cached_streamer_sentiment(streamer)
        if not chat_sample:
            logger.info(
                f"[EXPOSE] Sentiment cache miss for '{streamer}', sampling chat..."
            )
            try:
                chat_sample = sample_live_chat(
                    streamer, duration=10, source="on-demand"
                )
            except Exception as e:
                logger.error(f"Failed to sample live chat: {e}")
                chat_sample = {
                    "total_messages": 0,
                    "msg_per_minute": 0.0,
                    "sentiment": "Offline",
                    "messages": [],
                }

        # Find peer category streamers
        peers = find_peers_for_streamer(streamer, dossier_text=history_context)

        # Retrieve comprehensive dossier (fabric, similarity, drift)
        comp_dossier = ""
        try:
            from ag_kaggle_5day.agents.advisor import (
                get_streamer_comprehensive_dossier,
            )

            comp_dossier = get_streamer_comprehensive_dossier(streamer)
        except Exception as e:
            logger.warning(
                f"Failed to fetch comprehensive dossier for '{streamer}': {e}"
            )

        grounding_prompt = (
            f"Perform detailed search and compile recent news, viewership "
            f"trends, games played, and community reputation about "
            f"streamer '{friendly_streamer}'. Also explicitly search "
            f"for their official social and website links, including their "
            f"Twitch channel URL, YouTube channel URL, Twitter/X profile URL, "
            f"and official merchandise or online store URL if they have one. "
            f"Synthesize this into a structured dossier.\n\n"
            f"Contextual metrics & peers:\n"
            f"- Live Chat Vibe/Sentiment: {chat_sample.get('sentiment')}\n"
            f"- Chat Speed: {chat_sample.get('msg_per_minute')} messages/minute\n"
            f"- Category Peers for comparison: {', '.join(peers)}\n"
        )
        if comp_dossier:
            grounding_prompt += (
                "\n\n### Comprehensive Database Dossier "
                f"(Use this for precise facts):\n{comp_dossier}"
            )
        if history_context:
            grounding_prompt += (
                "\n\nUse the following historical context to inform your "
                f"investigation:\n{history_context}"
            )

        dossier_text = ""
        try:
            response = safe_generate_content(
                api_key=api_key,
                model=None,
                contents=grounding_prompt,
                system_instruction=(
                    "You are a professional streamer analytics investigator."
                ),
                use_google_search=True,
                chain_name="default",
            )
            dossier_text = response.text
        except Exception as e:
            logger.warning(f"Grounded search failed for candidate '{streamer}': {e}")
            dossier_text = f"Dossier fallback for candidate '{streamer}'."

        dossiers[streamer] = {
            "twitch_info": twitch_info,
            "vods": vods,
            "web_research": dossier_text,
            "history_context": history_context,
            "chat_sample": chat_sample,
            "peers": peers,
        }

    logger.log(25, "[EXPOSE] Hand-off: Research Agent -> Expose Selector Agent")
    node_input["dossiers"] = dossiers
    return node_input


@node(name="evaluate_expose_selection")
def evaluate_expose_selection_node(node_input: dict) -> dict:
    """Evaluates the candidate dossiers and selects the Streamer of the Day."""
    candidates = node_input["candidates"]
    dossiers = node_input["dossiers"]
    logger.log(25, "[EXPOSE] Task 'evaluate_expose_selection' started.")
    api_key = os.environ.get("GEMINI_API_KEY")

    prompt = (
        f"You are the Expose Selector Agent. Review the dossiers of the "
        f"following three candidate streamers and select the single most "
        f"interesting Streamer of the Day to write a long-form expose on.\n"
        f"Candidates: {candidates}\n\n"
        f"Dossiers:\n{json.dumps(dossiers)}\n\n"
        f"Choose the streamer based on recent performance jumps, news relevance, "
        f"game diversity, or potential interest to the community.\n"
        f"Return a JSON object with two keys:\n"
        f"- 'selected_streamer': the exact handle of the chosen streamer\n"
        f"- 'reasoning': a brief 2-sentence explanation of why they were selected.\n"
        f"Return ONLY the raw JSON string, do not wrap in markdown code blocks."
    )

    selected = candidates[0]
    reasoning = "Default selection."
    logger.log(
        25,
        "[EXPOSE] Expose Selector Agent: Evaluating candidate dossiers "
        f"for {candidates}",
    )
    try:
        response = safe_generate_content(
            api_key=api_key,
            model=None,
            contents=prompt,
            system_instruction=(
                "You are the Expose Selector Agent. You output only raw JSON."
            ),
            use_google_search=False,
            chain_name="default",
        )
        parsed = parse_json_response(response.text)
        if isinstance(parsed, dict) and parsed.get("selected_streamer") in candidates:
            selected = parsed["selected_streamer"]
            reasoning = parsed.get("reasoning", "")
    except Exception as e:
        logger.error(f"Failed to evaluate expose selection: {e}")

    logger.log(
        25,
        f"[EXPOSE] Evaluator selected '{selected}' as Streamer of the Day. "
        f"Reasoning: {reasoning}",
    )
    logger.log(
        25,
        "[EXPOSE] Hand-off: Expose Selector Agent -> Expose Writer Agent "
        f"for streamer '{selected}'",
    )
    node_input["selected_streamer"] = selected
    node_input["selection_reasoning"] = reasoning
    return node_input


@node(name="write_expose_article")
def write_expose_article_node(node_input: dict) -> dict:
    """Samples live chat sentiment and compiles a detailed expose article."""
    selected = node_input["selected_streamer"]
    dossier = node_input["dossiers"][selected]
    candidates = node_input["candidates"]
    logger.log(
        25, f"[EXPOSE] Task 'write_expose_article' started for streamer '{selected}'"
    )

    from ag_kaggle_5day.agents.gcp_storage import (
        get_historical_expose_context,
        get_historical_sentiment_summary,
    )
    from ag_kaggle_5day.agents.scraper import sample_live_chat

    chat_sample = {}
    try:
        chat_sample = sample_live_chat(selected, duration=60, source="daily-expose")
    except Exception as chat_err:
        logger.error(f"Failed to sample live chat for '{selected}': {chat_err}")
        chat_sample = {
            "total_messages": 0,
            "msg_per_minute": 0.0,
            "sentiment": "Neutral",
            "messages": [],
        }

    api_key = os.environ.get("GEMINI_API_KEY")
    history_context = get_historical_expose_context(selected, api_key)
    sentiment_history = get_historical_sentiment_summary(selected, limit=10)
    peers = dossier.get("peers", [])

    profile_fabric = {}
    try:
        from ag_kaggle_5day.agents.advisor import get_streamer_profile_fabric

        profile_fabric = get_streamer_profile_fabric(selected) or {}
    except Exception as e:
        logger.warning(
            f"Could not retrieve profile fabric for '{selected}' in workflow: {e}"
        )

    friendly_selected = selected
    if profile_fabric:
        friendly_selected = (
            profile_fabric.get("display_name")
            or profile_fabric.get("youtube_title")
            or profile_fabric.get("twitch_display_name")
            or selected
        )
    if friendly_selected.lower().startswith("uc"):
        try:
            from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

            link_info = resolve_streamer_link(selected)
            if link_info and link_info.get("display_name"):
                friendly_selected = link_info["display_name"]
        except Exception:
            pass

    prompt = (
        f"Write a comprehensive, premium long-form expose article about our "
        f"Streamer of the Day: '{friendly_selected}' (handle: '{selected}'). Always refer to them in the article body by their friendly display name '{friendly_selected}' rather than their raw ID handle '{selected}'.\n"  # noqa: E501
        f"Context for the article:\n"
        f"- Selection candidates of the day: {candidates}\n"
        f"- Selection reason: {node_input['selection_reasoning']}\n"
    )
    if history_context:
        prompt += f"- Relevant past exposes / historical context:\n{history_context}\n"

    fabric_status = profile_fabric.get("fabric_status", "preliminary")
    prompt += (
        f"- Detailed dossier:\n{json.dumps(dossier)}\n"
        f"- Live Twitch IRC chat sample (60s): {json.dumps(chat_sample)}\n"
        "- Historical chat sentiment trends (past checks): "
        f"{json.dumps(sentiment_history)}\n"
        f"- Category Peers for comparison: {', '.join(peers)}\n"
        "- Streamer Profile Fabric (archetype, active hours, peers, games): "
        f"{json.dumps(profile_fabric)}\n\n"
        "STYLE & TONE CONSTRAINTS:\n"
        "- Do NOT use corny, hyperbolic analogies, over-the-top similes, or "
        "exaggerated metaphorical language (e.g. 'blasting off to Mars').\n"
        "- Do weave comparative references and links to other relevant "
        f"category peer streamers (like {', '.join(peers)}) into the article. "
        "Each reference MUST be a clickable HTML link formatted exactly as: "
        '<a href="/spotlight?handle=peer_handle">peer_name</a>.\n'
        "- Do NOT use em dashes (— or --) under any circumstances in the "
        "article text. Use standard punctuation, colons, or parentheses "
        "instead.\n"
        "- TONE CONFIDENCE RULE: The streamer's chat profile status is "
        f"'{fabric_status}'. "
    )
    if fabric_status == "preliminary":
        prompt += (
            "Because historical chat data is limited, write all metrics/ "
            "sentiment claims using softer, 'early-telemetry' phrasing "
            "(e.g. 'Early telemetry suggests...', 'Initial chat metrics "
            "indicate...'). Rely more on the qualitative dossier than "
            "long-term statistical trends.\n\n"
        )
    else:
        prompt += (
            "Write all metrics/sentiment claims with high-confidence "
            "statistical authority, detailing stable sentiment trends "
            "and clear historical velocity patterns.\n\n"
        )

    prompt += (
        "The article must be high-word-count, styled for a premium "
        "retro-arcade newspaper/blog, and MUST be structured into "
        "exactly two main parts:\n"
        "1. **Behind the Cabinet (Spotlight Bio & Vibe)**: Written "
        "in a warm, friendly, community-oriented, "
        "'get-to-know-the-streamer' style. This part must contain:\n"
        "   - Career Trajectory & Biography (streamer background, "
        "milestones, active time-of-day)\n"
        "   - Core Gameplay Loop & Audience Engagement Vibe "
        "(streaming style, personality, catchphrases, quirks)\n"
        "2. **The Strategic Grid (Performance & Metrics)**: Written "
        "in a sharp, professional, and data-grounded style. "
        "This part must contain:\n"
        "   - Real-time Live Chat Sentiment & Speed Analysis "
        f"(mention chat speed of {chat_sample.get('msg_per_minute')} "
        f"msg/min and sentiment of {chat_sample.get('sentiment')})\n"
        "   - Viewership & Category Performance (analyzing primary "
        "game, top games, and historical sentiment patterns)\n"
        "   - Strategic Recommendations for other streamers "
        "(actionable takeaways based on telemetry)\n\n"
        f"Format the article in retro-arcade newspaper style.\n\n"
        f"Return the article in a clean JSON format with three keys:\n"
        f"- 'title': the expose article title\n"
        f"- 'content': the HTML-formatted article body.\n"
        f"- 'links': a JSON object containing the streamer's verified URLs. "
        "Supported keys are 'twitch', 'youtube', 'store', and 'twitter'. "
        f"If the Twitch channel URL is not found in the dossier, use "
        f"'https://twitch.tv/{selected}'. "
        "For 'youtube', 'store', and 'twitter', only include the key if a "
        "verified URL is found in the dossier; do not include the key if "
        "not found.\n\n"
        f"Return ONLY the raw JSON string. Do not wrap in markdown code blocks."
    )

    article = {
        "streamer_handle": selected,
        "title": f"Daily Expose: {selected}",
        "content": "<p>Long-form expose generation failed.</p>",
        "links": {"twitch": f"https://twitch.tv/{selected}"},
    }
    logger.log(
        25,
        "[EXPOSE] Expose Writer Agent: Generating long-form expose article "
        f"draft for '{selected}'",
    )
    try:
        response = safe_generate_content(
            api_key=api_key,
            model=None,
            contents=prompt,
            system_instruction=(
                "You are the Expose Writer Agent. You output only raw JSON."
            ),
            use_google_search=False,
            chain_name="expose",
        )
        parsed = parse_json_response(response.text)
        if isinstance(parsed, dict) and "title" in parsed and "content" in parsed:
            article = parsed
            if "links" not in article or not isinstance(article["links"], dict):
                article["links"] = {}
            if not article["links"].get("twitch"):
                article["links"]["twitch"] = f"https://twitch.tv/{selected}"
    except Exception as e:
        logger.error(f"Failed to generate long-form expose: {e}")

    logger.log(25, "[EXPOSE] Hand-off: Expose Writer Agent -> Editor Agent")
    article["streamer_handle"] = selected
    node_input["article"] = article
    node_input["chat_sample"] = chat_sample
    return node_input


@node(name="store_expose_article")
def store_expose_article_node(node_input: dict) -> dict:
    """Saves candidate history to BigQuery, and the expose article to Firestore."""
    candidates = node_input["candidates"]
    selected = node_input["selected_streamer"]
    article = node_input["article"]
    logger.log(
        25,
        f"[EXPOSE] Task 'store_expose_article' started for streamer '{selected}'",
    )

    from ag_kaggle_5day.agents.gcp_storage import (
        store_expose_article_vector,
        store_expose_candidates_to_bq,
    )

    try:
        store_expose_candidates_to_bq(candidates, selected)
    except Exception as bq_err:
        logger.error(f"Failed to store candidates to BigQuery: {bq_err}")

    api_key = os.environ.get("GEMINI_API_KEY")
    text_content = (
        f"Streamer: {selected}. Title: {article.get('title')}. "
        f"Content: {article.get('content')}"
    )
    logger.log(
        25,
        "[EXPOSE] Storage Agent: Saving expose candidates and article vector "
        "to database",
    )
    try:
        store_expose_article_vector(article, text_content, api_key)
    except Exception as store_err:
        logger.error(f"Failed to store expose article in Firestore: {store_err}")

    logger.log(
        25,
        "[EXPOSE] Success: Daily expose selection and long-form expose "
        f"finished for streamer '{selected}'",
    )
    return node_input


# ===========================================================================
# 6. Graph/Workflow Definitions (Continued)
# ===========================================================================

medium_form_article_workflow = Workflow(
    name="medium_form_article_workflow",
    edges=[
        (START, check_and_research_streamer_node),
        (check_and_research_streamer_node, generate_medium_article_node),
        (generate_medium_article_node, edit_article_node),
        (edit_article_node, refine_article_node),
    ],
)

daily_expose_workflow = Workflow(
    name="daily_expose_workflow",
    edges=[
        (START, select_expose_candidates_node),
        (select_expose_candidates_node, build_candidate_dossiers_node),
        (build_candidate_dossiers_node, evaluate_expose_selection_node),
        (evaluate_expose_selection_node, write_expose_article_node),
        (write_expose_article_node, edit_article_node),
        (edit_article_node, refine_article_node),
        (refine_article_node, store_expose_article_node),
    ],
)
