import json
import os
import threading

from filelock import FileLock
from google.adk.agents import Agent
from google.adk.apps import App

from ag_kaggle_5day.agents.advisor import (
    get_cached_games,
    get_recommendation,
)
from ag_kaggle_5day.agents.scraper import load_model_config, scrape_metrics


# --- 1. Load Environment variables ---
def load_env():
    """Loads environment variables from .env file at the project root."""
    env_path = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        ".env",
    )
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    k, v = stripped.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()

# --- 2. Define Agent Tools ---


def get_current_metrics() -> list[dict]:
    """Retrieves live viewership metrics and opportunities for trending
    and sponsored games.

    Returns:
        List of dictionaries containing game titles, categories, viewer
        numbers, scoring, and source information.
    """
    return get_cached_games()


# get_market_analysis_report has been deprecated and removed.


def get_game_specific_advice(query: str) -> str:
    """Provides tailored strategic growth and content advice for a specific
    game or query.

    Args:
        query: The user's specific query (e.g., "should I stream Minecraft
            or Elden Ring?").

    Returns:
        A detailed Markdown recommendation analysis.
    """
    return get_recommendation(query=query)


def add_custom_game_to_dashboard(game_title: str) -> str:
    """Adds a custom game to the persistent dashboard metrics.

    Args:
        game_title: The name of the game to add (e.g., Stardew Valley).
    """
    game_title = game_title.strip()
    if not game_title:
        return "Error: Game title cannot be empty."

    from ag_kaggle_5day.agents.advisor import prefetch_news_for_games
    from ag_kaggle_5day.agents.scraper import CACHE_FILE

    existing_custom = []
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                games = json.load(f)
            for g in games:
                if g.get("custom") or g.get("tier") == "custom":
                    existing_custom.append(g["title"])
        except Exception as e:
            return f"Error reading cached games list: {e}"

    if any(g.lower() == game_title.lower() for g in existing_custom):
        return (
            f"Game '{game_title}' is already present in the custom dashboard metrics."
        )

    new_custom = existing_custom + [game_title]

    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        custom_results, _ = scrape_metrics(custom_games=new_custom, api_key=api_key)

        if custom_results:
            threading.Thread(
                target=prefetch_news_for_games,
                args=(custom_results, api_key),
                daemon=True,
            ).start()

            # Regenerate the comparison report with the new games list! (disabled)
            pass

        return (
            f"Successfully added '{game_title}' to the dashboard "
            f"and scraped live viewership data!"
        )
    except Exception as e:
        return f"Error scraping viewership for '{game_title}': {e}"


def remove_custom_game_from_dashboard(game_title: str) -> str:
    """Removes a custom game from the dashboard metrics list.

    Args:
        game_title: The name of the custom game to remove.
    """
    game_title = game_title.strip()
    if not game_title:
        return "Error: Game title cannot be empty."

    from ag_kaggle_5day.agents.scraper import _CACHE_LOCK_FILE, CACHE_FILE

    if not os.path.exists(CACHE_FILE):
        return f"Game '{game_title}' was not found because cache is empty."

    lock = FileLock(_CACHE_LOCK_FILE, timeout=5)
    try:
        with lock:
            with open(CACHE_FILE, "r") as f:
                games = json.load(f)

            found = False
            updated_games = []
            for g in games:
                is_custom = g.get("custom") or g.get("tier") == "custom"
                if is_custom and g["title"].lower() == game_title.lower():
                    found = True
                else:
                    updated_games.append(g)

            if not found:
                return f"Game '{game_title}' is not a custom game on the dashboard."

            with open(CACHE_FILE, "w") as f:
                json.dump(updated_games, f, indent=2)

            # Regenerate comparison report with the remaining custom games (disabled)
            pass

            return (
                f"Successfully removed '{game_title}' from the "
                f"custom dashboard metrics!"
            )
    except Exception as e:
        return f"Error removing '{game_title}': {e}"


async def generate_playbooks_for_current_games(
    vibe: str, scale: str, duration: float
) -> str:
    """Generates stream playbooks for the current top games matching the
    profile and saves them to Firestore.

    Args:
        vibe: Gamer profile vibe ("chill", "competitive", "community", "story").
        scale: Gamer channel scale ("starting", "affiliate", "partner").
        duration: Stream duration in hours (e.g., 3.0).

    Returns:
        A success message indicating playbooks were generated and saved.
    """
    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import stream_playbook_workflow

    runner = InMemoryRunner(node=stream_playbook_workflow)
    import time

    session_id = f"playbook_session_{int(time.time())}"
    input_data = {"vibe": vibe, "scale": scale, "duration": duration}

    try:
        events = await runner.run_debug(
            json.dumps(input_data),
            user_id="scheduled_system_task",
            session_id=session_id,
            quiet=True,
        )
        if events and events[-1].output:
            res = events[-1].output
            return (
                f"Successfully generated playbooks for "
                f"{len(res.get('playbooks', []))} games and saved them to the "
                "Firestore vector database."
            )
    except Exception as e:
        import logging

        logging.getLogger("agent").error(
            f"Error in stream playbook workflow: {e}", exc_info=True
        )
    return "Failed to generate playbooks via workflow."


def get_past_analysis_context(query: str) -> str:
    """Retrieves similar past playbooks, comparison reports, and news
    articles from the Firestore vector database.

    This provides 'memory' context of past analysis and advice to maintain
    consistency and give access to past insights.

    Args:
        query: The topic, game name, or question to find relevant past memories
            for.

    Returns:
        A structured Markdown summary of relevant past playbooks, comparison
        reports, and news.
    """
    try:
        from ag_kaggle_5day.agents.advisor import (
            get_past_analysis_context as _get_context,
        )

        return _get_context(query=query)
    except ImportError:
        return "Warning: Memory retrieval is temporarily unavailable (import error)."


def get_affiliate_gear_recommendation(query: str = None) -> str:
    """Queries the database for the most recently generated stream playbooks,
    analyzes their hardware/software advice, and uses Google Search Grounding
    to recommend suitable gear, real prices, and shopping links.

    Args:
        query: Optional specific search query or game name to filter gear for.

    Returns:
        A structured Markdown list of gear recommendations, real prices, and
        shopping links.
    """
    import logging

    logger = logging.getLogger("agent")
    logger.info("Executing get_affiliate_gear_recommendation tool...")

    from google.cloud import firestore

    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    playbooks = []

    if client:
        try:
            docs = (
                client.collection("playbooks")
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(5)
                .stream()
            )
            for doc in docs:
                playbooks.append(doc.to_dict())
        except Exception as e:
            logger.error(f"Failed to query latest playbooks from Firestore: {e}")

    if not playbooks:
        # Fallback to default cache
        from ag_kaggle_5day.agents.advisor import get_cached_games

        cached = get_cached_games()
        for g in cached[:3]:
            playbooks.append(
                {
                    "game": g.get("title", "Game"),
                    "category": g.get("category", "Game"),
                    "preparation": (
                        "Standard stream latency, high quality microphone, overlays."
                    ),
                    "advice": "Stream and engage with the chat.",
                }
            )

    context_lines = []
    for p in playbooks:
        game_name = p.get("game") or p.get("title") or "Unknown Game"
        prep = p.get("preparation") or "None"
        advice = p.get("advice") or "None"
        context_lines.append(
            f"- Game: {game_name}\n"
            f"  Strategic Advice: {advice}\n"
            f"  Setup Requirements: {prep}"
        )
    context_str = "\n".join(context_lines)

    prompt = (
        f"We just generated stream playbooks for the following games and setups:\n"
        f"{context_str}\n\n"
        "Based on this, use Google Search Grounding to find 3 specific "
        "hardware, gear, or software items (such as microphones, capture "
        "cards, lighting, audio mixers, overlays, or stream controllers) "
        "that align with these setups. For each product, search Google to "
        "find a valid, real shopping link (e.g. from Amazon, Best Buy) and a "
        "current lowest price estimate.\n"
        "Format the output in clean, readable Markdown with headings, "
        "bullet points, prices, and clickable Markdown links. Do not "
        "return raw JSON."
    )

    from ag_kaggle_5day.agents.scraper import safe_generate_content

    api_key = os.environ.get("GEMINI_API_KEY")

    system_instruction = (
        "You are an expert streaming hardware consultant. Your goal is to provide "
        "highly customized gear recommendations with valid links and prices, "
        "grounded in actual Google Search results. Ensure the links are real and "
        "the prices are current. Output ONLY clean Markdown."
    )

    try:
        response = safe_generate_content(
            api_key=api_key,
            model=None,
            contents=prompt,
            system_instruction=system_instruction,
            use_google_search=True,
            chain_name="gear_grounding",
        )
        return response.text
    except Exception as e:
        logger.warning(
            "Failed to generate grounded gear recommendations: %s. "
            "Retrying without search...",
            e,
        )
        try:
            response = safe_generate_content(
                api_key=api_key,
                model=None,
                contents=prompt,
                system_instruction=system_instruction,
                use_google_search=False,
                chain_name="gear_grounding",
            )
            return response.text
        except Exception as fallback_err:
            return f"Error retrieving gear recommendations: {fallback_err}"


def get_saturation_data() -> list[dict]:
    """Evaluates the saturation level of cached games by computing the
    viewer-to-streamer ratio.

    A higher viewer-to-streamer ratio indicates a 'blue-ocean' opportunity
    (high demand, low supply).

    Returns:
        List of dicts containing game title, category, viewers, estimated/
        live streamers, and saturation ratio.
    """
    from ag_kaggle_5day.agents.scraper import TwitchAPIClient

    cached_games = get_cached_games()
    twitch = TwitchAPIClient()

    saturation_results = []

    for g in cached_games:
        title = g["title"]
        category = g["category"]
        viewers = g.get("avg_viewers", 0) or (
            g.get("twitch_viewers", 0) + g.get("youtube_viewers", 0)
        )

        streamers = 0
        live_data = False

        if twitch.is_configured:
            try:
                game_id = twitch.get_game_id(title)
                if game_id:
                    twitch_data = twitch.get_viewers_for_game(game_id, title)
                    streamers = twitch_data.get("stream_count", 0)
                    live_data = True
            except Exception:
                pass

        if not live_data or streamers == 0:
            if viewers > 100000:
                streamers = int(viewers / 80) + 10
            elif viewers > 20000:
                streamers = int(viewers / 60) + 5
            elif viewers > 1000:
                streamers = int(viewers / 30) + 2
            else:
                streamers = int(viewers / 10) + 1

        ratio = round(viewers / max(1, streamers), 2)

        if ratio > 100:
            competition = "Very Low (Blue Ocean)"
        elif ratio > 40:
            competition = "Moderate"
        else:
            competition = "High (Red Ocean)"

        saturation_results.append(
            {
                "title": title,
                "category": category,
                "viewers": viewers,
                "streamers": streamers,
                "viewer_to_streamer_ratio": ratio,
                "competition_level": competition,
                "data_source": "live_helix" if live_data else "heuristic_estimate",
            }
        )

    saturation_results.sort(key=lambda x: x["viewer_to_streamer_ratio"], reverse=True)
    return saturation_results


def get_streamer_sentiment_data(streamer_handle: str) -> str:
    """Samples the live Twitch chat sentiment and speed (messages per minute)
    for a streamer handle.

    Uses cached data if it is less than 5 minutes old. Otherwise, runs a
    10-second on-demand live chat sample, logs the result to Firestore and
    BigQuery, and returns a conversational summary.
    """
    import logging
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_cached_streamer_sentiment,
    )
    from ag_kaggle_5day.agents.scraper import sample_live_chat

    logger = logging.getLogger("agent")
    handle = streamer_handle.strip().lower()

    # Check cache first
    cached = get_cached_streamer_sentiment(handle)
    if cached:
        ts = cached.get("timestamp", 0)
        if time.time() - ts < 300:
            logger.info(
                f"Tool: Using cached sentiment for '{handle}' "
                f"(age: {int(time.time() - ts)}s)"
            )
            mpm = cached.get("msg_per_minute", 0.0)
            sentiment = cached.get("sentiment", "Neutral")
            total = cached.get("total_messages", 0)
            summary = cached.get("summary", "")
            summary_line = f"- Chat Summary: {summary}\n" if summary else ""

            game_name = cached.get("game_name", "Unknown")
            channel_url = cached.get("streamer_channel_url", "")
            stream_url = cached.get("stream_url", "")
            top_streamers = cached.get("top_streamers_of_game", [])

            top_str_list = []
            for ts_item in top_streamers:
                user_name = ts_item.get("user_name", "Unknown")
                viewers = ts_item.get("viewer_count", 0)
                top_str_list.append(f"{user_name} ({viewers} viewers)")
            top_streamers_str = ", ".join(top_str_list) if top_str_list else "None"

            meta_lines = (
                f"- Active Game/Category: {game_name}\n"
                f"- Streamer Channel URL: {channel_url}\n"
                f"- Stream/VOD URL: {stream_url}\n"
                f"- Top Streamers playing {game_name}: {top_streamers_str}\n"
            )

            return (
                f"Streamer '{streamer_handle}' sentiment summary (cached):\n"
                f"- Chat Vibe: {sentiment}\n"
                f"- Chat Speed: {mpm} messages/min\n"
                f"- Total Messages Sampled: {total}\n"
                f"{summary_line}"
                f"{meta_lines}"
                f"Status: Active cache lookup successful."
            )

    # Run on-demand 30-second chat sample
    logger.info(f"Tool: Running 30s chat sample for streamer '{handle}'")
    try:
        sample = sample_live_chat(handle, duration=30, source="on-demand")
        mpm = sample.get("msg_per_minute", 0.0)
        sentiment = sample.get("sentiment", "Neutral")
        total = sample.get("total_messages", 0)
        summary = sample.get("summary", "")
        summary_line = f"- Chat Summary: {summary}\n" if summary else ""

        if sentiment == "Offline":
            return (
                f"Streamer '{streamer_handle}' is currently offline or unreachable. "
                "We logged the offline status to the history log, but no "
                "active chat could be sampled."
            )

        game_name = sample.get("game_name", "Unknown")
        channel_url = sample.get("streamer_channel_url", "")
        stream_url = sample.get("stream_url", "")
        top_streamers = sample.get("top_streamers_of_game", [])

        top_str_list = []
        for ts_item in top_streamers:
            user_name = ts_item.get("user_name", "Unknown")
            viewers = ts_item.get("viewer_count", 0)
            top_str_list.append(f"{user_name} ({viewers} viewers)")
        top_streamers_str = ", ".join(top_str_list) if top_str_list else "None"

        meta_lines = (
            f"- Active Game/Category: {game_name}\n"
            f"- Streamer Channel URL: {channel_url}\n"
            f"- Stream/VOD URL: {stream_url}\n"
            f"- Top Streamers playing {game_name}: {top_streamers_str}\n"
        )

        return (
            f"Live 30-second chat sample for streamer '{streamer_handle}':\n"
            f"- Chat Vibe: {sentiment}\n"
            f"- Chat Speed: {mpm} messages/min\n"
            f"- Total Messages Sampled: {total}\n"
            f"{summary_line}"
            f"{meta_lines}"
            f"Status: Sample successfully completed and logged."
        )
    except Exception as e:
        logger.error(f"Error in get_streamer_sentiment_data tool: {e}")
        return (
            f"Failed to retrieve chat sentiment for streamer '{streamer_handle}': {e}"
        )


def get_streamer_profile_fabric(streamer_handle: str) -> str:
    """Retrieves a streamer's detailed profile fabric from the database.

    This includes their archetype, active time of day, primary game category,
    top 5 category dimensions, peer connections, and correlated news events.

    Args:
        streamer_handle: The name of the streamer (e.g. Ninja).

    Returns:
        A JSON string summarizing the streamer's profile fabric,
        similar peers, and activity patterns.
    """
    try:
        from ag_kaggle_5day.agents.advisor import (
            get_streamer_profile_fabric as _get_fabric,
        )

        res = _get_fabric(streamer_handle)
        if not res:
            return f"No profile fabric found for streamer '{streamer_handle}'."
        import json

        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error retrieving profile fabric for '{streamer_handle}': {e}"


def query_streamer_connections(
    archetype: str = None,
    time_active: str = None,
    primary_game: str = None,
) -> str:
    """Queries the database to find similar or connected channels matching
    specific dimensions (Archetype, active time of day, or primary game).

    Args:
        archetype: Standardized category archetype (e.g. Cozy_Social_Interactive,
            Highly_Competitive_Sweat).
        time_active: Active hours bin (e.g. morning, afternoon, evening, latenight).
        primary_game: The primary game they stream.

    Returns:
        A JSON string listing matched streamer profiles and their dimensions.
    """
    try:
        from ag_kaggle_5day.agents.advisor import (
            query_streamer_connections as _query_connections,
        )

        filters = {}
        if archetype:
            filters["archetype_cluster"] = archetype
        if time_active:
            filters["time_active_cluster"] = time_active
        if primary_game:
            filters["primary_game"] = primary_game
        res = _query_connections(filters)
        import json

        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error querying streamer connections: {e}"


def get_archetype_analytics() -> list[dict]:
    """Retrieves aggregate metrics grouped by streamer archetype
    (e.g. Cozy_Social_Interactive, Highly_Competitive_Sweat).

    Returns:
        List of dicts containing the archetype name, counts, average
        chat messages per minute, and sentiment ratios.
    """
    from ag_kaggle_5day.agents.advisor import get_archetype_analytics as _get_archetypes

    return _get_archetypes()


def get_game_sentiment_metrics(game_name: str = None) -> list[dict]:
    """Retrieves aggregate sentiment, streamer counts, and chat speed metrics
    for a game or top games from BQ/Firestore.

    Args:
        game_name: Optional name of a specific game (e.g., Grand Theft Auto V)
            to retrieve metrics for. If omitted or None, returns metrics
            for the top games overall.

    Returns:
        List of dicts containing game title, streamer counts, average
        messages per minute, and sentiment ratios.
    """
    from ag_kaggle_5day.agents.advisor import (
        get_game_sentiment_metrics as _get_game_metrics,
    )

    return _get_game_metrics(game_name)


def get_similar_streamers(streamer_handle: str, top_n: int = 3) -> str:
    """Retrieves and formats a Markdown list of similar streamers for a given handle.

    Provides detailed qualitative analysis explaining why they are similar.

    Args:
        streamer_handle: The name of the streamer (e.g. shroud).
        top_n: Number of similar streamers to return (default 3).

    Returns:
        A formatted Markdown report.
    """
    from ag_kaggle_5day.agents.advisor import get_similar_streamers as _get_similar

    return _get_similar(streamer_handle, top_n)


def get_similarity_drift(streamer_a: str, streamer_b: str) -> str:
    """Retrieves BigQuery similarity timeseries logs and formats a trajectory report
    detailing how the similarity between two streamers has drifted or changed over time.

    Args:
        streamer_a: The name of the first streamer (e.g. Ninja).
        streamer_b: The name of the second streamer (e.g. shroud).

    Returns:
        A formatted Markdown table of historical similarity scores and trends.
    """
    from ag_kaggle_5day.agents.advisor import get_similarity_drift as _get_drift

    return _get_drift(streamer_a, streamer_b)


def get_streamer_correlations(
    streamer_handle: str, compare_with_handle: str = None
) -> dict:
    """Retrieves the current correlation and covariance analysis for a streamer,
    including their top 5 connected channels (Vibe-Coupled, Hype-Aligned,
    Counter-Programmed) and optional comparison metrics.

    Args:
        streamer_handle: The name of the streamer (e.g. Ninja).
        compare_with_handle: Optional name of another streamer to compare
          correlation against.

    Returns:
        A dictionary containing connection mappings and correlation coefficients.
    """
    from ag_kaggle_5day.agents.advisor import get_streamer_correlations as _get_corr

    return _get_corr(streamer_handle, compare_with_handle)


def get_streamer_comprehensive_dossier(streamer_handle: str) -> str:
    """Retrieves a comprehensive dossier for a streamer including profile fabric,
    peer similarity matches, and similarity drift trends for those matching peers.

    Args:
        streamer_handle: The name of the streamer (e.g. shroud).

    Returns:
        A formatted Markdown dossier report.
    """
    from ag_kaggle_5day.agents.advisor import (
        get_streamer_comprehensive_dossier as _get_dossier,
    )

    return _get_dossier(streamer_handle)


def get_ecosystem_overview() -> str:
    """Retrieves an ecosystem-wide overview including Vibe Tribe summaries,
    top 10 bellwether influencers, and top 10 convergence velocity signals.

    Returns:
        A structured Markdown overview report.
    """
    from ag_kaggle_5day.agents.advisor import get_ecosystem_overview as _get_overview

    return _get_overview()


def get_tribe_details(tribe_id: str) -> str:
    """Retrieves detailed network stats and relationships for a specific Vibe Tribe,
    including its members, archetype distribution, and internal convergence signals.

    Args:
        tribe_id: The ID of the tribe (e.g. "0").

    Returns:
        A formatted Markdown detail report.
    """
    from ag_kaggle_5day.agents.advisor import get_tribe_details as _get_details

    return _get_details(tribe_id)


def get_bellwether_rankings(top_n: int = 10) -> str:
    """Retrieves the ranked list of centrality scores across all active

    streamers, identifying the most influential cultural hubs in the
    ecosystem.

    Args:
        top_n: Optional number of rankings to retrieve (default is 10).

    Returns:
        A formatted Markdown rankings report.
    """
    from ag_kaggle_5day.agents.advisor import get_bellwether_rankings as _get_rankings

    return _get_rankings(top_n)


# --- 3. Load Model Config dynamically ---
config = load_model_config()
default_model_name = config.get("default_model", "gemma-4-26b-a4b-it")
if "gemma-4" in default_model_name.lower():
    from google.adk.models import Gemini

    default_model = Gemini(model=default_model_name)
else:
    default_model = default_model_name


# --- 4. Define the sub-agents ---
saturation_scout = Agent(
    name="saturation_scout_agent",
    model=default_model,
    description=(
        "A specialized sub-agent that evaluates viewer-to-streamer ratios "
        "and highlights low-competition 'blue-ocean' categories."
    ),
    instruction=(
        "You are the Saturation Scout. Your job is to analyze the "
        "viewer-to-streamer ratios and find the best low-competition "
        "opportunities (blue-ocean directories) for the streamer. "
        "Use the get_saturation_data tool to fetch ratios and perform "
        "comparative analysis. Clearly rank the directories and explain "
        "why they represent high-potential, low-competition targets."
    ),
    tools=[get_saturation_data],
)

streamer_research_agent = Agent(
    name="streamer_research_agent",
    model=default_model,
    description=(
        "Performs real-time searches and collects Twitch Helix and web "
        "metadata for candidate streamers to build dossiers."
    ),
    instruction=(
        "You are a detailed research agent. Your job is to gather and analyze "
        "metadata for streamers."
    ),
    tools=[],
)

expose_selector_agent = Agent(
    name="expose_selector_agent",
    model=default_model,
    description=(
        "Evaluates multiple streamer dossiers and selects the single "
        "Streamer of the Day."
    ),
    instruction=(
        "You are the Expose Selector. Your job is to evaluate candidate "
        "profiles and choose the spotlight streamer of the day."
    ),
    tools=[],
)

expose_writer_agent = Agent(
    name="expose_writer_agent",
    model=default_model,
    description=(
        "Writes strategic, long-form expose articles on selected streamers "
        "using performance data and live chat sentiment analysis."
    ),
    instruction=(
        "You are the Expose Writer. Your job is to compile strategic, detailed "
        "profile exposes for the selected Streamer of the Day."
    ),
    tools=[],
)

constellation_analyst = Agent(
    name="constellation_analyst_agent",
    model=default_model,
    description=(
        "A specialized sub-agent that analyzes ecosystem-level network "
        "topology, Vibe Tribe community structure, bellwether influence "
        "rankings, and convergence/divergence velocity signals."
    ),
    instruction=(
        "You are the Constellation Analyst. Your role is to interpret "
        "the structural topology of the streamer ecosystem. You analyze "
        "Vibe Tribe clusters, identify bellwether streamers (cultural "
        "hubs with high eigenvector centrality), and detect convergence "
        "or divergence velocity signals between channels.\n"
        "When answering questions:\n"
        "1. First call get_ecosystem_overview for the macro picture.\n"
        "2. Use get_tribe_details for cluster-specific deep dives.\n"
        "3. Use get_bellwether_rankings to identify influence leaders.\n"
        "4. Use get_streamer_correlations for pairwise analysis.\n"
        "Always explain WHY patterns exist, not just WHAT they are."
    ),
    tools=[
        get_ecosystem_overview,
        get_tribe_details,
        get_bellwether_rankings,
        get_streamer_correlations,
        get_streamer_comprehensive_dossier,
    ],
)

strategy_planner = Agent(
    name="strategy_planner_agent",
    model=default_model,
    description=(
        "A specialized sub-agent that drafts execution plans and gathers "
        "comprehensive streamer and market data using database tools."
    ),
    instruction=(
        "You are the Strategy Planner. Your role is to research and analyze "
        "streamer profiles, connections, archetypes, and game metrics. "
        "Before calling any tools, you must draft a short step-by-step plan "
        "identifying what you need and which tools are required to answer the query.\n"
        "To gather a complete context on a streamer, you should call "
        "get_streamer_comprehensive_dossier. Use the other individual tools "
        "like get_streamer_sentiment_data or get_game_sentiment_metrics for "
        "targeted inquiries. Always compile your findings and present a "
        "detailed, structured report back to the coordinator agent."
    ),
    tools=[
        get_streamer_comprehensive_dossier,
        get_streamer_profile_fabric,
        get_similar_streamers,
        get_similarity_drift,
        get_streamer_correlations,
        get_streamer_sentiment_data,
        query_streamer_connections,
        get_archetype_analytics,
        get_game_sentiment_metrics,
        get_past_analysis_context,
    ],
)

# --- 5. Define the ADK Root Agent ---
root_agent = Agent(
    name="streamer_metrics_advisor_agent",
    model=default_model,
    description=(
        "An expert streaming mentor that provides real-time, data-driven "
        "streaming intelligence by comparing metrics, news, and market "
        "saturation."
    ),
    instruction=(
        "You are the Streamer Metrics Advisor Agent. Your role is to help "
        "live streamers optimize their growth by recommending which games "
        "to stream based on live viewership, market dynamics, and game news. "
        "You have access to tools to fetch viewership metrics, "
        "provide specific streaming advice, and "
        "generate/store playbooks for standard gamer profiles. Specific "
        "advice requests (via get_game_specific_advice) automatically "
        "leverage historical playbooks and recommendations retrieved from "
        "a Google Firestore vector database to ensure consistency and build "
        "upon prior strategic insights. Always cite exact metrics when "
        "advising. You can also dynamically manage the dashboard metrics by "
        "adding or removing custom games using the "
        "add_custom_game_to_dashboard and remove_custom_game_from_dashboard "
        "tools. For scheduled runs or queries asking to pre-populate or "
        "update the database with playbooks, use the "
        "generate_playbooks_for_current_games tool. If the user asks for "
        "shopping links, gear recommendations, price estimates, or gear matching "
        "the latest playbooks, use the get_affiliate_gear_recommendation tool to "
        "retrieve and present that information. If the user asks about streamer "
        "profiles, archetype classification details, peer similarity mappings, "
        "relationship drift/trends over time, game-specific chat metrics, "
        "archetypes, or connections in the streaming ecosystem, you should delegate "
        "the task to the strategy_planner_agent. If the user asks about Vibe Tribes, "
        "community clusters, bellwether influence, ecosystem network topology, 2D PCA "
        "constellations, or convergence/divergence velocity signals, delegate the "
        "task to the constellation_analyst_agent. If the user asks to analyze market "
        "saturation, find low-competition opportunities, or check viewer-to-streamer "
        "ratios, you should delegate the task to the saturation_scout_agent."
    ),
    tools=[
        get_current_metrics,
        get_game_specific_advice,
        add_custom_game_to_dashboard,
        remove_custom_game_from_dashboard,
        generate_playbooks_for_current_games,
        get_affiliate_gear_recommendation,
    ],
    sub_agents=[
        saturation_scout,
        streamer_research_agent,
        expose_selector_agent,
        expose_writer_agent,
        constellation_analyst,
        strategy_planner,
    ],
)

app = App(name="streamer_metrics_advisor_app", root_agent=root_agent)
