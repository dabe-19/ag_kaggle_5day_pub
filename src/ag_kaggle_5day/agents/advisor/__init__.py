from filelock import FileLock  # noqa: F401

from ag_kaggle_5day.agents.advisor.analytics import (  # noqa: F401
    _classify_single_streamer_archetype,
    _process_single_streamer,
    check_and_run_daily_analytics_if_stale,
    get_archetype_analytics,
    get_game_sentiment_metrics,
    get_streamer_profile_fabric,
    get_unique_streamer_handles,
    query_streamer_connections,
    run_daily_analytics_aggregation,
)
from ag_kaggle_5day.agents.advisor.cache import (  # noqa: F401
    CACHE_TTL_SECONDS,
    _HourlyCacheStore,
    _refresh_hourly_cache_internal,
    _store,
    get_cached_games,
    get_hourly_cache,
    refresh_hourly_cache,
    reload_cache_from_firestore_if_stale,
    seed_firestore_cache_if_empty,
)
from ag_kaggle_5day.agents.advisor.ecosystem import (  # noqa: F401
    get_bellwether_rankings,
    get_ecosystem_overview,
    get_streamer_correlations,
    get_tribe_details,
)
from ag_kaggle_5day.agents.advisor.matchmaker import (  # noqa: F401
    run_matchmaker_pipeline,
)
from ag_kaggle_5day.agents.advisor.news import (  # noqa: F401
    _NEWS_CACHE_LOCK_FILE,
    NEWS_CACHE_FILE,
    get_game_news,
    parse_news_markdown,
    prefetch_news_for_games,
    prefetch_news_for_games_sync,
    write_news_markdown,
)
from ag_kaggle_5day.agents.advisor.playbooks import (  # noqa: F401
    _run_workflow_in_thread,
    calculate_compatibility_score,
    generate_stream_playbook,
    get_affiliate_playbook,
    get_or_generate_medium_form_article,
    trigger_daily_expose_job,
)
from ag_kaggle_5day.agents.advisor.recommendations import (  # noqa: F401
    get_past_analysis_context,
    get_recommendation,
)
from ag_kaggle_5day.agents.advisor.reports import (  # noqa: F401
    _CUSTOM_REPORT_LOCK_FILE,
    CUSTOM_REPORT_FILE,
    _fallback_comparison_html,
    _generate_comparison_report,
    _generate_custom_report_process,
    _local_custom_report_key,
    _render_report_json_to_html,
    clean_html_fences,
    clean_json_response,
    get_comparative_analytics,
    get_visible_trending_games,
    matches_category,
)
from ag_kaggle_5day.agents.advisor.similarity import (  # noqa: F401
    calculate_similarity_nvar,
    get_circular_time_distance,
    get_jaccard_overlap,
    get_sentiment_ratios_for_handle,
    get_similar_streamers,
    get_similarity_drift,
    get_streamer_comprehensive_dossier,
    get_viewer_count_for_handle,
)

# Re-exports of external dependencies to support backward compatible test mocks
from ag_kaggle_5day.agents.scraper import (  # noqa: F401
    _GeminiError,
    discover_top_games,
    parse_json_response,
    safe_generate_content,
    scrape_viewership_for_games,
)
