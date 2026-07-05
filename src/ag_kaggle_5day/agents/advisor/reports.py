from __future__ import annotations

import json
import logging
import os
import time

import jinja2

logger = logging.getLogger("streamer_advisor.advisor")
from ag_kaggle_5day.agents.scraper import (  # noqa: E402
    SPONSORED_GAMES,
)

# Package-relative path configuration
_PACKAGE_DIR = os.path.dirname(os.path.dirname(__file__))
CUSTOM_REPORT_FILE = os.path.join(_PACKAGE_DIR, "custom_report.json")
_CUSTOM_REPORT_LOCK_FILE = CUSTOM_REPORT_FILE + ".lock"

_TEMPLATE_DIR = os.path.join(os.path.dirname(_PACKAGE_DIR), "templates")
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
)


def clean_html_fences(text: str) -> str:
    """Strips markdown code fences (e.g. ```html ... ```) from a string."""
    import re

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return text.strip()


def matches_category(
    game_category: str, game_title: str, selected_category: str
) -> bool:
    """Replicates the frontend JavaScript category-matching logic."""
    if not selected_category or selected_category.lower() == "overall":
        return True
    cat = (game_category or "").lower()
    t = (game_title or "").lower()
    sel = selected_category.lower().strip()
    if sel == "sandbox":
        return "sandbox" in cat or "open world" in cat or "minecraft" in t
    if sel == "rpg":
        return (
            "rpg" in cat or "role-playing" in cat or "souls" in cat or "elden ring" in t
        )
    if sel == "fps":
        return "fps" in cat or "shooter" in cat or "valorant" in t
    if sel == "roguelike":
        return "rogue" in cat or "hades" in t
    if sel == "moba":
        return (
            "moba" in cat
            or "multiplayer online battle arena" in cat
            or "league of legends" in t
        )
    if sel == "action-adventure":
        return (
            "action" in cat
            or "adventure" in cat
            or "racing" in cat
            or "driving" in cat
            or "forza" in cat
            or "gta" in t
            or "grand theft auto" in t
        )
    if sel == "irl":
        return "irl" in cat or "just chatting" in cat or "chatting" in cat
    return True


def get_visible_trending_games(games: list[dict], limit: int = 10) -> list[dict]:
    """Returns the deduplicated union of the top `limit` trending games

    across all 8 dashboard category views.
    """
    categories = [
        "overall",
        "sandbox",
        "rpg",
        "fps",
        "roguelike",
        "moba",
        "action-adventure",
        "irl",
    ]
    visible_games = []
    seen_titles = set()

    # Filter for trending games
    trending_games = [g for g in games if g.get("tier") == "trending"]
    if not trending_games:
        # Fallback to the whole list if tier is not explicitly set
        trending_games = games

    for cat in categories:
        cat_games = [
            g
            for g in trending_games
            if matches_category(g.get("category"), g.get("title"), cat)
        ]
        top_cat = cat_games[:limit]
        for g in top_cat:
            title_lower = g.get("title", "").strip().lower()
            if title_lower and title_lower not in seen_titles:
                seen_titles.add(title_lower)
                visible_games.append(g)

    return visible_games


def _generate_comparison_report(
    games: list[dict], api_key: str = None, model: str = None, category: str = "overall"
) -> str:
    """
    Generates the Gemini-powered comparative analytics HTML for a given
    game list.
    Injects news article data and summaries into the prompt context for
    deeper strategic analysis.
    This is the raw generation function — it does NOT read from the cache store.

    Uses the report_chain from models.json config (Flash-first for quality).
    """
    from ag_kaggle_5day.agents.advisor import (
        NEWS_CACHE_FILE,
        get_cached_games,
        parse_news_markdown,
        safe_generate_content,
    )

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    # Read report model from externalized config for logging
    from ag_kaggle_5day.agents.scraper import load_model_config

    config = load_model_config()
    report_model = config.get("report_model", "gemini-3.5-flash")
    report_chain = config.get("report_chain", [])
    logger.info(f"Report generation: primary='{report_model}', chain={report_chain}")

    # Load news from news_cache.md
    news_data = parse_news_markdown(NEWS_CACHE_FILE)

    # Ensure all custom games are always included,
    # and pad trending/sponsored/editors pick
    custom_games = [g for g in games if g.get("custom") or g.get("tier") == "custom"]
    sponsored_games = [g for g in games if g.get("tier") == "sponsored"]
    editors_pick_games = [g for g in games if g.get("tier") == "editors_pick"]
    trending_games = [g for g in games if g.get("tier") == "trending"]

    # Load all cached games as a backup pool
    all_cached = get_cached_games()

    # Ensure we have sponsored games
    if not sponsored_games:
        sponsored_games = [g for g in all_cached if g.get("tier") == "sponsored"]
    if not sponsored_games:
        # Fallback to SPONSORED_GAMES constants
        import urllib.parse

        for g in SPONSORED_GAMES[:2]:
            sponsored_games.append(
                {
                    "title": g["title"],
                    "category": g["category"],
                    "avg_viewers": g["avg_viewers"],
                    "twitch_viewers": g["avg_viewers"],
                    "youtube_viewers": 0,
                    "avg_length_hours": g["avg_length_hours"],
                    "score": g["score"],
                    "source": "Local Fallback (no live data)",
                    "source_url": f"https://www.twitch.tv/directory/game/{urllib.parse.quote(g['title'])}",
                    "custom": False,
                    "tier": "sponsored",
                    "data_quality": "no_live_data",
                }
            )

    # Ensure we have the editor's pick game
    if not editors_pick_games:
        editors_pick_games = [g for g in all_cached if g.get("tier") == "editors_pick"]
    if not editors_pick_games:
        # Fallback to Forza Horizon 6 from config/default
        from ag_kaggle_5day.agents.scraper import load_model_config

        config = load_model_config()
        editors_pick_config = config.get("editors_pick") or {
            "title": "Forza Horizon 6",
            "category": "Racing",
            "avg_viewers": 35000,
            "twitch_viewers": 35000,
            "youtube_viewers": 0,
            "avg_length_hours": 3.5,
            "score": 85,
            "tier": "editors_pick",
            "source": "Config Fallback",
        }
        g = dict(editors_pick_config)
        g["tier"] = "editors_pick"
        editors_pick_games = [g]

    # Using global matches_category helper

    # Filter trending games by category
    category_trending = [
        g
        for g in trending_games
        if matches_category(g.get("category"), g.get("title"), category)
    ]

    # If we have less than 5 trending games for this category, look into all_cached
    if len(category_trending) < 5:
        cached_trending = [g for g in all_cached if g.get("tier") == "trending"]
        cached_category_trending = [
            g
            for g in cached_trending
            if matches_category(g.get("category"), g.get("title"), category)
        ]

        seen_titles = {g["title"].lower() for g in category_trending}
        for g in cached_category_trending:
            if g["title"].lower() not in seen_titles:
                category_trending.append(g)
                seen_titles.add(g["title"].lower())

    # If we STILL have less than 5 trending games, pad with random
    # selections from the remaining overall trending games pool
    if len(category_trending) < 5:
        import random

        all_trending_pool = {
            g["title"].lower(): g
            for g in trending_games
            + [g for g in all_cached if g.get("tier") == "trending"]
        }
        remaining_trending = [
            g
            for title_lower, g in all_trending_pool.items()
            if title_lower not in {x["title"].lower() for x in category_trending}
        ]
        needed = 5 - len(category_trending)
        if remaining_trending:
            sampled = random.sample(
                remaining_trending, min(needed, len(remaining_trending))
            )
            category_trending.extend(sampled)

    # Limit category_trending to the top 15 games by score
    category_trending = sorted(
        category_trending, key=lambda g: g.get("score", 0), reverse=True
    )[:15]

    # Combine and deduplicate
    final_games_list = []
    seen = set()
    for g in custom_games + sponsored_games + editors_pick_games + category_trending:
        title_lower = g["title"].lower().strip()
        if title_lower not in seen:
            seen.add(title_lower)
            final_games_list.append(g)

    ranked_games = sorted(
        final_games_list, key=lambda g: g.get("score", 0), reverse=True
    )

    games_list = []
    for g in ranked_games:
        title = g["title"]
        news_items = news_data.get(title.lower(), {}).get("articles", [])
        news_str = ""
        if news_items:
            news_details = []
            for item in news_items[:2]:  # Limit to 2 news items per game
                headline = item.get("title", "No headline").replace("\n", " ")
                summary = item.get("summary", "No summary").replace("\n", " ")
                news_details.append(f"  - {headline}: {summary}")
            news_str = "\n" + "\n".join(news_details)
        else:
            news_str = "\n  - No recent news available."

        streamers_str = ""
        if g.get("top_streamers"):
            streamers_details = []
            for s in g["top_streamers"]:
                platform = s.get("platform")
                if not platform:
                    login = s.get("user_login", "")
                    platform = "youtube" if login.startswith("UC") else "twitch"
                streamers_details.append(
                    f"{s['user_name']} ({s['user_login']}:{platform})"
                )
            streamers_str = f" | TopStreamers={', '.join(streamers_details)}"

        twitch_val = g.get("twitch_viewers") or 0
        youtube_val = g.get("youtube_viewers") or 0
        title = g.get("title", "Unknown")
        category_name = g.get("category", "Unknown")
        score = g.get("score", 0)

        # Query game sentiment metrics from BigQuery/Firestore
        from ag_kaggle_5day.agents.advisor import get_game_sentiment_metrics

        metrics_list = get_game_sentiment_metrics(title)
        metrics_str = ""
        if metrics_list:
            m = metrics_list[0]
            pos = m.get("positive_ratio", 0.0)
            neu = m.get("neutral_ratio", 0.0)
            neg = m.get("negative_ratio", 0.0)
            mix = m.get("mixed_ratio", 0.0)
            metrics_str = (
                f" | StreamersCount={m.get('streamer_count', 0)}"
                f" | AvgMsgPerMin={m.get('avg_msg_per_minute', 0.0)}"
                f" | PosRatio={pos:.2%} | NeuRatio={neu:.2%}"
                f" | NegRatio={neg:.2%} | MixRatio={mix:.2%}"
            )
            if m.get("archetypes"):
                metrics_str += f" | Archetypes={m['archetypes']}"

        games_list.append(
            f"- {title} ({category_name}): "
            f"Twitch={twitch_val:,} | "
            f"YouTube={youtube_val:,} | "
            f"Score={score} | Tier={g.get('tier', 'sponsored')} | "
            f"Quality={g.get('data_quality', 'unknown')}"
            f"{streamers_str}"
            f"{metrics_str}"
            f"{news_str}"
        )
    games_summary = "\n".join(games_list)

    # Fetch similar past comparison reports for reference/RAG context
    from ag_kaggle_5day.agents.gcp_storage import search_similar_comparison_reports

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
            # Truncate snippet
            past_reports_context = (
                f"\n### Reference Memory (Past Comparison Report "
                f"Snippet):\n{clean_text[:400]}...\n"
            )
    except Exception as e:
        logger.debug(f"Failed to retrieve past comparison reports context: {e}")

    system_instruction = (
        "You are an expert streaming mentor. Compare the streaming metrics provided "
        "and produce a strategic report in JSON format only. Do NOT output any markdown blocks or HTML tags.\n"  # noqa: E501
        "The output must be a single, valid JSON object with the following keys:\n"
        '1. "overview": A 2-3 sentence paragraph summarizing the current market landscape and general strategy.\n'  # noqa: E501
        '2. "matrix_strategies": A JSON object mapping game titles (exactly as written in the Games data) '  # noqa: E501
        "to a 1-2 sentence strategy recommendation. Ensure you include an entry in "
        '"matrix_strategies" for EVERY game listed in the Games data, using the exact game title as the key.\n'  # noqa: E501
        '3. "recommendation_cards": An array of objects, one for each recommendation card. You must include cards for:\n'  # noqa: E501
        "   - ALL custom games present in the dataset\n"
        "   - Exactly one sponsored game (labeled with a disclaimer)\n"
        "   - The top 5 trending games in the category\n"
        "   Each recommendation card object must have:\n"
        '   - "game": The exact title of the game.\n'
        '   - "type": "[Custom]" for custom games, "[Sponsored]" for the sponsored game, or a rank label like "1", "2", "3", "4", "5" for trending games.\n'  # noqa: E501
        '   - "pro": A concise, single-sentence Pro detail.\n'
        '   - "con": A concise, single-sentence Con detail.\n'
        '   - "advice": A detailed 3-4 sentence strategic advice block (Adopt style, hours, engage hook).\n'  # noqa: E501
        '4. "hidden_gem": A JSON object representing 1 unique out-of-sample recommendation (not in the provided dataset) with keys:\n'  # noqa: E501
        '   - "title": The game title.\n'
        '   - "opportunity": A 2-3 sentence justification of the opportunity.\n'
        '   - "strategy": A concise stream scheduling/targeting advice sentence.\n'
        "Keep total output under 600 words. Return valid JSON only. Do NOT wrap it in markdown block fences like ```json."  # noqa: E501
    )

    query = (
        f"Games data:\n{games_summary}\n\n"
        f"{past_reports_context}"
        "Generate the report JSON per the system instructions. Construct the "
        "JSON containing 'overview', 'matrix_strategies' mapping for ALL games in Games data, "  # noqa: E501
        "and 'recommendation_cards' for custom/sponsored/top 5 games, and 'hidden_gem' out-of-sample recommendation."  # noqa: E501
    )

    if not api_key:
        logger.warning("No API key — returning static fallback comparison report.")
        return _fallback_comparison_html()

    try:
        obfuscated_key = (
            f"{api_key[:4]}...{api_key[-4:]}"
            if api_key and len(api_key) > 8
            else "short_or_empty"
        )
        logger.info(
            f"Generating comparison report for {len(ranked_games)} games. "
            f"API Key: {obfuscated_key}\n"
            f"System Instruction: {system_instruction}\n"
            f"Query/Prompt: {query}"
        )
        start_time = time.time()
        response = safe_generate_content(
            api_key=api_key,
            model=None,  # Let the report chain select the model
            contents=query,
            system_instruction=system_instruction,
            use_google_search=False,
            timeout=120.0,
            chain_name="report",
        )
        latency = round((time.time() - start_time) * 1000.0, 2)
        response_text = response.text
        logger.info(
            f"Comparison report JSON generated in {latency}ms\n"
            f"Raw Response: {response_text}",
            extra={"event_type": "gemini_call", "latency_ms": latency},
        )

        try:
            json_data = clean_json_response(response_text)
            return _render_report_json_to_html(json_data, ranked_games, category)
        except Exception as json_err:
            logger.warning(
                f"JSON parsing failed for LLM response (falling back to pre-designed HTML): {json_err}\n"  # noqa: E501
                f"Response content: {response_text}"
            )
            return _fallback_comparison_html(category)

    except Exception as e:
        logger.error(f"Error generating comparison report: {e}", exc_info=True)
        return (
            f"<div style='color: #ef4444; padding: 1rem;'>"
            f"Error generating comparative analytics: {e}</div>"
        )


def clean_json_response(text: str) -> dict:
    """Strips markdown fences and parses valid JSON from LLM response."""

    text = text.strip()
    if text.startswith("```"):
        first_line_end = text.find("\n")
        if first_line_end != -1:
            text = text[first_line_end:].strip()
        else:
            text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def _render_report_json_to_html(data: dict, games: list[dict], category: str) -> str:
    """Renders the parsed JSON report data into clean HTML layout matching

    dashboard CSS classes."""
    overview = data.get(
        "overview", "Strategic comparison of the current streaming landscape."
    )

    strategies = data.get("matrix_strategies", {})
    strategies_lookup = {k.lower().strip(): v for k, v in strategies.items()}

    games_data = []
    for g in games:
        title = g.get("title", "Unknown")
        tier = g.get("tier", "trending")

        badge_cls = "badge-trending"
        if tier == "sponsored":
            badge_cls = "badge-sponsored"
        elif tier == "custom":
            badge_cls = "badge-custom"

        twitch_v = g.get("twitch_viewers") or 0
        youtube_v = g.get("youtube_viewers") or 0
        score = g.get("score") or 0

        streamers_links = "—"
        if g.get("top_streamers"):
            links = []
            for s in g["top_streamers"]:
                name = s.get("user_name", "")
                login = s.get("user_login", "")
                platform = s.get("platform")
                if not platform:
                    platform = "youtube" if login.startswith("UC") else "twitch"

                if platform == "youtube":
                    links.append(
                        f'<a href="https://youtube.com/channel/{login}" target="_blank" '  # noqa: E501
                        f'class="streamer-link" data-handle="{login}">{name}</a>'
                    )
                else:
                    links.append(
                        f'<a href="https://twitch.tv/{login.lower()}" target="_blank" '
                        f'class="streamer-link" data-handle="{login.lower()}">{name}</a>'  # noqa: E501
                    )
            if links:
                streamers_links = ", ".join(links)

        # Robust lookup:
        strategy_text = strategies_lookup.get(title.lower().strip())
        if not strategy_text:
            for k, v in strategies_lookup.items():
                if k in title.lower().strip() or title.lower().strip() in k:
                    strategy_text = v
                    break

        if not strategy_text:
            category_lower = g.get("category", "").lower()
            if "chat" in title.lower() or "just chatting" in title.lower():
                strategy_text = "Focus on high viewer interaction, Q&A segments, and real-time chat overlays."  # noqa: E501
            elif (
                "shooter" in category_lower
                or "action" in category_lower
                or "fps" in category_lower
                or "counter-strike" in title.lower()
                or "valorant" in title.lower()
            ):
                strategy_text = "Highlight high-skill plays, stream during peak viewer hours, and interact during lobby wait times."  # noqa: E501
            elif (
                "moba" in category_lower
                or "strategy" in category_lower
                or "league of legends" in title.lower()
                or "dota" in title.lower()
            ):
                strategy_text = "Deliver rank grind commentary, explain tactical choices, and schedule community match lobbies."  # noqa: E501
            elif "sports" in category_lower or "racing" in category_lower:
                strategy_text = "Run time-trial challenges, host viewer lobbies, and stream during esports events."  # noqa: E501
            else:
                strategy_text = "Optimize stream schedules and engage chat with category-matching overlays."  # noqa: E501

        games_data.append(
            {
                "title": title,
                "tier": tier,
                "badge_cls": badge_cls,
                "twitch_viewers": twitch_v,
                "youtube_viewers": youtube_v,
                "streamers_links": streamers_links,
                "score": score,
                "strategy_text": strategy_text,
            }
        )

    cards = []
    for card in data.get("recommendation_cards", []):
        game_title = card.get("game", "Unknown")
        card_type = card.get("type", "Trending")
        pro = card.get("pro", "N/A")
        con = card.get("con", "N/A")
        advice = card.get("advice", "N/A")

        disclaimer = False
        if "[Sponsored]" in card_type or "sponsored" in card_type.lower():
            disclaimer = True

        card_title = (
            f"{card_type}. {game_title}"
            if card_type and card_type not in game_title
            else game_title
        )

        cards.append(
            {
                "title": card_title,
                "disclaimer": disclaimer,
                "pro": pro,
                "con": con,
                "advice": advice,
            }
        )

    gem = data.get("hidden_gem", {})
    gem_data = {
        "title": gem.get("title", "Sea of Stars"),
        "opportunity": gem.get("opportunity", "Blue-ocean niche opportunity."),
        "strategy": gem.get("strategy", "Adopt interactive stream elements."),
    }

    template = _jinja_env.get_template("partials/comparison_report.html")
    return template.render(
        overview=overview,
        games=games_data,
        cards=cards,
        gem=gem_data,
    )


def _fallback_comparison_html(category: str = "overall") -> str:
    cat = category.lower().strip()

    # Pre-designed data sets for keyless visitors
    data_sets = {
        "sandbox": {
            "title": "Sandbox & Creative",
            "overview": (
                "The sandbox market is dominated by creative freedom and "
                "community-driven content. Audiences value highly interactive "
                "and self-directed streams over linear gameplay."
            ),
            "games": [
                {
                    "game": "Minecraft",
                    "tier": "sponsored",
                    "twitch": "28,500",
                    "youtube": "12,000",
                    "streamers": "xQc, Shroud",
                    "score": "95",
                    "strategy": "Host viewer worlds",
                },
                {
                    "game": "Terraria",
                    "tier": "trending",
                    "twitch": "8,400",
                    "youtube": "3,100",
                    "streamers": "Pedguin",
                    "score": "88",
                    "strategy": "Expert speedrun",
                },
                {
                    "game": "Roblox",
                    "tier": "trending",
                    "twitch": "14,000",
                    "youtube": "19,500",
                    "streamers": "KreekCraft",
                    "score": "86",
                    "strategy": "Custom lobbies",
                },
                {
                    "game": "Garry's Mod",
                    "tier": "trending",
                    "twitch": "3,200",
                    "youtube": "1,200",
                    "streamers": "Sips",
                    "score": "75",
                    "strategy": "Roleplay events",
                },
                {
                    "game": "Subnautica",
                    "tier": "trending",
                    "twitch": "5,100",
                    "youtube": "1,800",
                    "streamers": "Jacksepticeye",
                    "score": "80",
                    "strategy": "Hardcore run",
                },
            ],
            "cards": [
                {
                    "title": "[Sponsored] Minecraft",
                    "pro": "Infinite viewer interaction hooks",
                    "con": "High oversaturation",
                    "advice": (
                        "Engage viewers directly by hosting a dedicated "
                        "sub-server. Stream for 3-4 hours during peak "
                        "afternoon hours to optimize scaling. Use custom "
                        "Twitch interactive overlays where chat can trigger "
                        "game events to stand out."
                    ),
                },
                {
                    "title": "1. Terraria",
                    "pro": "Loyal core community",
                    "con": "Deep game knowledge needed",
                    "advice": (
                        "Focus on high-challenge playthroughs (e.g. calamity "
                        "mod). Keep chat updated on your death count. Target "
                        "a 3-hour evening stream, utilizing custom milestone "
                        "overlays for boss defeats."
                    ),
                },
                {
                    "title": "2. Roblox",
                    "pro": "Massive YouTube cross-traffic",
                    "con": "Younger chat demographic",
                    "advice": (
                        "Stream trending minigames or custom community maps. "
                        "Set up interactive chat triggers to choose next "
                        "maps. Stream 2-3 hours on weekends to capture "
                        "maximum global traffic."
                    ),
                },
                {
                    "title": "3. Subnautica",
                    "pro": "Strong suspense/reaction content",
                    "con": "Limited replayability once finished",
                    "advice": (
                        "Adopt a blind or hardcore style. Position your "
                        "camera to capture reactions. Keep overlays clean to "
                        "maintain immersion. Target 3-4 hour late evening "
                        "streams."
                    ),
                },
                {
                    "title": "4. Garry's Mod",
                    "pro": "High variety of custom modes",
                    "con": "Needs group coordination",
                    "advice": (
                        "Run custom sandbox events or Trouble in Terrorist "
                        "Town with other streamers. Use viewer suggestion "
                        "polls to choose game modes. Stream 4 hours on "
                        "Friday nights."
                    ),
                },
            ],
            "gem": {
                "title": "Stormworks: Build and Rescue",
                "opportunity": (
                    "A brilliant physics builder with moderate saturation. "
                    "Perfect for creators looking to showcase complex "
                    "engineering designs or hilarious catastrophic failures."
                ),
                "plan": (
                    "Schedule a weekly 3-hour builder showcase. Take "
                    "blueprint requests from chat."
                ),
            },
        },
        "rpg": {
            "title": "Role-Playing Games",
            "overview": (
                "RPG viewers seek deep narrative immersion and high-stakes "
                "decision-making. Backseat gaming is common; leverage it as "
                "an engagement tool rather than a distraction."
            ),
            "games": [
                {
                    "game": "Elden Ring",
                    "tier": "trending",
                    "twitch": "42,000",
                    "youtube": "18,000",
                    "streamers": "KaiCenat",
                    "score": "96",
                    "strategy": "No-hit runs",
                },
                {
                    "game": "Baldur's Gate 3",
                    "tier": "trending",
                    "twitch": "15,000",
                    "youtube": "5,500",
                    "streamers": "CohhCarnage",
                    "score": "90",
                    "strategy": "Tactician mode",
                },
                {
                    "game": "Cyberpunk 2077",
                    "tier": "trending",
                    "twitch": "8,100",
                    "youtube": "2,400",
                    "streamers": "Shroud",
                    "score": "82",
                    "strategy": "Phantom Liberty",
                },
                {
                    "game": "Witcher 3",
                    "tier": "trending",
                    "twitch": "4,300",
                    "youtube": "1,100",
                    "streamers": "xQc",
                    "score": "78",
                    "strategy": "Lore walk-throughs",
                },
                {
                    "game": "Minecraft",
                    "tier": "sponsored",
                    "twitch": "28,500",
                    "youtube": "12,000",
                    "streamers": "xQc, Shroud",
                    "score": "95",
                    "strategy": "Roleplay custom",
                },
            ],
            "cards": [
                {
                    "title": "1. Elden Ring",
                    "pro": "Unmatched hype and challenge appeal",
                    "con": "Highly competitive directory",
                    "advice": (
                        "Host specific challenge runs (e.g. no-shield, RL1). "
                        "Use overlays displaying your current deaths "
                        "prominently. Stream for 4+ hours during evening "
                        "blocks to attract hardcore fans."
                    ),
                },
                {
                    "title": "2. Baldur's Gate 3",
                    "pro": "Deep story branching for viewers",
                    "con": "Slower pacing requires high commentary",
                    "advice": (
                        "Let chat vote on key dialogue options and companion "
                        "selections. Keep conversation flowing during slow "
                        "turn-based combat. Target 3-4 hours in afternoon "
                        "blocks."
                    ),
                },
                {
                    "title": "3. Cyberpunk 2077",
                    "pro": "Visually stunning game environments",
                    "con": "Harder to interact while reading subtitles",
                    "advice": (
                        "Adopt a warm camera setup. Share personal lore "
                        "theories during travel. Focus on completing unique "
                        "builds. Stream 3 hours during late night slots."
                    ),
                },
                {
                    "title": "[Sponsored] Minecraft",
                    "pro": "Easy setup and broad demographic",
                    "con": "Needs custom RPG modpacks",
                    "advice": (
                        "Build or play in a custom medieval RPG world. Use "
                        "fantasy music overlays and interactive sound effects. "
                        "Target a 3-hour afternoon weekend slot."
                    ),
                },
            ],
            "gem": {
                "title": "Sea of Stars",
                "opportunity": (
                    "A retro-inspired turn-based RPG with a passionate niche "
                    "community. Provides low-saturation visibility and highly "
                    "engaged chat discussion around classic gaming aesthetics."
                ),
                "plan": (
                    "Stream 2-3 hours during mid-day blocks. Focus on "
                    "completing puzzles live with chat help."
                ),
            },
        },
        "fps": {
            "title": "First-Person Shooters",
            "overview": (
                "The FPS sector requires high mechanical skill, low latency "
                "interactions, and competitive match tracking. Overlays must "
                "not obstruct crosshairs or crucial hud elements."
            ),
            "games": [
                {
                    "game": "Valorant",
                    "tier": "trending",
                    "twitch": "98,000",
                    "youtube": "34,000",
                    "streamers": "Tarik, TenZ",
                    "score": "98",
                    "strategy": "Ranked grind",
                },
                {
                    "game": "Counter-Strike 2",
                    "tier": "trending",
                    "twitch": "75,000",
                    "youtube": "22,000",
                    "streamers": "Gaules, s1mple",
                    "score": "95",
                    "strategy": "Premier matchmaking",
                },
                {
                    "game": "Apex Legends",
                    "tier": "trending",
                    "twitch": "32,000",
                    "youtube": "11,000",
                    "streamers": "iiTzTimmy",
                    "score": "89",
                    "strategy": "Ranked push",
                },
                {
                    "game": "Overwatch 2",
                    "tier": "trending",
                    "twitch": "18,000",
                    "youtube": "6,200",
                    "streamers": "Flats, Seagull",
                    "score": "81",
                    "strategy": "Viewer custom games",
                },
                {
                    "game": "Minecraft",
                    "tier": "sponsored",
                    "twitch": "28,500",
                    "youtube": "12,000",
                    "streamers": "xQc, Shroud",
                    "score": "95",
                    "strategy": "PvP tournaments",
                },
            ],
            "cards": [
                {
                    "title": "1. Valorant",
                    "pro": "Massive community and co-streaming",
                    "con": "Extremely high saturation",
                    "advice": (
                        "Provide play-by-play commentary explaining your "
                        "positioning. Set stream latency to 'low' for "
                        "instant response. Stream for 4 hours starting in "
                        "early evening."
                    ),
                },
                {
                    "title": "2. Counter-Strike 2",
                    "pro": "Constant global competitive traffic",
                    "con": "High toxicity in random lobbies",
                    "advice": (
                        "Queue with a friendly stack to maintain positive "
                        "stream vibe. Highlight clutch rounds using clip "
                        "highlights. Target 3-4 hours during peak afternoon "
                        "times."
                    ),
                },
                {
                    "title": "3. Apex Legends",
                    "pro": "Fast-paced movement is exciting to watch",
                    "con": "High action makes chat reading difficult",
                    "advice": (
                        "Read chat during load screens and lobby queues. "
                        "Utilize a text-to-speech option for super chats. "
                        "Stream 3 hours during evening slots."
                    ),
                },
                {
                    "title": "[Sponsored] Minecraft",
                    "pro": "Broad appeal to all age groups",
                    "con": "Needs FPS/PvP focus (e.g. Bedwars)",
                    "advice": (
                        "Run viewer lobby tournaments or bedwars challenges. "
                        "Maintain high-energy shoutcasting during matches. "
                        "Target 3 hours on Saturday afternoons."
                    ),
                },
            ],
            "gem": {
                "title": "Spectre Divide",
                "opportunity": (
                    "A new tactical shooter featuring unique dual-body "
                    "mechanics. Sits in a low-saturation sweet spot, drawing "
                    "curious competitive players looking for new strategies."
                ),
                "plan": (
                    "Stream 3 hours during mid-afternoon. Create short "
                    "gameplay guides and explain mechanics."
                ),
            },
        },
        "racing": {
            "title": "Racing & Simulation",
            "overview": (
                "Racing simulation audiences appreciate specialized rigs, "
                "steering wheel overlays, and telemetry details. Stream audio "
                "balancing must ensure engine sounds do not drown out "
                "commentary."
            ),
            "games": [
                {
                    "game": "Forza Horizon 5",
                    "tier": "trending",
                    "twitch": "12,000",
                    "youtube": "4,100",
                    "streamers": "DonJoewonSong",
                    "score": "88",
                    "strategy": "Custom tracks",
                },
                {
                    "game": "Mario Kart 8",
                    "tier": "trending",
                    "twitch": "9,200",
                    "youtube": "3,800",
                    "streamers": "Bay area bugg",
                    "score": "85",
                    "strategy": "Viewer lobbies",
                },
                {
                    "game": "F1 24",
                    "tier": "trending",
                    "twitch": "15,000",
                    "youtube": "6,000",
                    "streamers": "JarnoOpmeer",
                    "score": "91",
                    "strategy": "Career mode",
                },
                {
                    "game": "Assetto Corsa",
                    "tier": "trending",
                    "twitch": "6,100",
                    "youtube": "1,900",
                    "streamers": "Drifting servers",
                    "score": "79",
                    "strategy": "Drift challenges",
                },
                {
                    "game": "Minecraft",
                    "tier": "sponsored",
                    "twitch": "28,500",
                    "youtube": "12,000",
                    "streamers": "xQc, Shroud",
                    "score": "95",
                    "strategy": "Boat racing maps",
                },
            ],
            "cards": [
                {
                    "title": "1. F1 24",
                    "pro": "Strong overlap with real-world motorsports",
                    "con": "High rig expectation from viewers",
                    "advice": (
                        "Construct a clean dashboard overlay. Run full career "
                        "mode seasons and ask chat for setup advice. Stream "
                        "for 3 hours on Sunday mornings around race times."
                    ),
                },
                {
                    "title": "2. Forza Horizon 5",
                    "pro": "Visually beautiful and casual",
                    "con": "Less competitive depth than simulation titles",
                    "advice": (
                        "Host custom open-world exploration or drag races. "
                        "Position camera to capture hands/wheel. Target 3 "
                        "hours during Saturday morning blocks."
                    ),
                },
                {
                    "title": "3. Mario Kart 8",
                    "pro": "Extremely high viewer lobby conversion",
                    "con": "High RNG item gameplay can frustate",
                    "advice": (
                        "Host viewer rooms with interactive queue counters. "
                        "Keep stream vibe humorous and casual. Target a "
                        "2.5-hour evening slot on weekdays."
                    ),
                },
                {
                    "title": "[Sponsored] Minecraft",
                    "pro": "Low entry barrier and easy setup",
                    "con": "Needs racing specific mod/map packs",
                    "advice": (
                        "Set up ice-boat racing maps or parkour race tracks. "
                        "Create high-stakes time-trials for chat. Stream 3 "
                        "hours during weekend afternoons."
                    ),
                },
            ],
            "gem": {
                "title": "Wreckfest",
                "opportunity": (
                    "Combines demolition derby chaos with competitive racing "
                    "physics. Perfect for high-energy casual streams, "
                    "offering low-saturation directories with high-laughter "
                    "potential."
                ),
                "plan": (
                    "Host a Friday night demolition derby. Open slots to "
                    "viewers and run custom lobby rules."
                ),
            },
        },
        "overall": {
            "title": "Overall Stream Landscape",
            "overview": (
                "The current streaming landscape is split between massive "
                "competitive game directories and highly interactive variety "
                "directories. Leveraging RAG-based strategies is required "
                "to stand out."
            ),
            "games": [
                {
                    "game": "Valorant",
                    "tier": "trending",
                    "twitch": "98,000",
                    "youtube": "34,000",
                    "streamers": "Tarik, TenZ",
                    "score": "98",
                    "strategy": "Ranked grind",
                },
                {
                    "game": "Elden Ring",
                    "tier": "trending",
                    "twitch": "42,000",
                    "youtube": "18,000",
                    "streamers": "KaiCenat",
                    "score": "96",
                    "strategy": "No-hit runs",
                },
                {
                    "game": "Minecraft",
                    "tier": "sponsored",
                    "twitch": "28,500",
                    "youtube": "12,000",
                    "streamers": "xQc, Shroud",
                    "score": "95",
                    "strategy": "Host viewer worlds",
                },
                {
                    "game": "Baldur's Gate 3",
                    "tier": "trending",
                    "twitch": "15,000",
                    "youtube": "5,500",
                    "streamers": "CohhCarnage",
                    "score": "90",
                    "strategy": "Tactician mode",
                },
                {
                    "game": "Forza Horizon 5",
                    "tier": "trending",
                    "twitch": "12,000",
                    "youtube": "4,100",
                    "streamers": "DonJoewonSong",
                    "score": "88",
                    "strategy": "Custom tracks",
                },
            ],
            "cards": [
                {
                    "title": "1. Valorant",
                    "pro": "Extremely active competitive audience",
                    "con": "High saturation requires high skill or humor",
                    "advice": (
                        "Adopt an educational or highly entertaining "
                        "playstyle. Stream for 4 hours during peak afternoon "
                        "times, ensuring low latency is configured."
                    ),
                },
                {
                    "title": "2. Elden Ring",
                    "pro": "Passionate community, great reaction clips",
                    "con": "Requires gameplay focus over reading chat",
                    "advice": (
                        "Set up a death counter. Interact during bosses or "
                        "lore talks. Stream 3-4 hours in late evening slots."
                    ),
                },
                {
                    "title": "[Sponsored] Minecraft",
                    "pro": "Broad appeal and infinite modpacks",
                    "con": "High directory saturation",
                    "advice": (
                        "Set up custom sub-servers or unique challenges. "
                        "Stream 3 hours during peak weekend blocks with "
                        "custom interactive overlays."
                    ),
                },
                {
                    "title": "3. Baldur's Gate 3",
                    "pro": "Viewer votes drive high engagement",
                    "con": "Turn-based pacing is slower",
                    "advice": (
                        "Let chat choose your alignment and companion "
                        "decisions. Target 3-4 hours during afternoon slots."
                    ),
                },
            ],
            "gem": {
                "title": "Hades II",
                "opportunity": (
                    "High viewer interest, excellent pacing, and rich gameplay "
                    "narrative. Rogue-likes offer ideal loops for stream "
                    "runs, keeping viewers hooked through multiple attempts."
                ),
                "plan": (
                    "Schedule 3-hour evening runs. Take weapon/boon build "
                    "suggestions from chat polls."
                ),
            },
        },
    }

    # Fetch data or default to overall
    c_data = data_sets.get(cat, data_sets["overall"])

    # Generate rows
    games_data = []
    for g in c_data["games"]:
        badge_cls = "badge-trending"
        if g["tier"] == "sponsored":
            badge_cls = "badge-sponsored"
        elif g["tier"] == "custom":
            badge_cls = "badge-custom"

        # Format streamers links
        streamers_links = "—"
        if g["streamers"] and g["streamers"] != "—":
            parts = [s.strip() for s in g["streamers"].split(",")]
            streamers_links = ", ".join(
                f'<a href="https://twitch.tv/{s.lower()}" target="_blank" '
                f'class="streamer-link" data-handle="{s.lower()}">{s}</a>'
                for s in parts
            )

        games_data.append(
            {
                "game": g["game"],
                "tier": g["tier"],
                "badge_cls": badge_cls,
                "twitch": g["twitch"],
                "youtube": g["youtube"],
                "streamers_links": streamers_links,
                "score": g["score"],
                "strategy": g["strategy"],
            }
        )

    # Warning banner (keep as is or prepend)
    banner = (
        '<div style="background: rgba(10, 10, 20, 0.4); padding: 1.5rem; '
        "border-radius: 12px; border: 1px dashed rgba(0, 240, 255, 0.15); "
        'margin-bottom: 2rem;">'
        '<h3 style="color: var(--accent-cyan); margin-bottom: 0.75rem; '
        "font-family: 'Press Start 2P', cursive; font-size: 0.85rem;\">"
        "📊 Comparative Analytics Fallback</h3>"
        '<p style="color: var(--text-muted); font-size: 0.9rem; '
        'margin-bottom: 1.25rem;">'
        "No Gemini API key is configured, or database cache is not yet "
        f"seeded. Serving pre-compiled analysis for <strong>{c_data['title']}"
        "</strong> category. Connect your key to run real-time comparisons."
        "</p>"
        "</div>"
    )

    cards = []
    for card in c_data["cards"]:
        disclaimer = False
        if "[Sponsored]" in card["title"]:
            disclaimer = True
        cards.append(
            {
                "title": card["title"],
                "disclaimer": disclaimer,
                "pro": card["pro"],
                "con": card["con"],
                "advice": card["advice"],
            }
        )

    gem = {
        "title": c_data["gem"]["title"],
        "opportunity": c_data["gem"]["opportunity"],
        "strategy": c_data["gem"]["plan"],
    }

    template = _jinja_env.get_template("partials/fallback_report.html")
    report_content = template.render(
        title=c_data["title"],
        overview=c_data["overview"],
        games=games_data,
        cards=cards,
        gem=gem,
    )
    return banner + report_content


def _generate_custom_report_process(
    custom_games: list[str],
    api_key: str = None,
    search_model: str = None,
    analysis_model: str = None,
    category: str = "overall",
) -> None:
    try:
        logger.info(
            f"[Child Process] Starting background report generation for {custom_games}"
        )

        # 1. Fetch viewership metrics for custom games
        from ag_kaggle_5day.agents.advisor import (
            get_cached_games,
            prefetch_news_for_games,
        )
        from ag_kaggle_5day.agents.scraper import scrape_viewership_for_games

        custom_results = scrape_viewership_for_games(
            custom_games, api_key=api_key, model=search_model
        )
        for g in custom_results:
            g["custom"] = True
            g["tier"] = "custom"

        # 2. Get existing hourly cached games (top5 + staples)
        custom_titles_lower = {cg.strip().lower() for cg in custom_games}
        existing_games = get_cached_games()
        filtered_existing = [
            g for g in existing_games if g["title"].lower() not in custom_titles_lower
        ]

        # Combined list for prompt
        combined_games = filtered_existing + custom_results

        # 3. Trigger background (non-blocking) news pre-fetch.
        # We rely on currently cached news to avoid delaying the report.
        news_targets = [
            g for g in combined_games if g.get("tier") == "trending" or g.get("custom")
        ]
        try:
            prefetch_news_for_games(news_targets, api_key=api_key, model=search_model)
        except Exception as e:
            logger.error(f"Failed to start background news pre-fetch: {e}")

        # 4. Generate the unified report using the populated news cache
        report = _generate_comparison_report(
            combined_games, api_key=api_key, model=analysis_model, category=category
        )

        # Save comparison report to Firestore
        from ag_kaggle_5day.agents.gcp_storage import store_comparison_report_vector

        try:
            store_comparison_report_vector(report, custom_games, api_key)
        except Exception as store_err:
            logger.error(
                f"Failed to store custom comparison report vector: {store_err}"
            )

        # Write success status using store_custom_report_state
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
            logger.error(
                f"[Child Process] Failed to store custom report state: {store_err}"
            )
        logger.info(
            f"[Child Process] Background report generation succeeded for {custom_games}"
        )

    except Exception as e:
        logger.error(
            f"[Child Process] Background report generation failed: {e}", exc_info=True
        )
        # Write error status using store_custom_report_state
        data = {
            "custom_games": custom_games,
            "category": category,
            "report": (
                f"<div style='color: #ef4444; padding: 1rem;'>"
                f"Error generating comparative analytics: {str(e)}</div>"
            ),
            "status": "error",
            "error": str(e),
            "generated_at": time.time(),
        }
        try:
            from ag_kaggle_5day.app import store_custom_report_state

            store_custom_report_state(custom_games, category, data)
        except Exception as store_err:
            logger.error(
                "[Child Process] Failed to store custom report error state: "
                f"{store_err}"
            )


def _local_custom_report_key(custom_games: list[str], category: str) -> str:
    import hashlib

    sorted_games = sorted([g.strip().lower() for g in custom_games if g.strip()])
    hash_payload = json.dumps({"games": sorted_games, "category": category})
    hash_val = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()
    return f"custom_report_{hash_val}"


def get_comparative_analytics(
    custom_games: list[str],
    api_key: str = None,
    search_model: str = None,
    analysis_model: str = None,
    force_refresh: bool = False,
    category: str = "overall",
) -> str:
    """
    Returns the comparison report.
    - If custom_games are provided: triggers background process to fetch
      viewership and news for custom games, and generate a unified,
      comprehensive comparison report in a non-blocking way.
    - Otherwise, returns the cached hourly comparison report.
    """
    from ag_kaggle_5day.agents.advisor import (
        _store,
        get_cached_games,
        prefetch_news_for_games,
    )

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    # If no custom games, return the cached hourly report directly
    if not custom_games:
        cached_report = None
        if category == "overall":
            cached_report = _store.comparison_report

        if not cached_report:
            try:
                from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state

                key = _local_custom_report_key([], category)
                cached_data = get_app_cache_state(key)
                if cached_data and cached_data.get("status") == "success":
                    cached_report = cached_data.get("report")
            except Exception as e:
                logger.warning(f"Failed to load cached report for {category}: {e}")

        is_error = (
            cached_report is not None
            and "Error generating comparative analytics:" in cached_report
        )
        eff_analysis_model = analysis_model or "gemma-4-31b-it"
        model_changed = (
            _store.analysis_model and _store.analysis_model != eff_analysis_model
        )

        # Handle generation/startup states
        is_generating = _store.refreshed_at > 0.0 and not _store.comparison_report
        is_starting = _store.refreshed_at == 0.0

        if (is_generating or is_starting) and api_key:
            logger.info(
                "Comparison report is currently generating in the background. "
                "Returning placeholder."
            )
            return (
                "<div data-loading='true' style='padding: 1.5rem; "
                "background: rgba(30, 41, 59, 0.4); border-radius: 12px; "
                "border: 1px dashed rgba(255,255,255,0.1);'>"
                "<h3 style='color: var(--accent-cyan); margin-bottom: "
                "1rem;'>🔄 Generating Comparative Analytics...</h3>"
                "<p>The streaming advisor is currently compiling live "
                "metrics and generating the report. Please refresh this "
                "page in a few seconds.</p>"
                "</div>"
            )

        if (not cached_report or is_error or model_changed) and api_key:
            logger.info(
                f"Generating comparison report on the fly for category '{category}'..."
            )
            combined = get_cached_games()
            if combined:
                # Trigger background (non-blocking) news pre-fetch.
                # We rely on currently cached news to avoid delaying the report.
                news_games = [
                    g
                    for g in combined
                    if g.get("tier") == "trending" or g.get("custom")
                ]
                try:
                    prefetch_news_for_games(
                        news_games, api_key=api_key, model=search_model
                    )
                except Exception as e:
                    logger.error(f"Failed to start background news pre-fetch: {e}")
                cached_report = _generate_comparison_report(
                    combined,
                    api_key=api_key,
                    model=eff_analysis_model,
                    category=category,
                )
                if "Error generating comparative analytics:" not in cached_report:
                    try:
                        from ag_kaggle_5day.agents.gcp_storage import (
                            store_app_cache_state,
                        )

                        key = _local_custom_report_key([], category)
                        data = {
                            "custom_games": [],
                            "category": category,
                            "report": cached_report,
                            "status": "success",
                            "generated_at": time.time(),
                        }
                        store_app_cache_state(key, data)
                        if category == "overall":
                            _store.comparison_report = cached_report
                            _store.analysis_model = eff_analysis_model
                            store_app_cache_state(
                                "comparison_report", {"report": cached_report}
                            )
                    except Exception as cache_err:
                        logger.warning(f"Failed to cache generated report: {cache_err}")
            else:
                cached_report = _fallback_comparison_html(category)
        else:
            cached_report = cached_report or _fallback_comparison_html(category)

        return cached_report

    # If custom games are provided, check background status or trigger generation
    if not api_key:
        logger.warning(
            "No API key provided for custom comparison report. Returning fallback."
        )
        return _fallback_comparison_html(category)

    logger.info(f"Checking background report status for custom games: {custom_games}")

    # Standardize game titles for comparison
    sorted_custom_req = sorted(
        [cg.strip().lower() for cg in custom_games if cg.strip()]
    )

    # Read status from Firestore/local query-specific cache
    cached_data = None
    try:
        from ag_kaggle_5day.app import get_custom_report_state

        cached_data = get_custom_report_state(custom_games, category)
    except Exception as e:
        logger.warning(f"Failed to read custom report state: {e}")

    # Check if cache is matching and valid
    is_generating = False

    if cached_data:
        cached_games = cached_data.get("custom_games", [])
        sorted_cached = sorted([g.strip().lower() for g in cached_games if g.strip()])
        if sorted_cached == sorted_custom_req:
            status = cached_data.get("status")
            if status == "success" and not force_refresh:
                # Check cache age (max age 1h for overall, 25h for other
                # categories, 5m for custom lists)
                age = time.time() - cached_data.get("generated_at", 0.0)
                max_age = (
                    (3600 if category == "overall" else 90000)
                    if not custom_games
                    else 300
                )
                if age < max_age:
                    return cached_data.get("report")
            elif status == "generating":
                # Check if generator process is stuck (timeout > 3 minutes)
                age = time.time() - cached_data.get("generated_at", 0.0)
                if age < 180:
                    is_generating = True
                else:
                    logger.warning("Custom report generation seems stuck. Restarting.")
            elif status == "error" and not force_refresh:
                # If error occurred recently, return it
                age = time.time() - cached_data.get("generated_at", 0.0)
                if age < 60:
                    return cached_data.get("report")

    # Trigger background generation if not already generating
    if not is_generating:
        logger.info(
            "Triggering background process to generate custom comparison report..."
        )
        gen_data = {
            "custom_games": custom_games,
            "category": category,
            "report": "",
            "status": "generating",
            "generated_at": time.time(),
        }
        try:
            from ag_kaggle_5day.app import store_custom_report_state

            store_custom_report_state(custom_games, category, gen_data)
        except Exception as e:
            logger.warning(f"Failed to write generating status: {e}")

        import multiprocessing

        p = multiprocessing.Process(
            target=_generate_custom_report_process,
            args=(custom_games, api_key, search_model, analysis_model, category),
            daemon=True,
        )
        p.start()

    return (
        "<div data-loading='true' style='text-align: center; padding: "
        "3rem; background: rgba(30, 41, 59, 0.4); border-radius: 12px; "
        "border: 1px dashed rgba(255,255,255,0.1);'>"
        '<span class="loader" style="width: 2rem; height: 2rem; '
        'border-width: 3px; display: inline-block;"></span>'
        "<h3 style='color: var(--accent-cyan); margin-top: 1.5rem; "
        "margin-bottom: 0.5rem;'>🔄 Generating Custom Comparative "
        "Analytics...</h3>"
        "<p style='color: var(--text-muted); font-size: 0.95rem;'> "
        "We are scraping viewership and news for your custom games in the background. "
        "This report will load automatically in a few seconds."
        "</p>"
        "</div>"
    )
