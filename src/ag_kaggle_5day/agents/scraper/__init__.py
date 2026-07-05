# Re-exports for backward compatibility
from ag_kaggle_5day.agents.scraper.chat import (  # noqa: F401
    deduplicate_chat_messages,
    deduplicate_message_tokens,
    sample_live_chat,
)
from ag_kaggle_5day.agents.scraper.config import (  # noqa: F401
    _CACHE_LOCK_FILE,
    CACHE_FILE,
    get_model_timeout,
    load_model_config,
)
from ag_kaggle_5day.agents.scraper.correlation import (  # noqa: F401
    calculate_daily_ecosystem_analytics,
    calculate_hourly_correlation,
)
from ag_kaggle_5day.agents.scraper.discovery import (  # noqa: F401
    _get_cached_youtube_viewers,
    _get_last_known_good_youtube_viewers,
    _last_known_yt_cache,
    discover_top5_games,
    discover_top_games,
    scrape_metrics,
    scrape_viewership_for_games,
)
from ag_kaggle_5day.agents.scraper.games import (  # noqa: F401
    SPONSORED_GAMES,
    STAPLE_GAMES,
    TWITCH_CATEGORIES,
    DynamicSponsoredGames,
    _build_canonical_game,
    _calculate_score,
    _estimate_avg_length,
    _infer_category,
)
from ag_kaggle_5day.agents.scraper.gemini import (  # noqa: F401
    _GeminiError,
    _get_genai_client,
    parse_json_response,
    safe_generate_content,
)
from ag_kaggle_5day.agents.scraper.live_status import (  # noqa: F401
    check_streamer_live_status_ondemand,
    discover_and_profile_micro_streamers,
    get_youtube_channel_live_status,
)
from ag_kaggle_5day.agents.scraper.sentinel import (  # noqa: F401
    _channel_events,
    _channel_games,
    _resolve_and_store_sentiment,
    _ring_buffers,
    _rolling_windows,
    _scrape_youtube_live_chat,
    async_live_monitor_twitch_chat,
    async_live_monitor_youtube_chat,
    get_active_sentinel_channels,
    get_current_decayed_state,
    get_youtube_channel_live_video_id,
    start_raid_sentinel,
    stop_raid_sentinel,
)
from ag_kaggle_5day.agents.scraper.steam import (  # noqa: F401
    get_steam_appid_by_name,
    get_steam_player_count,
)
from ag_kaggle_5day.agents.scraper.twitch import TwitchAPIClient  # noqa: F401
from ag_kaggle_5day.agents.scraper.youtube import (  # noqa: F401
    _QUOTA_LOCK_FILE,
    QUOTA_STATUS_FILE,
    YouTubeAPIClient,
    _is_quota_exceeded_persistent,
    _set_quota_exceeded_persistent,
)
