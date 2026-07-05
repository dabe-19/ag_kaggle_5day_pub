from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("streamer_advisor.advisor")


def get_past_analysis_context(query: str, api_key: str = None, limit: int = 2) -> str:
    """Retrieves similar past playbooks, comparison reports, and news
    articles from the Firestore vector database.

    This provides 'memory' context of past analysis and advice to maintain
    consistency and give access to past insights.

    Args:
        query: The topic, game name, or question to find relevant past memories for.
        api_key: Optional Gemini API Key.
        limit: Number of matches to retrieve per category (default: 2).

    Returns:
        A structured Markdown summary of relevant past playbooks, comparison
        reports, and news.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Warning: GEMINI_API_KEY is not set. Memory retrieval is disabled."

    from ag_kaggle_5day.agents.gcp_storage import (
        search_similar_news,
        search_similar_playbooks,
    )

    results = []

    # 1. Fetch playbooks
    try:
        playbooks = search_similar_playbooks(query, api_key, limit=limit)
        if playbooks:
            results.append("### Relevant Past Playbooks:")
            for p in playbooks:
                results.append(
                    f"- **Game**: {p.get('game')} ({p.get('category')})\n"
                    f"  - Platform: {p.get('platform')}\n"
                    f"  - Concept/Hook: {p.get('hook')}\n"
                    f"  - Advice: {p.get('advice')}"
                )
    except Exception as e:
        results.append(f"*(Failed to retrieve past playbooks: {e})*")

    # 2. Fetch reports (disabled/deprecated)

    # 3. Fetch news
    try:
        news = search_similar_news(query, api_key, limit=limit)
        if news:
            results.append("### Relevant Past News Articles:")
            for n in news:
                results.append(
                    f"- **Game**: {n.get('game')} | **Headline**: {n.get('headline')}\n"
                    f"  - Summary: {n.get('summary')}\n"
                    f"  - Source URL: {n.get('url')}"
                )
    except Exception as e:
        results.append(f"*(Failed to retrieve past news: {e})*")

    if not results:
        return "No relevant past analysis, reports, or news found in memory."

    return "\n\n".join(results)


def get_recommendation(query: str, api_key: str = None, model: str = None) -> str:
    """
    Queries Gemini for streaming advice using the cached game list as context.
    """
    from ag_kaggle_5day.agents.advisor import get_cached_games, safe_generate_content

    logger.info(f"Querying recommendation for: '{query}'")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    games = get_cached_games()
    games_summary = "\n".join(
        [
            f"- {g['title']} ({g['category']}): "
            f"Twitch Viewers: {g.get('twitch_viewers', 0):,}, "
            f"YouTube Viewers: {g.get('youtube_viewers', 0):,}, "
            f"Total Avg Viewers: {g.get('avg_viewers', 0):,}, "
            f"Avg length: {g['avg_length_hours']}h, "
            f"Score: {g['score']}, "
            f"Tier: {g.get('tier', 'staple')}, "
            f"Data Quality: {g.get('data_quality', 'unknown')}, "
            f"Source: {g.get('source', 'Unknown')}"
            for g in games
        ]
    )

    system_instruction = (
        "You are an expert streaming mentor and market analyst. Your "
        "goal is to guide budding streamers on what games to stream to "
        "build an audience. Use the provided list of trending "
        "games/categories and live search results (using Google Search) "
        "to suggest optimal choices. When asked for 'out-of-sample' "
        "advice, recommend unique hidden gems or rising trends that "
        "allow the streamer to tap into the zeitgeist without "
        "competing in overcrowded directories.\n\n"
        "Additionally, leverage the historical context from similar "
        "past playbooks/advice retrieved from our vector database to "
        "maintain consistency and build upon past recommendations.\n\n"
        "Prompt Guidelines for Gemma-4 Model:\n"
        "- Do NOT provide generic game descriptions or explain basic "
        "gameplay. Focus on audience demographics, market saturation, and "
        "growth strategies.\n"
        "- Be highly strategic, thorough, and analytical. Structure your "
        "responses clearly with Markdown:\n"
        "  * **Direct Analysis**: A detailed analysis of the user's "
        "query utilizing the current metrics.\n"
        "  * **Data-Driven Match**: Map the user's specific request to "
        "games in the metrics list. Cite exact metrics (Twitch, YouTube, "
        "Score, Data Quality).\n"
        "  * **Out-of-Sample Recommendation**: Propose 1-2 unique or "
        "rising alternative titles using Google Search, explaining the "
        "blue-ocean opportunity.\n"
        "  * **Action Plan**: Provide an actionable checklist including "
        "platform recommendation (Twitch vs YouTube based on viewership "
        "ratios), stream duration, and stream schedule.\n\n"
        f"Current trending metrics in our dashboard:\n{games_summary}"
    )

    if not api_key:
        logger.warning("No API key provided. Using fallback recommendation.")
        return (
            "⚠️ [Environment Configuration Warning: GEMINI_API_KEY is not set.]\n\n"
            "Here is some advisor advice based on cached metrics:\n"
            "We recommend targeting middle-tier viewership games (like "
            "VALORANT or Elden Ring) depending on your target stream duration. "
            "To stand out, look at newer rogue-likes or indie titles (such "
            "as Hades II) which offer highly engaged audiences but lower "
            "competition."
        )

    # Perform vector search for RAG context (playbooks, reports, and news)
    rag_context = ""
    try:
        rag_context = get_past_analysis_context(query, api_key, limit=2)
        if rag_context:
            rag_context = (
                f"### Relevant Past Memories / Analysis Context:\n{rag_context}\n\n"
            )
    except Exception as rag_err:
        logger.error(f"RAG retrieval failed: {rag_err}")

    contents_query = query
    if (
        rag_context
        and "No relevant past" not in rag_context
        and "Memory retrieval is disabled" not in rag_context
    ):
        contents_query = f"{rag_context}User Query: {query}"

    try:
        logger.info("Sending recommendation request to Gemini...")
        start_time = time.time()
        response = safe_generate_content(
            api_key=api_key,
            model=model,
            contents=contents_query,
            system_instruction=system_instruction,
            use_google_search=True,
        )
        latency = round((time.time() - start_time) * 1000.0, 2)
        logger.info(
            f"Received Gemini recommendation in {latency}ms",
            extra={"event_type": "gemini_call", "latency_ms": latency},
        )
        return response.text
    except Exception as e:
        logger.error(f"Error communicating with Gemini Advisor: {e}", exc_info=True)
        return f"Error communicating with Gemini Advisor: {e}"
