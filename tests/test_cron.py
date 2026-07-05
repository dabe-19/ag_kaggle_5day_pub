from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ag_kaggle_5day.cron import run_cron_refresh


@pytest.mark.anyio
@patch("ag_kaggle_5day.cron.start_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.cron.stop_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.agents.advisor.trigger_daily_expose_job", new=AsyncMock())
@patch("ag_kaggle_5day.agents.scraper.calculate_hourly_correlation", new=MagicMock())
@patch("ag_kaggle_5day.agents.advisor.run_daily_analytics_aggregation", new=MagicMock())
@patch("ag_kaggle_5day.cron.get_effective_key")
@patch("ag_kaggle_5day.cron.refresh_hourly_cache")
@patch("ag_kaggle_5day.cron.query_remote_agent", new_callable=AsyncMock)
@patch("ag_kaggle_5day.cron.TwitchAPIClient")
@patch("ag_kaggle_5day.cron.YouTubeAPIClient")
@patch("ag_kaggle_5day.cron.get_app_cache_state")
@patch("ag_kaggle_5day.cron.store_app_cache_state")
async def test_run_cron_refresh(
    mock_store_app_cache_state,
    mock_get_app_cache_state,
    mock_youtube_client,
    mock_twitch_client,
    mock_query_remote_agent,
    mock_refresh_hourly_cache,
    mock_get_effective_key,
):
    # Setup mocks
    mock_get_effective_key.return_value = "dummy-api-key"
    mock_get_app_cache_state.return_value = None
    mock_twitch = MagicMock()
    mock_twitch_client.return_value = mock_twitch
    mock_youtube = MagicMock()
    mock_youtube_client.return_value = mock_youtube

    # Execute
    await run_cron_refresh()

    # Assertions
    mock_get_effective_key.assert_called_once()
    mock_refresh_hourly_cache.assert_called_once_with(
        "dummy-api-key",
        mock_twitch,
        mock_youtube,
        None,
        None,
        True,
    )
    mock_query_remote_agent.assert_called_once()
    args, kwargs = mock_query_remote_agent.call_args
    assert "Perform scheduled database updates" in args[0]
    assert kwargs["api_key"] == "dummy-api-key"
    assert kwargs["user_id"] == "scheduled_system_task"


@pytest.mark.anyio
@patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
@patch("ag_kaggle_5day.agents.gcp_storage.prepopulate_streamer_links_cache")
@patch(
    "ag_kaggle_5day.agents.scraper.sentinel._run_sentinel_connection",
    new_callable=AsyncMock,
)
@patch(
    "ag_kaggle_5day.agents.scraper.sentinel._run_youtube_sentinel_connection",
    new_callable=AsyncMock,
)
@patch("ag_kaggle_5day.agents.scraper.safe_generate_content")
@patch(
    "ag_kaggle_5day.agents.scraper._resolve_and_store_sentiment",
    new_callable=AsyncMock,
)
async def test_sentinel_aggregated_summaries(
    mock_resolve_store,
    mock_safe_generate,
    mock_run_yt_sentinel,
    mock_run_sentinel,
    mock_prepopulate_links,
    mock_get_firestore,
):
    import time

    from ag_kaggle_5day.agents.scraper import (
        _channel_events,
        _channel_games,
        _ring_buffers,
        _rolling_windows,
        start_raid_sentinel,
        stop_raid_sentinel,
    )

    _channel_events.clear()
    _channel_games.clear()
    _ring_buffers.clear()
    _rolling_windows.clear()

    # Avoid Firestore requests during test
    mock_get_firestore.return_value = None

    # Setup mock LLM return
    mock_response = MagicMock()
    mock_response.text = (
        "Overall the stream started with high speed followed by negative vibe shift."
    )
    mock_safe_generate.return_value = mock_response

    # Initialize Sentinel state
    await start_raid_sentinel("test-api-key")

    # Simulate triggers for a channel
    channel = "test_streamer"
    _channel_games[channel] = "VALORANT"
    _ring_buffers[channel] = ["hello"] * 20
    _rolling_windows[channel] = [
        (time.time(), 0) for _ in range(20)
    ]  # deque/list tuple of (timestamp, score)

    # Populate events manually to simulate triggers
    _channel_events[channel] = [
        {
            "timestamp": time.time(),
            "trigger_type": "VOLUME_SPIKE",
            "mpm": 35.0,
            "mu": 0.0,
            "sigma": 0.5,
            "chat_snippet": ["wow", "hype"],
        },
        {
            "timestamp": time.time(),
            "trigger_type": "VIBE_SHIFT",
            "mpm": 30.0,
            "mu": -0.3,
            "sigma": 0.8,
            "chat_snippet": ["nooo", "why"],
        },
    ]

    # Call stop_raid_sentinel to trigger aggregation
    await stop_raid_sentinel("test-api-key")

    # Assertions
    # 1. safe_generate_content should be called once with aggregated timeline prompt
    mock_safe_generate.assert_called_once()
    call_args, call_kwargs = mock_safe_generate.call_args
    assert "Event Timeline:" in call_kwargs.get("contents", "")

    # 2. _resolve_and_store_sentiment should be called with synthesized
    # summary for target channel
    called_channels = [call[0][0] for call in mock_resolve_store.call_args_list]
    assert channel in called_channels
    target_call = next(
        c for c in mock_resolve_store.call_args_list if c[0][0] == channel
    )
    args, kwargs = target_call
    assert (
        args[1]["summary"]
        == "Overall the stream started with high speed followed by negative vibe shift."
    )


@pytest.mark.anyio
@patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
@patch("ag_kaggle_5day.agents.gcp_storage.get_bigquery_client")
@patch("ag_kaggle_5day.agents.gcp_storage.store_correlation_history")
async def test_calculate_hourly_correlation(
    mock_store_corr_history,
    mock_get_bigquery_client,
    mock_get_firestore_client,
):
    import datetime

    from ag_kaggle_5day.agents.scraper import calculate_hourly_correlation

    # 1. Mock Firestore
    mock_fs = MagicMock()
    mock_get_firestore_client.return_value = mock_fs

    mock_doc1 = MagicMock()
    mock_doc1.id = "streamer1"
    mock_doc1.to_dict.return_value = {"archetype_cluster": "chill"}
    mock_doc2 = MagicMock()
    mock_doc2.id = "streamer2"
    mock_doc2.to_dict.return_value = {"archetype_cluster": "competitive"}

    mock_fs.collection.return_value.stream.return_value = [mock_doc1, mock_doc2]

    # 2. Mock BigQuery
    mock_bq = MagicMock()
    mock_bq.project = "test-project"
    mock_get_bigquery_client.return_value = mock_bq

    # Mock BigQuery historical correlation_history rows
    class MockRow:
        def __init__(
            self,
            timestamp,
            streamer_a,
            streamer_b,
            volatility_cov,
            sentiment_cov,
            msg_rate_cov,
            viewer_count_cov,
        ):
            self.timestamp = timestamp
            self.streamer_a = streamer_a
            self.streamer_b = streamer_b
            self.volatility_cov = volatility_cov
            self.sentiment_cov = sentiment_cov
            self.msg_rate_cov = msg_rate_cov
            self.viewer_count_cov = viewer_count_cov

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    mock_rows = [
        MockRow(
            now_dt - datetime.timedelta(hours=2),
            "streamer1",
            "streamer2",
            0.5,
            0.4,
            0.6,
            0.5,
        ),
        MockRow(
            now_dt - datetime.timedelta(hours=1),
            "streamer1",
            "streamer2",
            0.6,
            0.5,
            0.7,
            0.6,
        ),
    ]

    mock_query_job = MagicMock()
    mock_query_job.result.return_value = mock_rows
    mock_bq.query.return_value = mock_query_job

    # Execute
    calculate_hourly_correlation("dummy-key")

    # Assertions
    mock_get_firestore_client.assert_called()
    mock_get_bigquery_client.assert_called()
    # Check that firestore set was called on current correlation
    mock_fs.collection.assert_any_call("streamer_sentiment")
    mock_fs.collection.assert_any_call("streamer_correlation")
    # Verify correlation history was stored
    mock_store_corr_history.assert_called_once()
    records = mock_store_corr_history.call_args[0][0]
    assert len(records) > 0

    # Verify current correlation doc is written to Firestore with bellwether_scores
    set_call = mock_fs.collection("streamer_correlation").document("current").set
    set_call.assert_called_once()
    saved_doc = set_call.call_args[0][0]
    assert "bellwether_scores" in saved_doc
    assert "convergence_velocity" in saved_doc


@pytest.mark.anyio
@patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
@patch("ag_kaggle_5day.agents.gcp_storage.store_ecosystem_snapshot")
@patch("ag_kaggle_5day.agents.scraper.safe_generate_content")
async def test_calculate_daily_ecosystem_analytics(
    mock_safe_generate,
    mock_store_snapshot,
    mock_get_firestore_client,
):
    from ag_kaggle_5day.agents.scraper import calculate_daily_ecosystem_analytics

    mock_fs = MagicMock()
    mock_get_firestore_client.return_value = mock_fs

    # Mock historical correlations in Firestore
    mock_current_ref = MagicMock()
    mock_current_snapshot = MagicMock()
    mock_current_snapshot.exists = True
    mock_current_snapshot.to_dict.return_value = {
        "streamers": ["streamer1", "streamer2", "streamer3"],
        "correlation_matrices": {
            "chat_volatility": {
                "streamer1": [1.0, 0.8, 0.2],
                "streamer2": [0.8, 1.0, 0.1],
                "streamer3": [0.2, 0.1, 1.0],
            },
            "rolling_sentiment_score": {
                "streamer1": [1.0, 0.8, 0.2],
                "streamer2": [0.8, 1.0, 0.1],
                "streamer3": [0.2, 0.1, 1.0],
            },
            "msg_per_minute": {
                "streamer1": [1.0, 0.8, 0.2],
                "streamer2": [0.8, 1.0, 0.1],
                "streamer3": [0.2, 0.1, 1.0],
            },
            "viewer_count": {
                "streamer1": [1.0, 0.8, 0.2],
                "streamer2": [0.8, 1.0, 0.1],
                "streamer3": [0.2, 0.1, 1.0],
            },
        },
        "bellwether_scores": {"streamer1": 0.9, "streamer2": 0.8, "streamer3": 0.2},
        "convergence_velocity": [
            {
                "streamer_a": "streamer1",
                "streamer_b": "streamer2",
                "velocity": 0.05,
                "direction": "converging",
            }
        ],
    }
    mock_current_ref.get.return_value = mock_current_snapshot

    mock_names_ref = MagicMock()
    mock_names_snapshot = MagicMock()
    mock_names_snapshot.exists = False
    mock_names_ref.get.return_value = mock_names_snapshot

    def document_route(doc_id):
        if doc_id == "current":
            return mock_current_ref
        elif doc_id == "tribe_names":
            return mock_names_ref
        else:
            m_ref = MagicMock()
            m_ref.get.return_value.exists = False
            return m_ref

    mock_fs.collection.return_value.document.side_effect = document_route

    # Mock LLM response for tribe naming
    mock_response = MagicMock()
    mock_response.text = '{"0": "Cozy Variety Coalition"}'
    mock_safe_generate.return_value = mock_response

    # Execute
    calculate_daily_ecosystem_analytics("dummy-key")

    # Assertions
    mock_store_snapshot.assert_called_once()
    snapshot = mock_store_snapshot.call_args[0][0]
    assert "num_tribes" in snapshot
    assert "tribe_assignments" in snapshot
    assert "constellation_coords_galaxy" in snapshot


@pytest.mark.anyio
@patch("ag_kaggle_5day.cron.start_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.cron.stop_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.agents.advisor.trigger_daily_expose_job", new=AsyncMock())
@patch("ag_kaggle_5day.agents.scraper.calculate_hourly_correlation", new=MagicMock())
@patch("ag_kaggle_5day.agents.advisor.run_daily_analytics_aggregation", new=MagicMock())
@patch("ag_kaggle_5day.cron.get_effective_key")
@patch("ag_kaggle_5day.cron.refresh_hourly_cache")
@patch("ag_kaggle_5day.cron.query_remote_agent", new_callable=AsyncMock)
@patch("ag_kaggle_5day.cron.TwitchAPIClient")
@patch("ag_kaggle_5day.cron.YouTubeAPIClient")
@patch("ag_kaggle_5day.cron.get_app_cache_state")
@patch("ag_kaggle_5day.cron.store_app_cache_state")
async def test_run_cron_refresh_skips_playbooks_when_fresh(
    mock_store_app_cache_state,
    mock_get_app_cache_state,
    mock_youtube_client,
    mock_twitch_client,
    mock_query_remote_agent,
    mock_refresh_hourly_cache,
    mock_get_effective_key,
):
    import time

    # Setup mocks
    mock_get_effective_key.return_value = "dummy-api-key"
    mock_get_app_cache_state.return_value = {
        "last_run": time.time()
    }  # Fresh status cache
    mock_twitch = MagicMock()
    mock_twitch_client.return_value = mock_twitch
    mock_youtube = MagicMock()
    mock_youtube_client.return_value = mock_youtube

    # Execute
    await run_cron_refresh()

    # Assertions
    mock_get_effective_key.assert_called_once()
    mock_refresh_hourly_cache.assert_called_once()
    # Playbook generation should NOT be called
    mock_query_remote_agent.assert_not_called()
    mock_store_app_cache_state.assert_not_called()


@pytest.mark.anyio
@patch("ag_kaggle_5day.cron.start_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.cron.stop_raid_sentinel", new=AsyncMock())
@patch("ag_kaggle_5day.agents.advisor.trigger_daily_expose_job", new=AsyncMock())
@patch("ag_kaggle_5day.agents.scraper.calculate_hourly_correlation", new=MagicMock())
@patch("ag_kaggle_5day.agents.advisor.run_daily_analytics_aggregation", new=MagicMock())
@patch("ag_kaggle_5day.cron.get_effective_key")
@patch("ag_kaggle_5day.cron.refresh_hourly_cache")
@patch("ag_kaggle_5day.cron.query_remote_agent", new_callable=AsyncMock)
@patch("ag_kaggle_5day.cron.TwitchAPIClient")
@patch("ag_kaggle_5day.cron.YouTubeAPIClient")
@patch("ag_kaggle_5day.cron.get_app_cache_state")
@patch("ag_kaggle_5day.cron.store_app_cache_state")
async def test_run_cron_refresh_playbook_failure_non_fatal(
    mock_store_app_cache_state,
    mock_get_app_cache_state,
    mock_youtube_client,
    mock_twitch_client,
    mock_query_remote_agent,
    mock_refresh_hourly_cache,
    mock_get_effective_key,
):
    # Setup mocks
    mock_get_effective_key.return_value = "dummy-api-key"
    mock_get_app_cache_state.return_value = None
    mock_query_remote_agent.side_effect = Exception("Failed to generate playbooks")
    mock_twitch = MagicMock()
    mock_twitch_client.return_value = mock_twitch
    mock_youtube = MagicMock()
    mock_youtube_client.return_value = mock_youtube

    # Execute should NOT raise an exception
    await run_cron_refresh()

    # Assertions
    mock_get_effective_key.assert_called_once()
    mock_refresh_hourly_cache.assert_called_once()
    mock_query_remote_agent.assert_called_once()
    # Playbooks status should NOT be updated since it failed
    mock_store_app_cache_state.assert_not_called()
