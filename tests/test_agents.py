"""
test_agents.py — Unit tests for the scraper and advisor agents.

All Twitch Helix and YouTube API calls are mocked so tests run without
real credentials.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from ag_kaggle_5day.agents.advisor import get_recommendation
from ag_kaggle_5day.agents.scraper import (
    TwitchAPIClient,
    YouTubeAPIClient,
    _calculate_score,
    discover_top5_games,
    scrape_metrics,
)

# ---------------------------------------------------------------------------
# TwitchAPIClient unit tests
# ---------------------------------------------------------------------------


def test_twitch_client_not_configured_without_env(monkeypatch):
    """TwitchAPIClient.is_configured is False when env vars are absent."""
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    client = TwitchAPIClient()
    assert not client.is_configured


def test_twitch_client_configured_with_env(monkeypatch):
    """TwitchAPIClient.is_configured is True when env vars are present."""
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fake_id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "fake_secret")
    client = TwitchAPIClient()
    assert client.is_configured


def test_twitch_get_top_games_mock():
    """get_top_games parses the Helix response correctly."""
    client = TwitchAPIClient(client_id="fake", client_secret="fake")
    client._token = "tok"
    client._token_expires_at = 9999999999.0

    mock_resp = {
        "data": [
            {"id": "1", "name": "Fortnite", "box_art_url": ""},
            {"id": "2", "name": "VALORANT", "box_art_url": ""},
        ]
    }
    with patch.object(client, "_helix_get", return_value=mock_resp):
        games = client.get_top_games(2)
    assert len(games) == 2
    assert games[0]["name"] == "Fortnite"


def test_twitch_get_viewers_aggregates_pages():
    """get_viewers_for_game sums viewer_count across streams."""
    client = TwitchAPIClient(client_id="fake", client_secret="fake")
    client._token = "tok"
    client._token_expires_at = 9999999999.0

    page1 = {
        "data": [{"viewer_count": 5000}, {"viewer_count": 3000}],
        "pagination": {"cursor": "abc"},
    }
    page2 = {"data": [{"viewer_count": 2000}], "pagination": {}}

    call_count = 0

    def mock_helix_get(path, params):
        nonlocal call_count
        call_count += 1
        return page1 if call_count == 1 else page2

    with patch.object(client, "_helix_get", side_effect=mock_helix_get):
        result = client.get_viewers_for_game("1", "Fortnite")

    assert result["twitch_viewers"] == 10000
    assert result["stream_count"] == 3


# ---------------------------------------------------------------------------
# YouTubeAPIClient unit tests
# ---------------------------------------------------------------------------


def test_youtube_client_not_configured_without_env(monkeypatch):
    """YouTubeAPIClient.is_configured is False when env var is absent."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    client = YouTubeAPIClient()
    assert not client.is_configured


def test_youtube_get_viewers_aggregates():
    """get_viewers_for_game sums concurrentViewers from liveStreamingDetails."""
    from unittest.mock import MagicMock, patch

    client = YouTubeAPIClient(api_key="fake_yt_key")

    search_mock = MagicMock()
    search_mock.raise_for_status = MagicMock()
    search_mock.json.return_value = {
        "items": [{"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}]
    }

    videos_mock = MagicMock()
    videos_mock.raise_for_status = MagicMock()
    videos_mock.json.return_value = {
        "items": [
            {
                "liveStreamingDetails": {"concurrentViewers": "12000"},
                "snippet": {
                    "channelTitle": "YoutuberA",
                    "channelId": "chanA",
                    "title": "Stream A",
                },
            },
            {
                "liveStreamingDetails": {"concurrentViewers": "8000"},
                "snippet": {
                    "channelTitle": "YoutuberB",
                    "channelId": "chanB",
                    "title": "Stream B",
                },
            },
        ]
    }

    with (
        patch(
            "ag_kaggle_5day.agents.scraper.youtube.YouTubeAPIClient._scrape_viewers_via_html",
            return_value=None,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.youtube.requests.get",
            side_effect=[search_mock, videos_mock],
        ),
    ):
        result = client.get_viewers_for_game("Minecraft")

    assert result["youtube_viewers"] == 20000
    assert result["stream_count"] == 2
    assert len(result["top_streamers"]) == 2
    assert result["top_streamers"][0]["user_name"] == "YoutuberA"
    assert result["top_streamers"][0]["user_login"] == "chanA"
    assert result["top_streamers"][0]["platform"] == "youtube"


# ---------------------------------------------------------------------------
# discover_top5_games tests
# ---------------------------------------------------------------------------


def test_discover_top5_uses_twitch_when_configured(monkeypatch):
    """discover_top5_games returns live data when Twitch is configured."""
    monkeypatch.setenv("TWITCH_CLIENT_ID", "fake_id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "fake_secret")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    twitch = TwitchAPIClient()
    twitch._token = "tok"
    twitch._token_expires_at = 9999999999.0

    top_games_resp = {
        "data": [{"id": "1", "name": "Fortnite"}, {"id": "2", "name": "VALORANT"}]
    }
    viewers_resp = {"data": [{"viewer_count": 5000}], "pagination": {}}

    with patch.object(
        twitch, "_helix_get", side_effect=[top_games_resp, viewers_resp, viewers_resp]
    ):
        games = discover_top5_games(twitch_client=twitch)

    assert len(games) >= 1
    assert all(g["data_quality"] == "live" for g in games)
    assert all(g["tier"] == "trending" for g in games)


def test_discover_top5_falls_back_to_staples_when_unconfigured(monkeypatch):
    """discover_top5_games returns no_live_data fallback when no APIs configured."""
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    games = discover_top5_games(api_key=None)
    assert len(games) == 5
    assert all(g["data_quality"] == "no_live_data" for g in games)
    assert all(g["tier"] == "trending" for g in games)


# ---------------------------------------------------------------------------
# scrape_metrics tests
# ---------------------------------------------------------------------------


def test_scrape_metrics_custom_games_written_to_cache(tmp_path, monkeypatch):
    """
    scrape_metrics() with custom_games fetches viewership, tags entries
    custom=True / tier="custom", and writes them to cache.json.
    """
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    # Patch CACHE_FILE to use tmp_path
    import ag_kaggle_5day.agents.scraper as scraper_mod

    orig_cache = scraper_mod.CACHE_FILE
    orig_lock = scraper_mod._CACHE_LOCK_FILE
    scraper_mod.CACHE_FILE = str(tmp_path / "cache.json")
    scraper_mod._CACHE_LOCK_FILE = str(tmp_path / "cache.json.lock")

    try:
        games, logs = scrape_metrics(custom_games=["Pong", "Tetris"])
        assert len(games) == 2
        assert os.path.exists(scraper_mod.CACHE_FILE)
        for g in games:
            assert "title" in g
            assert g.get("custom") is True
            assert g.get("tier") == "custom"
            assert "data_quality" in g
    finally:
        scraper_mod.CACHE_FILE = orig_cache
        scraper_mod._CACHE_LOCK_FILE = orig_lock


def test_scrape_metrics_no_args_returns_cache(tmp_path, monkeypatch):
    """scrape_metrics() with no args returns cache.json contents without scraping."""
    import ag_kaggle_5day.agents.scraper as scraper_mod

    orig_cache = scraper_mod.CACHE_FILE
    orig_lock = scraper_mod._CACHE_LOCK_FILE
    scraper_mod.CACHE_FILE = str(tmp_path / "cache.json")
    scraper_mod._CACHE_LOCK_FILE = str(tmp_path / "cache.json.lock")

    seed = [
        {"title": "Minecraft", "avg_viewers": 125000, "custom": False, "tier": "staple"}
    ]
    with open(scraper_mod.CACHE_FILE, "w") as f:
        json.dump(seed, f)

    try:
        cached, logs = scrape_metrics()
        assert len(cached) == 1
        assert cached[0]["title"] == "Minecraft"
    finally:
        scraper_mod.CACHE_FILE = orig_cache
        scraper_mod._CACHE_LOCK_FILE = orig_lock


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------


def test_calculate_score_zero_viewers():
    assert _calculate_score(0, 0) == 0


def test_calculate_score_large_viewership():
    score = _calculate_score(100000, 50000)
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# Advisor tests
# ---------------------------------------------------------------------------


def test_get_recommendation_fallback():
    """get_recommendation returns the fallback message when no API key is set."""
    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]

    try:
        rec = get_recommendation("What game is best tonight?")
        assert "GEMINI_API_KEY is not set" in rec
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_youtube_client_rate_limiting():
    """Verify that YouTubeAPIClient sets _quota_exceeded on 403/429
    and bypasses requests."""
    # Reset class state initially
    YouTubeAPIClient._quota_exceeded = False
    client = YouTubeAPIClient(api_key="fake_yt_key")
    assert client.is_configured

    # Mock responses: first one returns 429
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.raise_for_status = MagicMock()

    with (
        patch(
            "ag_kaggle_5day.agents.scraper.youtube.YouTubeAPIClient._scrape_viewers_via_html",
            return_value=None,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.youtube.requests.get", return_value=mock_429
        ) as mock_get,
    ):
        res = client.get_viewers_for_game("Brotato")
        assert res["youtube_viewers"] == 0
        assert YouTubeAPIClient._quota_exceeded is True
        assert not client.is_configured
        assert mock_get.call_count == 1

    # Second call should bypass requests entirely
    with (
        patch(
            "ag_kaggle_5day.agents.scraper.youtube.YouTubeAPIClient._scrape_viewers_via_html",
            return_value=None,
        ),
        patch("ag_kaggle_5day.agents.scraper.youtube.requests.get") as mock_get_bypass,
    ):
        res = client.get_viewers_for_game("Minecraft")
        assert res["youtube_viewers"] == 0
        assert mock_get_bypass.call_count == 0

    # Initializing with a new key should reset it
    new_client = YouTubeAPIClient(api_key="new_fake_key")
    assert not YouTubeAPIClient._quota_exceeded
    assert new_client.is_configured


def test_safe_generate_content_fallback():
    """Verify safe_generate_content tries alternative models on failure
    and propagates final error."""
    from ag_kaggle_5day.agents.scraper import safe_generate_content

    # Create a mock response that has a text attribute
    mock_response = MagicMock()
    mock_response.text = "hi"

    # Create a mock client
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_config = {
        "default_model": "gemma-4-26b-a4b-it",
        "default_chain": ["gemma-4-26b-a4b-it", "gemma-4-31b-it"],
    }

    with patch(
        "ag_kaggle_5day.agents.scraper.load_model_config", return_value=mock_config
    ):
        # 1. Successful call on first attempt
        with patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_client
        ):
            res = safe_generate_content(
                api_key="test-key", model="primary-model", contents="hello"
            )
            assert res.text == "hi"
            assert mock_client.models.generate_content.call_count == 1

            # Verify call arguments
            args, kwargs = mock_client.models.generate_content.call_args
            assert kwargs["model"] == "primary-model"
            assert kwargs["contents"] == "hello"

        # 2. Falls back to first alternative when primary raises a generic error
        mock_client.reset_mock()
        call_models = []

        def generate_content_side_effect(model, contents, config=None):
            call_models.append(model)
            if model == "primary-model":
                raise ValueError("Primary failed")
            resp = MagicMock()
            resp.text = f"ok_{model}"
            return resp

        mock_client.models.generate_content.side_effect = generate_content_side_effect

        with patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_client
        ):
            res = safe_generate_content(
                api_key="test-key", model="primary-model", contents="hello"
            )
            assert res.text == "ok_gemma-4-26b-a4b-it"
            assert len(call_models) == 2
            assert call_models[0] == "primary-model"

        # 3. Primary model is not duplicated when it already appears in the fallback
        # list
        mock_client.reset_mock()
        call_models.clear()

        def generate_content_all_fail(model, contents, config=None):
            call_models.append(model)
            raise ValueError(f"failed {model}")

        mock_client.models.generate_content.side_effect = generate_content_all_fail

        with patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_client
        ):
            try:
                safe_generate_content(
                    api_key="test-key", model="gemma-4-31b-it", contents="hello"
                )
            except ValueError:
                pass

        assert call_models.count("gemma-4-31b-it") == 1
        assert call_models == [
            "gemma-4-31b-it",
            "gemma-4-26b-a4b-it",
        ]


def test_safe_generate_content_429_raises_gemini_error():
    """Verify safe_generate_content raises _GeminiError(429) when
    exhausted due to 429 errors."""
    from google.genai.errors import ClientError

    from ag_kaggle_5day.agents.scraper import _GeminiError, safe_generate_content

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = ClientError(
        429, "429 RESOURCE_EXHAUSTED"
    )

    with patch(
        "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_client
    ):
        try:
            safe_generate_content(
                api_key="test-key", model="gemini-3.5-flash", contents="hello"
            )
            assert False, "Should have raised _GeminiError"
        except _GeminiError as e:
            assert e.code == 429
            assert "429" in str(e)


def test_youtube_persistent_quota_and_cache_reuse(tmp_path, monkeypatch):
    """Verify persistent quota state checks and YouTube cache reuse logic."""
    import time

    import ag_kaggle_5day.agents.scraper as scraper_mod

    # Patch CACHE_FILE and QUOTA_STATUS_FILE to use tmp_path
    orig_cache = scraper_mod.CACHE_FILE
    orig_lock = scraper_mod._CACHE_LOCK_FILE
    orig_quota = scraper_mod.QUOTA_STATUS_FILE
    orig_quota_lock = scraper_mod._QUOTA_LOCK_FILE

    scraper_mod.CACHE_FILE = str(tmp_path / "cache.json")
    scraper_mod._CACHE_LOCK_FILE = str(tmp_path / "cache.json.lock")
    scraper_mod.QUOTA_STATUS_FILE = str(tmp_path / "quota_status.json")
    scraper_mod._QUOTA_LOCK_FILE = str(tmp_path / "quota_status.lock")

    try:
        # Reset any static state
        YouTubeAPIClient._quota_exceeded = False
        scraper_mod._set_quota_exceeded_persistent(False)

        # Test 1: Check persistent quota flag behavior
        client = YouTubeAPIClient(api_key="fake_key")
        assert client.is_configured

        scraper_mod._set_quota_exceeded_persistent(True)
        assert not client.is_configured
        assert scraper_mod._is_quota_exceeded_persistent()

        # Reset key clears block
        new_client = YouTubeAPIClient(api_key="different_key")
        assert new_client.is_configured
        assert not scraper_mod._is_quota_exceeded_persistent()

        # Test 2: Cache reuse lookup
        seed_data = [
            {
                "title": "Minecraft",
                "category": "Sandbox",
                "avg_viewers": 125000,
                "twitch_viewers": 100000,
                "youtube_viewers": 25000,
                "avg_length_hours": 3.2,
                "score": 92,
                "source": "YouTube Data API v3",
                "data_quality": "live",
                "youtube_fetched_at": time.time(),
            }
        ]
        with open(scraper_mod.CACHE_FILE, "w") as f:
            json.dump(seed_data, f)

        cached_val = scraper_mod._get_cached_youtube_viewers("Minecraft")
        assert cached_val is not None
        assert cached_val["youtube_viewers"] == 25000

        # Check case insensitivity
        cached_val_lower = scraper_mod._get_cached_youtube_viewers("minecraft")
        assert cached_val_lower is not None
        assert cached_val_lower["youtube_viewers"] == 25000

        # Check non-existent game
        assert scraper_mod._get_cached_youtube_viewers("UnknownGame") is None

    finally:
        # Clean up files if they exist
        scraper_mod._set_quota_exceeded_persistent(False)
        scraper_mod.CACHE_FILE = orig_cache
        scraper_mod._CACHE_LOCK_FILE = orig_lock
        scraper_mod.QUOTA_STATUS_FILE = orig_quota
        scraper_mod._QUOTA_LOCK_FILE = orig_quota_lock


def test_markdown_news_cache(tmp_path):
    """Verify parse_news_markdown and write_news_markdown function correctly."""
    from ag_kaggle_5day.agents.advisor import parse_news_markdown, write_news_markdown

    filepath = str(tmp_path / "news_cache.md")

    news_data = {
        "minecraft": {
            "articles": [
                {
                    "title": "Minecraft news 1",
                    "url": "http://minecraft.net",
                    "summary": "Minecraft is great.",
                },
                {
                    "title": "Minecraft news 2",
                    "url": "http://minecraft.net/2",
                    "summary": "Minecraft patch released.",
                },
            ],
            "fetched_at": 12345.6,
        },
        "fortnite": {
            "articles": [
                {
                    "title": "Fortnite news 1",
                    "url": "http://fortnite.com",
                    "summary": "Fortnite season updates.",
                }
            ],
            "fetched_at": 78910.1,
        },
    }

    # Write to markdown
    write_news_markdown(filepath, news_data)

    # Read and parse back
    parsed_data = parse_news_markdown(filepath)

    assert "minecraft" in parsed_data
    assert "fortnite" in parsed_data
    assert len(parsed_data["minecraft"]["articles"]) == 2
    assert parsed_data["minecraft"]["fetched_at"] == 12345.6
    assert parsed_data["minecraft"]["articles"][0]["title"] == "Minecraft news 1"
    assert parsed_data["minecraft"]["articles"][0]["url"] == "http://minecraft.net"
    assert parsed_data["minecraft"]["articles"][0]["summary"] == "Minecraft is great."
    assert parsed_data["fortnite"]["fetched_at"] == 78910.1
    assert parsed_data["fortnite"]["articles"][0]["title"] == "Fortnite news 1"


def test_prefetch_news_freshness(tmp_path):
    """Verify prefetch_news_for_games_sync skips fetching when cached news
    is fresh (< 12 hours)."""
    import time

    import ag_kaggle_5day.agents.advisor as advisor_mod
    from ag_kaggle_5day.agents.advisor import (
        prefetch_news_for_games_sync,
        write_news_markdown,
    )

    # Setup tmp cache file
    filepath = str(tmp_path / "news_cache.md")
    orig_cache_file = advisor_mod.NEWS_CACHE_FILE
    advisor_mod.NEWS_CACHE_FILE = filepath

    try:
        now = time.time()
        news_data = {
            "fresh_game": {
                "articles": [
                    {
                        "title": "Fresh Info",
                        "url": "http://example.com",
                        "summary": "Very recent.",
                    }
                ],
                "fetched_at": now - 3600,  # 1 hour ago (fresh)
            },
            "stale_game": {
                "articles": [
                    {
                        "title": "Old Info",
                        "url": "http://example.com",
                        "summary": "Ancient.",
                    }
                ],
                "fetched_at": now - 54000,  # 15 hours ago (stale)
            },
        }
        write_news_markdown(filepath, news_data)

        games = [
            {"title": "Fresh_Game"},
            {"title": "Stale_Game"},
            {"title": "Uncached_Game"},
        ]

        with patch("ag_kaggle_5day.agents.advisor.get_game_news") as mock_get_news:
            prefetch_news_for_games_sync(games, api_key="fake_key", model="fake_model")

            # Should NOT call get_game_news for Fresh_Game.
            # Should call get_game_news for Stale_Game and Uncached_Game.
            called_games = [call[0][0] for call in mock_get_news.call_args_list]
            assert "Fresh_Game" not in called_games
            assert "Stale_Game" in called_games
            assert "Uncached_Game" in called_games

    finally:
        advisor_mod.NEWS_CACHE_FILE = orig_cache_file


def test_prefetch_news_throttling(tmp_path):
    """Verify prefetch_news_for_games_sync throttles to 8 oldest games."""
    import time

    import ag_kaggle_5day.agents.advisor as advisor_mod
    from ag_kaggle_5day.agents.advisor import (
        prefetch_news_for_games_sync,
        write_news_markdown,
    )

    filepath = str(tmp_path / "news_cache.md")
    orig_cache_file = advisor_mod.NEWS_CACHE_FILE
    advisor_mod.NEWS_CACHE_FILE = filepath

    try:
        now = time.time()
        # Create 12 stale games with different fetched_at ages
        # oldest (candidate 0) to youngest (candidate 11)
        news_data = {}
        games = []
        for i in range(12):
            game_name = f"Game_{i}"
            # i = 0 (fetched 20h ago - oldest), i = 11 (fetched 13h ago - youngest)
            fetched_at = now - (20 - i / 2.0) * 3600
            news_data[game_name.lower()] = {
                "articles": [
                    {
                        "title": "Old Info",
                        "url": "http://example.com",
                        "summary": "Old",
                    }
                ],
                "fetched_at": fetched_at,
            }
            games.append({"title": game_name})

        write_news_markdown(filepath, news_data)

        with patch("ag_kaggle_5day.agents.advisor.get_game_news") as mock_get_news:
            prefetch_news_for_games_sync(games, api_key="fake_key", model="fake_model")

            called_games = [call[0][0] for call in mock_get_news.call_args_list]
            # Should have fetched exactly 8 oldest games (Game_0 to Game_7)
            assert len(called_games) == 8
            for i in range(8):
                assert f"Game_{i}" in called_games
            # Game_8 to Game_11 should not be called (skipped due to throttling)
            for i in range(8, 12):
                assert f"Game_{i}" not in called_games

    finally:
        advisor_mod.NEWS_CACHE_FILE = orig_cache_file


def test_gemini_error_handling(tmp_path):
    """Verify that get_game_news handles _GeminiError correctly and fallback is safe."""
    import ag_kaggle_5day.agents.advisor as advisor_mod
    from ag_kaggle_5day.agents.advisor import get_game_news
    from ag_kaggle_5day.agents.scraper import _GeminiError

    filepath = str(tmp_path / "news_cache.md")
    orig_cache_file = advisor_mod.NEWS_CACHE_FILE
    advisor_mod.NEWS_CACHE_FILE = filepath

    try:
        # Mock safe_generate_content to raise _GeminiError
        with patch(
            "ag_kaggle_5day.agents.advisor.safe_generate_content",
            side_effect=_GeminiError(429, "Too Many Requests"),
        ):
            # It should handle the exception and return fallback
            articles = get_game_news("Minecraft", api_key="fake_key", refresh=True)
            assert len(articles) > 0
            assert "failed" in articles[0]["title"].lower()
    finally:
        advisor_mod.NEWS_CACHE_FILE = orig_cache_file


def test_parse_json_response_robustness():
    """Verify parse_json_response extracts JSON robustly even with
    leading/trailing text with brackets."""
    from ag_kaggle_5day.agents.scraper import parse_json_response

    # 1. Clean JSON array
    text = '[{"title": "a", "url": "b", "summary": "c"}]'
    assert parse_json_response(text) == [{"title": "a", "url": "b", "summary": "c"}]

    # 2. JSON array with trailing explanation text containing brackets
    text = (
        '[{"title": "a", "url": "b", "summary": "c"}]\n'
        "Note: [Google Search] was utilized."
    )
    assert parse_json_response(text) == [{"title": "a", "url": "b", "summary": "c"}]

    # 3. JSON array with leading text containing brackets and trailing
    # text containing brackets
    text = (
        "Here is the results for [Counter-Strike]:\n"
        '[{"title": "a", "url": "b", "summary": "c"}]\n'
        "Hope you like it [Cheers]."
    )
    assert parse_json_response(text) == [{"title": "a", "url": "b", "summary": "c"}]


def test_custom_report_background_generation(tmp_path):
    """Verify that get_comparative_analytics correctly triggers background
    report generation."""
    import ag_kaggle_5day.agents.advisor as advisor_mod
    from ag_kaggle_5day.agents.advisor import get_comparative_analytics

    # Setup tmp custom report file
    filepath = str(tmp_path / "custom_report.json")
    orig_custom_file = advisor_mod.CUSTOM_REPORT_FILE
    orig_lock_file = advisor_mod._CUSTOM_REPORT_LOCK_FILE
    advisor_mod.CUSTOM_REPORT_FILE = filepath
    advisor_mod._CUSTOM_REPORT_LOCK_FILE = filepath + ".lock"

    try:
        custom_games = ["Pong", "Tetris"]

        # Mock multiprocessing.Process
        with patch("multiprocessing.Process") as mock_process:
            # 1. First call: no file exists. Should trigger generation and
            # return placeholder.
            report = get_comparative_analytics(custom_games, api_key="fake_key")
            assert "Generating Custom Comparative Analytics" in report
            assert mock_process.call_count == 1

            # 2. Second call: status is generating. Should NOT trigger another process.
            mock_process.reset_mock()
            report2 = get_comparative_analytics(custom_games, api_key="fake_key")
            assert "Generating Custom Comparative Analytics" in report2
            assert mock_process.call_count == 0

    finally:
        advisor_mod.CUSTOM_REPORT_FILE = orig_custom_file
        advisor_mod._CUSTOM_REPORT_LOCK_FILE = orig_lock_file


def test_dynamic_staple_games():
    """Verify that STAPLE_GAMES dynamically returns games from load_model_config."""
    from ag_kaggle_5day.agents.scraper import STAPLE_GAMES

    custom_staples = [
        {
            "title": "CustomStapleGame",
            "category": "Test",
            "avg_viewers": 100,
            "avg_length_hours": 2.0,
            "score": 50,
        }
    ]

    with patch(
        "ag_kaggle_5day.agents.scraper.load_model_config",
        return_value={"staple_games": custom_staples},
    ):
        assert len(STAPLE_GAMES) == 1
        assert STAPLE_GAMES[0]["title"] == "CustomStapleGame"
        assert list(STAPLE_GAMES) == custom_staples


def test_generate_stream_playbook():
    """Verify generate_stream_playbook scores games and produces
    structured playbooks."""
    from ag_kaggle_5day.agents.advisor import generate_stream_playbook

    mock_games = [
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 120000,
            "avg_length_hours": 3.0,
            "score": 90,
            "tier": "staple",
        },
        {
            "title": "VALORANT",
            "category": "FPS",
            "avg_viewers": 150000,
            "avg_length_hours": 2.5,
            "score": 95,
            "tier": "staple",
        },
        {
            "title": "Hades II",
            "category": "Roguelike",
            "avg_viewers": 40000,
            "avg_length_hours": 3.5,
            "score": 88,
            "tier": "trending",
        },
        {
            "title": "CustomGameX",
            "category": "Indie",
            "avg_viewers": 5000,
            "avg_length_hours": 4.0,
            "score": 75,
            "tier": "custom",
        },
    ]

    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    try:
        with (
            patch(
                "ag_kaggle_5day.agents.advisor.get_cached_games",
                return_value=mock_games,
            ),
            patch(
                "ag_kaggle_5day.agents.scraper.load_model_config",
                return_value={"enable_affiliate_playbook": False},
            ),
        ):
            # 1. Test offline/no-key fallback
            res = generate_stream_playbook(
                vibe="chill",
                scale="starting",
                duration=3.0,
                stream_goal="engagement",
                api_key=None,
            )
            assert res["vibe"] == "chill"
            assert res["scale"] == "starting"
            assert res["stream_goal"] == "engagement"
            assert len(res["playbooks"]) == 4
            games_matched = [p["game"] for p in res["playbooks"]]
            assert "Minecraft" in games_matched
            assert "Hades II" in games_matched
            assert "CustomGameX" in games_matched
            assert "platform" in res["playbooks"][0]
            assert "hook" in res["playbooks"][0]
            assert "stream_goal" in res["playbooks"][0]
            assert "formatted_time" in res["playbooks"][0]
            assert "twitch_viewers" in res["playbooks"][0]

            # 2. Test Gemini integration mock
            mock_response = MagicMock()
            mock_response.text = (
                '{"platform": "Both - Twitch and YouTube Gaming", '
                '"hook": "Run a speedrun practice", '
                '"advice": "Set up overlay. Stream for 3 hours.", '
                '"preparation": "Configure stream setup."}'
            )

            with patch(
                "ag_kaggle_5day.agents.advisor.safe_generate_content",
                return_value=mock_response,
            ):
                res_gemini = generate_stream_playbook(
                    vibe="chill",
                    scale="starting",
                    duration=3.0,
                    stream_goal="growth",
                    api_key="AIzaSyTest",
                )
                assert len(res_gemini["playbooks"]) == 4
                assert res_gemini["stream_goal"] == "growth"
                assert "CustomGameX" in [p["game"] for p in res_gemini["playbooks"]]
                assert (
                    res_gemini["playbooks"][0]["platform"]
                    == "Both - Twitch and YouTube Gaming"
                )
                assert res_gemini["playbooks"][0]["hook"] == "Run a speedrun practice"
                assert (
                    res_gemini["playbooks"][0]["advice"]
                    == "Set up overlay. Stream for 3 hours."
                )
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_dashboard_mutation_tools(tmp_path, monkeypatch):
    """Verify add_custom_game_to_dashboard and
    remove_custom_game_from_dashboard tools."""
    import ag_kaggle_5day.agents.scraper as scraper_mod
    from ag_kaggle_5day.advisor_agent.agent import (
        add_custom_game_to_dashboard,
        remove_custom_game_from_dashboard,
    )

    orig_cache = scraper_mod.CACHE_FILE
    orig_lock = scraper_mod._CACHE_LOCK_FILE
    scraper_mod.CACHE_FILE = str(tmp_path / "cache.json")
    scraper_mod._CACHE_LOCK_FILE = str(tmp_path / "cache.json.lock")

    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    try:
        # Seed cache with standard games
        seed = [
            {
                "title": "Minecraft",
                "avg_viewers": 100,
                "custom": False,
                "tier": "staple",
            }
        ]
        with open(scraper_mod.CACHE_FILE, "w") as f:
            json.dump(seed, f)

        with patch("ag_kaggle_5day.agents.advisor.prefetch_news_for_games"):
            # 1. Add game
            res = add_custom_game_to_dashboard("Stardew Valley")
            assert "Successfully added" in res

            # Check added to cache
            with open(scraper_mod.CACHE_FILE, "r") as f:
                games = json.load(f)
            assert len(games) == 2
            assert any(g["title"] == "Stardew Valley" for g in games)

            # 2. Add duplicate game
            res_dup = add_custom_game_to_dashboard("Stardew Valley")
            assert "already present" in res_dup

            # 3. Remove game
            res_rem = remove_custom_game_from_dashboard("Stardew Valley")
            assert "Successfully removed" in res_rem

            with open(scraper_mod.CACHE_FILE, "r") as f:
                games = json.load(f)
            assert len(games) == 1
            assert not any(g["title"] == "Stardew Valley" for g in games)

            # 4. Remove non-existent game
            res_rem_non = remove_custom_game_from_dashboard("Stardew Valley")
            assert "not a custom game" in res_rem_non
    finally:
        scraper_mod.CACHE_FILE = orig_cache
        scraper_mod._CACHE_LOCK_FILE = orig_lock


def test_get_saturation_data():
    """Verify get_saturation_data returns sorted saturation metrics."""
    from ag_kaggle_5day.advisor_agent.agent import get_saturation_data

    # Seed cache with different viewer counts
    seed = [
        {
            "title": "Game A",
            "avg_viewers": 150000,
            "custom": False,
            "tier": "staple",
            "category": "FPS",
        },
        {
            "title": "Game B",
            "avg_viewers": 500,
            "custom": False,
            "tier": "staple",
            "category": "Indie",
        },
    ]
    with patch(
        "ag_kaggle_5day.advisor_agent.agent.get_cached_games", return_value=seed
    ):
        data = get_saturation_data()
        assert len(data) == 2
        assert data[0]["title"] in ("Game A", "Game B")
        assert "viewer_to_streamer_ratio" in data[0]
        assert "competition_level" in data[0]


# ---------------------------------------------------------------------------
# GCP Storage unit tests
# ---------------------------------------------------------------------------


def test_bq_firestore_client_graceful_fallback(monkeypatch):
    """Verify clients return None gracefully when credentials/environment is missing."""
    import ag_kaggle_5day.agents.gcp_storage as gcp_storage

    gcp_storage._bq_client = None
    gcp_storage._db_client = None

    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_firestore_client,
        search_similar_playbooks,
        store_playbook_vector,
        write_metrics_to_bigquery,
    )

    # Force clients to raise an exception or return None
    with patch(
        "ag_kaggle_5day.agents.gcp_storage.bigquery.Client",
        side_effect=Exception("No credentials"),
    ):
        assert get_bigquery_client() is None

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.firestore.Client",
        side_effect=Exception("No credentials"),
    ):
        assert get_firestore_client() is None

    # Verify functions don't crash when client is None
    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client", return_value=None
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client", return_value=None
        ),
    ):
        write_metrics_to_bigquery([{"title": "Minecraft", "score": 90}])
        store_playbook_vector({"game": "Minecraft"}, "text", "fake_key")
        assert search_similar_playbooks("Minecraft", "fake_key") == []


def test_write_metrics_to_bigquery_calls_client():
    """Verify BigQuery integration creates dataset/table and inserts rows."""
    from ag_kaggle_5day.agents.gcp_storage import write_metrics_to_bigquery

    mock_client = MagicMock()
    mock_client.project = "test-project"

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client",
        return_value=mock_client,
    ):
        games = [{"title": "Minecraft", "avg_viewers": 100, "score": 85}]
        write_metrics_to_bigquery(games)

        assert mock_client.get_dataset.call_count == 1
        assert mock_client.get_table.call_count == 2
        assert mock_client.insert_rows_json.call_count == 1
        # Check that insert_rows_json was called with correct arguments
        args, kwargs = mock_client.insert_rows_json.call_args
        assert args[0] == "test-project.streamer_metrics.hourly_stats"
        assert len(args[1]) == 1
        assert args[1][0]["title"] == "Minecraft"
        assert args[1][0]["score"] == 85.0


def test_store_playbook_vector_calls_client():
    """Verify store_playbook_vector computes embedding and adds doc to Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import store_playbook_vector

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collection.return_value = mock_collection

    mock_embedding_res = MagicMock()
    mock_embedding_res.embeddings = [MagicMock(values=[0.1, 0.2, 0.3])]
    mock_genai = MagicMock()
    mock_genai.models.embed_content.return_value = mock_embedding_res

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        playbook = {
            "game": "Minecraft",
            "platform": "Twitch",
            "hook": "A hook",
            "advice": "Some advice",
        }
        store_playbook_vector(playbook, "Minecraft text content", "fake_key")

        assert mock_genai.models.embed_content.call_count == 1
        assert mock_client.collection.call_count == 1
        assert mock_client.collection.call_args[0][0] == "playbooks"
        assert mock_collection.add.call_count == 1

        added_data = mock_collection.add.call_args[0][0]
        assert added_data["game"] == "Minecraft"
        assert added_data["platform"] == "Twitch"
        assert added_data["text_content"] == "Minecraft text content"


def test_search_similar_playbooks_calls_client():
    """Verify search_similar_playbooks queries Firestore using
    find_nearest kNN query."""
    from ag_kaggle_5day.agents.gcp_storage import search_similar_playbooks

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_query = MagicMock()
    mock_client.collection.return_value = mock_collection
    mock_collection.find_nearest.return_value = mock_query

    # Mock stream results
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "game": "Minecraft",
        "advice": "Retrieved advice",
        "embedding": [0.1, 0.2],
        "timestamp": MagicMock(isoformat=lambda: "2026-06-19T00:00:00Z"),
    }
    mock_query.stream.return_value = [mock_doc]

    mock_embedding_res = MagicMock()
    mock_embedding_res.embeddings = [MagicMock(values=[0.1, 0.2])]
    mock_genai = MagicMock()
    mock_genai.models.embed_content.return_value = mock_embedding_res

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        results = search_similar_playbooks("Minecraft query", "fake_key", limit=2)

        assert mock_genai.models.embed_content.call_count == 1
        assert mock_collection.find_nearest.call_count == 1
        assert mock_query.stream.call_count == 1
        assert len(results) == 1
        assert results[0]["game"] == "Minecraft"
        assert results[0]["advice"] == "Retrieved advice"
        assert "embedding" not in results[0]  # Verify embedding field is stripped
        assert results[0]["timestamp"] == "2026-06-19T00:00:00Z"


def test_hourly_cache_refresh_triggers_bigquery():
    """Verify hourly cache refresh invokes BigQuery write function."""
    from ag_kaggle_5day.agents.advisor import refresh_hourly_cache

    with (
        patch("ag_kaggle_5day.agents.advisor.discover_top_games", return_value=[]),
        patch(
            "ag_kaggle_5day.agents.advisor.scrape_viewership_for_games", return_value=[]
        ),
        patch(
            "ag_kaggle_5day.agents.advisor._generate_comparison_report", return_value=""
        ),
        patch("ag_kaggle_5day.agents.advisor.prefetch_news_for_games"),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.write_metrics_to_bigquery"
        ) as mock_bq_write,
    ):
        refresh_hourly_cache(api_key="fake_key")
        assert mock_bq_write.call_count == 1


def test_playbook_generation_triggers_firestore_store():
    """Verify generate_stream_playbook invokes Firestore storage for each
    generated playbook."""
    from ag_kaggle_5day.agents.advisor import generate_stream_playbook

    mock_games = [
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 100,
            "avg_length_hours": 3.0,
            "score": 90,
            "tier": "staple",
        }
    ]

    mock_response = MagicMock()
    mock_response.text = (
        '{"platform": "Twitch", "hook": "Use themed overlays", '
        '"advice": "Set up overlays and stream.", '
        '"preparation": "Configure stream deck."}'
    )

    with (
        patch(
            "ag_kaggle_5day.agents.advisor.get_cached_games", return_value=mock_games
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.load_model_config",
            return_value={"enable_affiliate_playbook": False},
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.safe_generate_content",
            return_value=mock_response,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.store_playbook_vector"
        ) as mock_store_vector,
    ):
        res = generate_stream_playbook(
            vibe="chill",
            scale="starting",
            duration=3.0,
            stream_goal="performance",
            api_key="fake_key",
        )
        assert len(res["playbooks"]) == 1
        assert mock_store_vector.call_count == 1
        # Check text content parameter
        args, kwargs = mock_store_vector.call_args
        assert args[0]["game"] == "Minecraft"
        assert args[0]["stream_goal"] == "performance"
        assert args[0]["formatted_time"] is not None
        assert "Use themed overlays" in args[1]


def test_recommendation_performs_vector_search():
    """Verify get_recommendation calls search_similar_playbooks to
    inject RAG context."""
    from ag_kaggle_5day.agents.advisor import get_recommendation

    mock_similar = [
        {
            "game": "Minecraft",
            "category": "Sandbox",
            "platform": "Twitch",
            "hook": "Minecraft Hook",
            "advice": "Minecraft Advice",
        }
    ]

    mock_response = MagicMock()
    mock_response.text = "Gemma Advice"

    with (
        patch("ag_kaggle_5day.agents.advisor.get_cached_games", return_value=[]),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.search_similar_playbooks",
            return_value=mock_similar,
        ) as mock_search,
        patch(
            "ag_kaggle_5day.agents.advisor.safe_generate_content",
            return_value=mock_response,
        ),
    ):
        res = get_recommendation("Minecraft recommendation", api_key="fake_key")
        assert res == "Gemma Advice"
        assert mock_search.call_count == 1
        args, kwargs = mock_search.call_args
        assert args[0] == "Minecraft recommendation"


@pytest.mark.anyio
async def test_generate_playbooks_for_current_games_tool():
    """Verify that generate_playbooks_for_current_games tool calls
    the stream playbook workflow."""
    from unittest.mock import AsyncMock

    from ag_kaggle_5day.advisor_agent.agent import generate_playbooks_for_current_games

    mock_event = MagicMock()
    mock_event.output = {"playbooks": [{"game": "Minecraft"}, {"game": "Fortnite"}]}

    mock_runner = MagicMock()
    mock_runner.run_debug = AsyncMock(return_value=[mock_event])

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
        res = await generate_playbooks_for_current_games(
            vibe="chill", scale="starting", duration=3.0
        )
        assert "Successfully generated playbooks for 2 games" in res


@pytest.mark.anyio
async def test_run_periodic_agent_scheduler():
    """Verify that run_periodic_agent_scheduler refreshes metrics and
    runs advisor agent."""
    import ag_kaggle_5day.app as app_mod
    from ag_kaggle_5day.app import run_periodic_agent_scheduler

    # Setup mocks
    mock_runner = MagicMock()

    # run_debug is an async function
    async def mock_run_debug(*args, **kwargs):
        return []

    mock_runner.run_debug = mock_run_debug

    orig_runner = app_mod.advisor_runner
    app_mod.advisor_runner = mock_runner

    try:
        # Mock asyncio.sleep so the test runs instantly and terminates on second call
        with (
            patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]),
            patch("ag_kaggle_5day.app.refresh_hourly_cache") as mock_refresh,
            patch("google.adk.runners.InMemoryRunner", return_value=mock_runner),
        ):
            try:
                await run_periodic_agent_scheduler(
                    api_key="fake_key",
                    twitch_client="mock_twitch",
                    youtube_client="mock_youtube",
                    interval_seconds=10,
                )
            except Exception as e:
                # We catch the Stop loop exception to end the while True loop
                assert str(e) == "Stop loop"

            assert mock_refresh.call_count == 1
            mock_refresh.assert_called_once_with(
                "fake_key", "mock_twitch", "mock_youtube"
            )
    finally:
        app_mod.advisor_runner = orig_runner


def test_youtube_rate_limit_fallback():
    """Verify that when YouTube API is disabled due to quota,
    discover_top5_games falls back to age-insensitive cache."""
    import time

    from ag_kaggle_5day.agents.scraper import YouTubeAPIClient, discover_top5_games

    # Mock Twitch Helix client
    mock_twitch = MagicMock()
    mock_twitch.is_configured = True
    mock_twitch.get_top_games.return_value = [{"id": "123", "name": "Minecraft"}]
    mock_twitch.get_top_games_by_category.return_value = [
        {"id": "123", "name": "Minecraft"}
    ]
    mock_twitch.get_viewers_for_game.return_value = {"twitch_viewers": 150000}

    # Mock YouTube client: configured but quota exceeded
    mock_youtube = MagicMock()
    mock_youtube.api_key = "fake_yt_key"
    YouTubeAPIClient._quota_exceeded = True

    # Mock the cached viewers function to return a stale cached value
    mock_cached_val = {
        "youtube_viewers": 45000,
        "youtube_fetched_at": time.time() - 86400,
    }  # 24 hours old (stale)

    def mock_get_cached_side_effect(game_name, max_age_seconds=43200):
        if max_age_seconds == 999999999:
            return mock_cached_val
        return None

    with patch(
        "ag_kaggle_5day.agents.scraper._get_cached_youtube_viewers",
        side_effect=mock_get_cached_side_effect,
    ) as mock_get_cached:
        results = discover_top5_games(
            api_key="fake_gemini_key",
            twitch_client=mock_twitch,
            youtube_client=mock_youtube,
        )
        assert len(results) == 1
        assert results[0]["youtube_viewers"] == 45000
        assert "Rate-Limited Fallback" in results[0]["source"]

        # Verify it was called twice: once with default 43200, once with 999999999
        assert mock_get_cached.call_count == 2

    # Reset YouTube quota class variable
    YouTubeAPIClient._quota_exceeded = False


def test_get_comparative_analytics_force_refresh():
    """Verify that get_comparative_analytics ignores cached success/error
    reports when force_refresh is True."""
    import json
    import time
    from unittest.mock import mock_open

    from ag_kaggle_5day.agents.advisor import get_comparative_analytics

    mock_cached_data = {
        "custom_games": ["Minecraft"],
        "report": "Old Custom Report",
        "status": "success",
        "generated_at": time.time() - 30.0,
    }

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(mock_cached_data))),
        patch("ag_kaggle_5day.agents.advisor.FileLock"),
        patch("multiprocessing.Process") as mock_process,
    ):
        res = get_comparative_analytics(
            custom_games=["Minecraft"], api_key="fake_key", force_refresh=False
        )
        assert res == "Old Custom Report"
        assert mock_process.call_count == 0

        res_forced = get_comparative_analytics(
            custom_games=["Minecraft"], api_key="fake_key", force_refresh=True
        )
        assert "Generating Custom Comparative Analytics" in res_forced
        assert mock_process.call_count == 1


def test_adk_agent_custom_tools_trigger_report_regeneration():
    """Verify that add_custom_game_to_dashboard and
    remove_custom_game_from_dashboard trigger report regeneration."""
    import json
    from unittest.mock import mock_open

    from ag_kaggle_5day.advisor_agent.agent import (
        add_custom_game_to_dashboard,
        remove_custom_game_from_dashboard,
    )

    # 1. Test add_custom_game_to_dashboard
    mock_games = [
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 100,
            "avg_length_hours": 3.0,
            "score": 90,
            "tier": "staple",
        }
    ]
    mock_scraped = (
        [
            {
                "title": "Pong",
                "category": "Arcade",
                "avg_viewers": 10,
                "avg_length_hours": 1.0,
                "score": 50,
                "custom": True,
                "tier": "custom",
            }
        ],
        ["log"],
    )

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(mock_games))),
        patch(
            "ag_kaggle_5day.advisor_agent.agent.scrape_metrics",
            return_value=mock_scraped,
        ),
        patch("ag_kaggle_5day.agents.advisor.prefetch_news_for_games"),
    ):
        res = add_custom_game_to_dashboard("Pong")
        assert "Successfully added" in res

    # 2. Test remove_custom_game_from_dashboard
    mock_custom_games = [
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 100,
            "avg_length_hours": 3.0,
            "score": 90,
            "tier": "staple",
        },
        {
            "title": "Pong",
            "category": "Arcade",
            "avg_viewers": 10,
            "avg_length_hours": 1.0,
            "score": 50,
            "custom": True,
            "tier": "custom",
        },
    ]
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(mock_custom_games))),
        patch("ag_kaggle_5day.advisor_agent.agent.FileLock"),
    ):
        res = remove_custom_game_from_dashboard("Pong")
        assert "Successfully removed" in res


def test_store_comparison_report_vector():
    """Verify store_comparison_report_vector (deprecated/disabled) does nothing."""
    from ag_kaggle_5day.agents.gcp_storage import store_comparison_report_vector

    mock_client = MagicMock()
    mock_genai = MagicMock()

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        store_comparison_report_vector("<h3>Report</h3>", ["Pong"], "fake_key")

        assert mock_genai.models.embed_content.call_count == 0
        assert mock_client.collection.call_count == 0


def test_store_news_vector():
    """Verify store_news_vector checks duplicates, computes embedding
    and adds doc to Firestore.
    """
    from ag_kaggle_5day.agents.gcp_storage import store_news_vector

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collection.return_value = mock_collection
    # Mock query to return empty list (no duplicate)
    mock_where = mock_collection.where.return_value.where.return_value
    mock_where.limit.return_value.get.return_value = []

    mock_embedding_res = MagicMock()
    mock_embedding_res.embeddings = [MagicMock(values=[0.1, 0.2, 0.3])]
    mock_genai = MagicMock()
    mock_genai.models.embed_content.return_value = mock_embedding_res

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        store_news_vector("Pong", "Headline", "Summary", "http://pong.com", "fake_key")

        assert mock_genai.models.embed_content.call_count == 1
        assert (
            mock_client.collection.call_count == 2
        )  # 1 for checking duplicate, 1 for adding
        assert mock_collection.add.call_count == 1

        added_data = mock_collection.add.call_args[0][0]
        assert added_data["game"] == "Pong"
        assert added_data["headline"] == "Headline"
        assert added_data["summary"] == "Summary"
        assert added_data["url"] == "http://pong.com"


def test_search_similar_comparison_reports():
    """Verify search_similar_comparison_reports (deprecated/disabled)
    returns empty list.
    """
    from ag_kaggle_5day.agents.gcp_storage import search_similar_comparison_reports

    mock_client = MagicMock()
    mock_genai = MagicMock()

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        results = search_similar_comparison_reports("Report query", "fake_key", limit=1)

        assert mock_genai.models.embed_content.call_count == 0
        assert len(results) == 0


def test_search_similar_news():
    """Verify search_similar_news queries Firestore composite index search."""
    from ag_kaggle_5day.agents.gcp_storage import search_similar_news

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_query = MagicMock()
    mock_client.collection.return_value = mock_collection
    mock_collection.find_nearest.return_value = mock_query

    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "game": "Pong",
        "headline": "Headline",
        "summary": "Summary",
        "url": "http://url",
        "embedding": [0.1, 0.2],
        "timestamp": MagicMock(isoformat=lambda: "2026-06-19T00:00:00Z"),
    }
    mock_query.stream.return_value = [mock_doc]

    mock_embedding_res = MagicMock()
    mock_embedding_res.embeddings = [MagicMock(values=[0.1, 0.2])]
    mock_genai = MagicMock()
    mock_genai.models.embed_content.return_value = mock_embedding_res

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_genai
        ),
    ):
        results = search_similar_news("News query", "fake_key", limit=1)

        assert mock_genai.models.embed_content.call_count == 1
        assert mock_collection.find_nearest.call_count == 1
        assert mock_query.stream.call_count == 1
        assert len(results) == 1
        assert results[0]["game"] == "Pong"
        assert results[0]["headline"] == "Headline"
        assert "embedding" not in results[0]


def test_get_past_analysis_context():
    """Verify get_past_analysis_context retrieves playbooks and news and
    formats output.
    """
    from ag_kaggle_5day.agents.advisor import get_past_analysis_context

    mock_playbooks = [
        {
            "game": "Pong",
            "category": "Arcade",
            "platform": "Twitch",
            "hook": "Hook",
            "advice": "Advice",
        }
    ]
    mock_news = [
        {
            "game": "Pong",
            "headline": "Headline",
            "summary": "Summary",
            "url": "http://pong",
        }
    ]

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.search_similar_playbooks",
            return_value=mock_playbooks,
        ) as m_pb,
        patch(
            "ag_kaggle_5day.agents.gcp_storage.search_similar_news",
            return_value=mock_news,
        ) as m_nw,
    ):
        context = get_past_analysis_context("query", "fake_key")
        assert "Relevant Past Playbooks" in context
        assert "Relevant Past News Articles" in context
        assert "Pong" in context
        m_pb.assert_called_once()
        m_nw.assert_called_once()


@pytest.mark.anyio
async def test_comparative_report_workflow():
    """Verify that comparative_report_workflow is deprecated and set to None."""
    from ag_kaggle_5day.advisor_agent.workflows import comparative_report_workflow

    assert comparative_report_workflow is None


@pytest.mark.anyio
async def test_stream_playbook_workflow():
    """Verify that StreamPlaybookWorkflow runs nodes and parallel

    generations successfully.
    """
    import json
    from unittest.mock import patch

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import stream_playbook_workflow

    mock_games = [
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 100,
            "avg_length_hours": 3.0,
            "score": 90,
            "tier": "staple",
        }
    ]

    mock_playbook = {
        "platform": "Twitch",
        "hook": "Mock hook",
        "advice": "Mock advice",
    }

    with (
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.get_cached_games",
            return_value=mock_games,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.load_model_config",
            return_value={"enable_affiliate_playbook": False},
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.generate_and_store_single_playbook_sync",
            return_value=mock_playbook,
        ),
    ):
        runner = InMemoryRunner(node=stream_playbook_workflow)
        events = await runner.run_debug(
            json.dumps({"vibe": "chill", "scale": "starting", "duration": 3.0}),
            user_id="test_user",
            session_id="test_session_2",
            quiet=True,
        )
        assert len(events) > 0
        res = events[-1].output
        assert res["vibe"] == "chill"
        assert len(res["playbooks"]) == 1
        assert res["playbooks"][0] == mock_playbook


def test_infer_category_heuristics(monkeypatch):
    """Verify that _infer_category matches genres by keyword heuristics."""
    # Mock Twitch client configuration to be false to force naive heuristics fallback
    monkeypatch.setattr(
        "ag_kaggle_5day.agents.scraper.twitch.TwitchAPIClient.is_configured",
        False,
    )
    # Mock Firestore client to be None
    monkeypatch.setattr(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        lambda: None,
    )
    from ag_kaggle_5day.agents.scraper import _infer_category

    # 1. MOBA
    assert _infer_category("League of Legends", None) == "MOBA"
    assert _infer_category("dota 2", None) == "MOBA"

    # 2. FPS
    assert _infer_category("Valorant", None) == "FPS"
    assert _infer_category("Counter-Strike 2", None) == "FPS"
    assert _infer_category("Fortnite Battle Royale", None) == "FPS"

    # 3. Sandbox
    assert _infer_category("Minecraft", None) == "Sandbox"
    assert _infer_category("Roblox", None) == "Sandbox"

    # 4. RPG
    assert _infer_category("Elden Ring", None) == "RPG"
    assert _infer_category("Diablo IV", None) == "RPG"

    # 5. Roguelike
    assert _infer_category("Hades II", None) == "Roguelike"
    assert _infer_category("Slay the Spire", None) == "Roguelike"

    # 6. Action-Adventure
    assert _infer_category("Grand Theft Auto V", None) == "Action-Adventure"
    assert _infer_category("Resident Evil 4", None) == "Action-Adventure"

    # 7. IRL
    assert _infer_category("Just Chatting", None) == "IRL"
    assert _infer_category("Talk Shows & Podcasts", None) == "IRL"

    # Fallback
    assert (
        _infer_category("Some random game name that doesn't match", None) == "Unknown"
    )


def test_get_last_known_good_youtube_viewers_bigquery():
    """Verify that _get_last_known_good_youtube_viewers queries
    BigQuery on cache miss.
    """
    import datetime
    from unittest.mock import MagicMock, patch

    import ag_kaggle_5day.agents.scraper as scraper_mod
    from ag_kaggle_5day.agents.scraper import _get_last_known_good_youtube_viewers

    # Reset global cache to prevent leakage from other tests
    scraper_mod._last_known_yt_cache = None

    # Mock cache miss
    with (
        patch(
            "ag_kaggle_5day.agents.scraper._get_cached_youtube_viewers",
            return_value=None,
        ),
        patch("ag_kaggle_5day.agents.gcp_storage.get_bigquery_client") as mock_get_bq,
    ):
        mock_client = MagicMock()
        mock_client.project = "fake-project"
        mock_get_bq.return_value = mock_client

        # Mock BigQuery query result
        mock_row = MagicMock()
        mock_row.title_lower = "minecraft"
        mock_row.youtube_viewers = 12500
        mock_row.timestamp = datetime.datetime.now(datetime.timezone.utc)

        mock_job = MagicMock()
        mock_job.result.return_value = [mock_row]
        mock_client.query.return_value = mock_job

        res = _get_last_known_good_youtube_viewers("Minecraft")
        assert res is not None
        assert res["youtube_viewers"] == 12500
        assert mock_client.query.call_count == 1


def test_get_cached_games_injects_history():
    """Verify that get_cached_games loads 24h history from BigQuery and injects it."""
    import datetime
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import _store, get_cached_games

    # Reset store cache
    _store.history_cache = None
    _store.history_cache_time = 0.0

    mock_games = [{"title": "Minecraft", "category": "Sandbox", "avg_viewers": 100}]
    _store.combined_games = mock_games

    with patch("os.path.exists", return_value=False):
        with patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client"
        ) as mock_get_bq:
            mock_client = MagicMock()
            mock_client.project = "fake-project"
            mock_get_bq.return_value = mock_client

            # Mock historical rows
            mock_row = MagicMock()
            mock_row.title = "Minecraft"
            mock_row.timestamp = datetime.datetime.now(datetime.timezone.utc)
            mock_row.twitch_viewers = 80
            mock_row.youtube_viewers = 20

            mock_job = MagicMock()
            mock_job.result.return_value = [mock_row]
            mock_client.query.return_value = mock_job

            games = get_cached_games()
            assert len(games) == 1
            assert len(games[0]["history"]) == 1
            assert games[0]["history"][0]["viewers"] == 100
            assert _store.history_cache is not None


def test_app_cache_state_storage():
    """Verify store_app_cache_state and get_app_cache_state set/get correctly."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import (
        get_app_cache_state,
        store_app_cache_state,
    )

    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "data": {"test_key": "test_val"},
        "timestamp": "some_time",
    }

    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        return_value=mock_db,
    ):
        # Test get_app_cache_state
        res = get_app_cache_state("test_state")
        assert res == {"test_key": "test_val"}
        mock_db.collection.assert_called_with("system_cache")
        mock_db.collection.return_value.document.assert_called_with("test_state")

        # Test store_app_cache_state
        store_app_cache_state("new_state", {"foo": "bar"})
        mock_db.collection.return_value.document.return_value.set.assert_called_once()


def test_seed_firestore_cache_if_empty():
    """Verify seed_firestore_cache_if_empty checks and seeds Firestore cache."""
    from ag_kaggle_5day.agents.advisor import _store, seed_firestore_cache_if_empty

    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = False  # Simulate empty cache
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    # Clear memory cache first
    _store.combined_games = []
    _store.comparison_report = ""

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        return_value=mock_db,
    ):
        seed_firestore_cache_if_empty(force=False)
        # Should call store/set for both combined_games and comparison_report
        assert mock_db.collection.return_value.document.return_value.set.call_count >= 2
        assert len(_store.combined_games) > 0
        assert _store.comparison_report != ""


def test_generate_comparison_report_padding():
    """Verify that _generate_comparison_report correctly pads the trending games
    count to at least 5 games when category filtering results in a sparse list."""
    from ag_kaggle_5day.agents.advisor import _generate_comparison_report, _store

    # Pre-populate overall cache store with a pool of trending games from other
    # categories to serve as the padding pool
    pool = [
        {
            "title": "VALORANT",
            "category": "FPS",
            "avg_viewers": 100000,
            "score": 90,
            "tier": "trending",
        },
        {
            "title": "League of Legends",
            "category": "MOBA",
            "avg_viewers": 120000,
            "score": 95,
            "tier": "trending",
        },
        {
            "title": "Minecraft",
            "category": "Sandbox",
            "avg_viewers": 80000,
            "score": 88,
            "tier": "trending",
        },
        {
            "title": "Fortnite",
            "category": "FPS",
            "avg_viewers": 150000,
            "score": 92,
            "tier": "trending",
        },
        {
            "title": "World of Warcraft",
            "category": "RPG",
            "avg_viewers": 30000,
            "score": 75,
            "tier": "trending",
        },
        {
            "title": "Hades II",
            "category": "Roguelike",
            "avg_viewers": 15000,
            "score": 70,
            "tier": "trending",
        },
    ]
    _store.combined_games = pool

    # Sparse games list matching RPG (only 1 game: World of Warcraft)
    sparse_games = [
        {
            "title": "World of Warcraft",
            "category": "RPG",
            "avg_viewers": 30000,
            "score": 75,
            "tier": "trending",
        },
        {
            "title": "Sponsored Game Slot",
            "category": "RPG",
            "avg_viewers": 5000,
            "score": 60,
            "tier": "sponsored",
        },
    ]

    # Mock safe_generate_content to see what games summary was generated in the prompt
    mock_response = MagicMock()
    mock_response.text = (
        "<h3>Overview</h3><h3>Comparative Matrix</h3>"
        "<h3>Recommendations & Strategy</h3><h3>Hidden Gem Recommendation</h3>"
    )

    with patch(
        "ag_kaggle_5day.agents.advisor.safe_generate_content",
        return_value=mock_response,
    ) as mock_generate:
        report = _generate_comparison_report(
            sparse_games,
            api_key="fake_key",
            model="gemini-3.5-flash",
            category="rpg",
        )
        assert report is not None
        assert mock_generate.call_count == 1
        query_prompt = mock_generate.call_args[1]["contents"]

        # Check that the prompt contains World of Warcraft (category RPG)
        assert "World of Warcraft" in query_prompt
        # Check that it has been padded with other trending games from the pool
        # to have at least 5 trending games
        lines = query_prompt.split("\n")
        trending_lines = [line for line in lines if "Tier=trending" in line]
        assert len(trending_lines) >= 5


def test_get_affiliate_playbook_dynamic():
    """Verify get_affiliate_playbook calls Gemini with search grounding.

    Only applies when api_key is set.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import get_affiliate_playbook

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "hook": "Test Dynamic Hook",
            "advice": "Test Dynamic Advice",
            "products": [
                {
                    "name": "Dynamic Mic",
                    "price": "$99",
                    "link": "https://example.com/mic",
                    "benefit": "Crisp audio profile.",
                }
            ],
        }
    )

    with patch(
        "ag_kaggle_5day.agents.advisor.safe_generate_content", return_value=mock_resp
    ) as mock_gen:
        playbook = get_affiliate_playbook(
            vibe="chill",
            scale="starting",
            stream_goal="growth",
            api_key="fake_key",
            previous_playbooks=[{"game": "Minecraft", "preparation": "world setup"}],
        )
        assert playbook["game"] == "Stream Gear & Setup"
        assert playbook["hook"] == "Test Dynamic Hook"
        assert "Dynamic Mic" in playbook["preparation"]
        assert (
            "Minecraft" in playbook["preparation"]
        )  # check priority injection context
        assert playbook["is_affiliate"] is True
        assert mock_gen.call_count == 1
        # Check model chain configuration was used
        assert mock_gen.call_args[1]["chain_name"] == "affiliate"
        assert mock_gen.call_args[1]["use_google_search"] is True


def test_generate_stream_playbook_random_insertion():
    """Verify generate_stream_playbook randomly inserts affiliate playbook."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import generate_stream_playbook

    dummy_aff = {
        "game": "Recommended Gear & Affiliates",
        "category": "Gear",
        "score": 100,
        "platform": "Check Amazon",
        "hook": "Test Hook",
        "advice": "Test Advice",
        "preparation": "Test Prep",
        "is_affiliate": True,
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "platform": "Both - Twitch and YouTube Gaming",
            "hook": "Test Hook",
            "advice": "Test Advice",
            "preparation": "Test Prep",
        }
    )

    with patch(
        "ag_kaggle_5day.agents.scraper.load_model_config",
        return_value={"enable_affiliate_playbook": True},
    ):
        with patch(
            "ag_kaggle_5day.agents.advisor.get_affiliate_playbook",
            return_value=dummy_aff,
        ) as mock_get_aff:
            with patch(
                "ag_kaggle_5day.agents.advisor.safe_generate_content",
                return_value=mock_resp,
            ):
                # Mock get_cached_games to return some games
                games = [
                    {
                        "title": "Minecraft",
                        "category": "Sandbox",
                        "avg_viewers": 100,
                        "score": 90,
                        "tier": "trending",
                    },
                    {
                        "title": "VALORANT",
                        "category": "FPS",
                        "avg_viewers": 200,
                        "score": 95,
                        "tier": "trending",
                    },
                ]
                with patch(
                    "ag_kaggle_5day.agents.advisor.get_cached_games", return_value=games
                ):
                    res = generate_stream_playbook(
                        "chill", "starting", 2.0, "growth", api_key="fake_key"
                    )
                    playbooks = res["playbooks"]
                    # Should have game playbooks + affiliate playbook
                    assert len(playbooks) >= 2
                    # Find the affiliate playbook position
                    aff_indices = [
                        idx for idx, p in enumerate(playbooks) if p.get("is_affiliate")
                    ]
                    assert len(aff_indices) == 1
                    assert mock_get_aff.call_count == 1


def test_custom_context_and_resolution_order_fixes():
    """Verify Firestore -> local -> static fallback resolution order.

    Also tests custom_context propagation and skipping affiliate playbook
    for single-game requests.
    """
    import json
    from unittest.mock import mock_open

    from ag_kaggle_5day.agents.advisor import (
        _store,
        generate_stream_playbook,
        get_cached_games,
    )

    # 1. Test resolution order
    # Clear in-memory store
    _store.combined_games = []

    # Mock Firestore get_app_cache_state to return dummy games list
    firestore_games = [
        {
            "title": "FirestoreGame",
            "category": "Action",
            "avg_viewers": 100,
            "score": 90,
            "tier": "trending",
        }
    ]
    local_games = [
        {
            "title": "LocalGame",
            "category": "FPS",
            "avg_viewers": 200,
            "score": 85,
            "tier": "trending",
        }
    ]

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_app_cache_state",
        return_value=firestore_games,
    ) as mock_get_db:
        # Case A: Firestore has games
        games = get_cached_games()
        assert any(g["title"] == "FirestoreGame" for g in games)
        mock_get_db.assert_called_with("combined_games")

    # Clear cache again
    _store.combined_games = []

    # Case B: Firestore fails/empty, fallback to local cache.json
    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_app_cache_state",
            side_effect=Exception("DB Error"),
        ),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(local_games))),
    ):
        games = get_cached_games()
        assert any(g["title"] == "LocalGame" for g in games)

    # 2. Test custom_context propagation and single-game affiliate skip
    dummy_aff = {
        "game": "Recommended Gear & Affiliates",
        "category": "Gear",
        "score": 100,
        "is_affiliate": True,
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "platform": "Twitch",
            "hook": "Test Hook",
            "advice": "Test Advice",
            "preparation": "Test Prep",
        }
    )

    with (
        patch(
            "ag_kaggle_5day.agents.scraper.load_model_config",
            return_value={"enable_affiliate_playbook": True},
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.get_affiliate_playbook",
            return_value=dummy_aff,
        ) as mock_get_aff,
        patch(
            "ag_kaggle_5day.agents.advisor.safe_generate_content",
            return_value=mock_resp,
        ) as mock_generate,
        patch(
            "ag_kaggle_5day.agents.advisor.get_cached_games",
            return_value=firestore_games,
        ),
    ):
        # Case A: game is specified (single-game request) -> should NOT
        # call get_affiliate_playbook
        res = generate_stream_playbook(
            vibe="chill",
            scale="starting",
            duration=3.0,
            stream_goal="growth",
            api_key="fake-key",
            game="FirestoreGame",
            custom_context="My channel name is @CoolStreamer",
        )
        assert mock_get_aff.call_count == 0
        assert not any(p.get("is_affiliate") for p in res["playbooks"])

        # Check custom_context was propagated to the prompt
        prompt_text = mock_generate.call_args[1]["contents"]
        assert (
            "Custom Gamer/Channel Context: My channel name is @CoolStreamer"
            in prompt_text
        )


def test_matches_category_unit():
    """Verify matches_category helper correctly classifies categories and titles."""
    from ag_kaggle_5day.agents.advisor import matches_category

    # Overall category matches everything
    assert matches_category("RPG", "Dark Souls", "overall") is True
    assert matches_category("", "", "overall") is True

    # Sandbox
    assert matches_category("Sandbox Game", "Minecraft", "sandbox") is True
    assert matches_category("Open World Action", "Some Game", "sandbox") is True
    assert matches_category("RPG", "Minecraft (Modded)", "sandbox") is True
    assert matches_category("FPS", "Call of Duty", "sandbox") is False

    # RPG
    assert matches_category("Action RPG", "elden ring", "rpg") is True
    assert matches_category("Role-Playing", "Final Fantasy", "rpg") is True
    assert matches_category("Souls-like", "Lies of P", "rpg") is True
    assert matches_category("Adventure", "Elden Ring", "rpg") is True
    assert matches_category("FPS", "Counter-Strike", "rpg") is False

    # FPS
    assert matches_category("Shooter", "CS:GO", "fps") is True
    assert matches_category("FPS", "Half-Life", "fps") is True
    assert matches_category("Strategy", "Valorant", "fps") is True
    assert matches_category("RPG", "Dark Souls", "fps") is False

    # Roguelike
    assert matches_category("Rogue-lite", "Slay the Spire", "roguelike") is True
    assert matches_category("Action", "Hades II", "roguelike") is True
    assert matches_category("FPS", "Doom", "roguelike") is False

    # MOBA
    assert matches_category("MOBA", "Dota 2", "moba") is True
    assert matches_category("Multiplayer online battle arena", "Smite", "moba") is True
    assert matches_category("Action", "League of Legends", "moba") is True
    assert matches_category("RPG", "Witcher", "moba") is False

    # Action-Adventure
    assert matches_category("Racing", "Need for Speed", "action-adventure") is True
    assert matches_category("Driving", "Forza Horizon", "action-adventure") is True
    assert matches_category("Action Adventure", "Uncharted", "action-adventure") is True
    assert matches_category("RPG", "GTA V", "action-adventure") is True
    assert matches_category("Sandbox", "Minecraft", "action-adventure") is False

    # IRL
    assert matches_category("IRL", "Chatting", "irl") is True
    assert matches_category("Just Chatting", "Stream", "irl") is True
    assert matches_category("Chatting", "Stream", "irl") is True
    assert matches_category("FPS", "Valorant", "irl") is False


def test_get_visible_trending_games_unit():
    """Verify get_visible_trending_games deduplicates and selects correct targets."""
    from ag_kaggle_5day.agents.advisor import get_visible_trending_games

    games = [
        {"title": "Minecraft", "category": "Sandbox", "tier": "trending"},
        {"title": "Elden Ring", "category": "RPG", "tier": "trending"},
        {"title": "Valorant", "category": "Shooter", "tier": "trending"},
        {"title": "Hades", "category": "Roguelike", "tier": "trending"},
        {"title": "League of Legends", "category": "MOBA", "tier": "trending"},
        {"title": "GTA V", "category": "Action-Adventure", "tier": "trending"},
        {"title": "Just Chatting", "category": "IRL", "tier": "trending"},
        {"title": "Other Game", "category": "Puzzle", "tier": "trending"},
    ]

    # Limit = 1: Should select the first match in each category
    visible = get_visible_trending_games(games, limit=1)

    visible_titles = [g["title"] for g in visible]
    assert "Minecraft" in visible_titles
    assert "Elden Ring" in visible_titles
    assert "Valorant" in visible_titles
    assert "Hades" in visible_titles
    assert "League of Legends" in visible_titles
    assert "GTA V" in visible_titles
    assert "Just Chatting" in visible_titles
    assert "Other Game" not in visible_titles


def test_calculate_compatibility_score_unit():
    """Verify that calculate_compatibility_score works for different profiles."""
    from ag_kaggle_5day.agents.advisor import calculate_compatibility_score

    # Minecraft is sandbox
    g_minecraft = {
        "title": "Minecraft",
        "category": "Sandbox",
        "twitch_viewers": 50000,
        "avg_length_hours": 3.0,
    }
    # Chill vibe, starting scale, duration 3.0
    score_chill = calculate_compatibility_score(
        g_minecraft, vibe="chill", scale="starting", duration=3.0
    )
    # Competitive vibe, starting scale, duration 3.0
    score_comp = calculate_compatibility_score(
        g_minecraft, vibe="competitive", scale="starting", duration=3.0
    )

    assert score_chill > score_comp  # Minecraft fits Chill vibe better

    # Test duration matching with a game that won't cap at 100
    g_minecraft_large = {
        "title": "Minecraft",
        "category": "Sandbox",
        "twitch_viewers": 500000,  # does not match starting scale
        "avg_length_hours": 3.0,
        "score": 10,
    }
    score_exact_duration = calculate_compatibility_score(
        g_minecraft_large, vibe="chill", scale="starting", duration=3.0
    )
    score_far_duration = calculate_compatibility_score(
        g_minecraft_large, vibe="chill", scale="starting", duration=8.0
    )
    assert score_exact_duration > score_far_duration


def test_get_affiliate_gear_recommendation_tool():
    """Verify get_affiliate_gear_recommendation tool retrieves playbooks

    and queries Gemini.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.advisor_agent.agent import get_affiliate_gear_recommendation

    mock_docs = []
    for i in range(2):
        doc = MagicMock()
        doc.to_dict.return_value = {
            "game": f"Game {i}",
            "preparation": f"Setup advice {i}",
            "advice": f"Advice {i}",
        }
        mock_docs.append(doc)

    mock_collection = MagicMock()
    (
        mock_collection.order_by.return_value.limit.return_value.stream.return_value
    ) = mock_docs

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    mock_response = MagicMock()
    mock_response.text = "Mocked grounded shopping links: Amazon, Best Buy"

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.safe_generate_content",
            return_value=mock_response,
        ) as mock_gen,
    ):
        result = get_affiliate_gear_recommendation("query")

        assert "Mocked grounded shopping links" in result
        assert mock_gen.call_count == 1
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["use_google_search"] is True
        assert "gear_grounding" in call_kwargs["chain_name"]


def test_sample_live_chat_mock():
    """Verify sample_live_chat connects via SSL socket and reads Twitch messages."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.scraper import sample_live_chat

    mock_sock = MagicMock()
    mock_ssl_sock = MagicMock()
    mock_ssl_sock.recv.side_effect = [
        b":user!user@user.tmi.twitch.tv PRIVMSG #test_channel :hello world\r\n",
        b"PING :tmi.twitch.tv\r\n",
        b"",
    ]

    with (
        patch("socket.socket", return_value=mock_sock),
        patch("ssl.create_default_context") as mock_ssl_context,
    ):
        mock_ssl_context.return_value.wrap_socket.return_value = mock_ssl_sock

        res = sample_live_chat("test_channel", duration=2)

        assert res["total_messages"] == 1
        assert res["messages"] == ["hello world"]
        assert res["sentiment"] == "Neutral"


@pytest.mark.anyio
async def test_medium_form_article_workflow_cached():
    """Verify medium_form_article_workflow returns immediately if cache exists."""
    from unittest.mock import patch

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import (
        medium_form_article_workflow,
    )

    mock_article = {
        "streamer_handle": "shroud",
        "title": "Spotlight shroud",
        "content": "<p>Cached contents</p>",
        "timestamp": 12345,
    }

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_cached_medium_form_article",
        return_value=mock_article,
    ):
        runner = InMemoryRunner(node=medium_form_article_workflow)
        events = await runner.run_debug(
            '{"streamer_handle": "shroud"}',
            user_id="test",
            session_id="test_sess",
            quiet=True,
        )
        assert events
        res = events[-1].output
        assert res["cached"] is True
        assert res["article"]["title"] == "Spotlight shroud"


@pytest.mark.anyio
async def test_medium_form_article_workflow_generate():
    """Verify medium_form_article_workflow runs research and generate nodes."""
    from unittest.mock import MagicMock, PropertyMock, patch

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import (
        medium_form_article_workflow,
    )

    mock_response = MagicMock()
    mock_response.text = (
        '{"title": "Spotlight generated", "content": "<p>Generated contents</p>"}'
    )

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_cached_medium_form_article",
            return_value=None,
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.safe_generate_content",
            return_value=mock_response,
        ),
        patch("ag_kaggle_5day.agents.scraper.TwitchAPIClient") as mock_twitch_class,
        patch(
            "ag_kaggle_5day.agents.gcp_storage.store_medium_form_article"
        ) as mock_store,
    ):
        type(mock_twitch_class.return_value).is_configured = PropertyMock(
            return_value=False
        )

        runner = InMemoryRunner(node=medium_form_article_workflow)
        events = await runner.run_debug(
            '{"streamer_handle": "ninja"}',
            user_id="test",
            session_id="test_sess",
            quiet=True,
        )
        assert events
        res = events[-1].output
        assert res["cached"] is False
        assert res["article"]["title"] == "Spotlight generated"
        assert "links" in res["article"]
        assert res["article"]["links"]["twitch"] == "https://twitch.tv/ninja"
        assert mock_store.call_count == 1
        mock_store.assert_called_once_with("ninja", res["article"])


@pytest.mark.anyio
async def test_daily_expose_workflow():
    """Verify daily_expose_workflow runs candidates poll, selector,
    writer, and store nodes.
    """
    from unittest.mock import MagicMock, PropertyMock, patch

    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.workflows import (
        daily_expose_workflow,
    )

    mock_poll = ["ninja", "shroud", "pokimane"]
    mock_response_select = MagicMock()
    mock_response_select.text = (
        '{"selected_streamer": "ninja", "reasoning": "ninja is popular"}'
    )

    mock_response_write = MagicMock()
    mock_response_write.text = (
        '{"title": "Expose Ninja", "content": "<p>Ninja expose contents</p>"}'
    )

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.poll_past_week_streamers_from_bq",
            return_value=mock_poll,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.sample_live_chat",
            return_value={
                "total_messages": 10,
                "msg_per_minute": 20,
                "sentiment": "Positive",
                "messages": ["gg"],
            },
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.safe_generate_content"
        ) as mock_gen,
        patch("ag_kaggle_5day.agents.scraper.TwitchAPIClient") as mock_twitch_class,
        patch(
            "ag_kaggle_5day.agents.gcp_storage.store_expose_candidates_to_bq"
        ) as mock_store_bq,
        patch(
            "ag_kaggle_5day.agents.gcp_storage.store_expose_article_vector"
        ) as mock_store_firestore,
    ):
        type(mock_twitch_class.return_value).is_configured = PropertyMock(
            return_value=True
        )
        type(mock_twitch_class.return_value).get_top_live_streams = MagicMock(
            return_value=[
                {"user_login": "ninja"},
                {"user_login": "shroud"},
                {"user_login": "pokimane"},
            ]
        )
        type(mock_twitch_class.return_value).get_channel_details = MagicMock(
            return_value=None
        )

        mock_gen.side_effect = [
            mock_response_write,
            mock_response_write,
            mock_response_write,
            mock_response_select,
            mock_response_write,
        ]

        runner = InMemoryRunner(node=daily_expose_workflow)
        events = await runner.run_debug(
            "{}", user_id="test", session_id="test_sess", quiet=True
        )
        assert events
        res = events[-1].output

        assert res["selected_streamer"] == "ninja"
        assert res["article"]["title"] == "Expose Ninja"
        assert "links" in res["article"]
        assert res["article"]["links"]["twitch"] == "https://twitch.tv/ninja"
        assert mock_store_bq.call_count == 1
        assert mock_store_firestore.call_count == 1


def test_sub_agents_registered():
    """Verify sub-agents are properly registered under the root agent."""
    from ag_kaggle_5day.advisor_agent.agent import root_agent

    sub_agent_names = [sa.name for sa in root_agent.sub_agents]
    assert "streamer_research_agent" in sub_agent_names
    assert "expose_selector_agent" in sub_agent_names
    assert "expose_writer_agent" in sub_agent_names


def test_get_historical_expose_context():
    """Verify get_historical_expose_context queries Firestore
    and merges exact/tangential context.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import get_historical_expose_context

    mock_client = MagicMock()
    mock_medium_doc = MagicMock()
    mock_medium_doc.exists = True
    mock_medium_doc.to_dict.return_value = {
        "title": "Ninja Medium Article",
        "content": "<p>Ninja plays Fortnite</p>",
        "timestamp": 123456,
    }
    mock_client.collection.return_value.document.return_value.get.return_value = (
        mock_medium_doc
    )

    mock_expose_doc = MagicMock()
    mock_expose_doc.id = "expose_id"
    mock_expose_doc.to_dict.return_value = {
        "title": "Ninja Expose Article",
        "content": "<p>Ninja plays Halo</p>",
        "timestamp": 123456,
    }

    mock_tangent_doc = MagicMock()
    mock_tangent_doc.id = "tangent_id"
    mock_tangent_doc.to_dict.return_value = {
        "streamer_handle": "shroud",
        "title": "Shroud Expose Article",
        "content": "<p>Shroud plays Valorant and collaborates with Ninja</p>",
        "timestamp": 123456,
    }

    mock_query_exact = MagicMock()
    mock_query_exact.stream.return_value = [mock_expose_doc]

    mock_query_tangent = MagicMock()
    mock_query_tangent.stream.return_value = [mock_tangent_doc]

    # Mock collection chaining
    def mock_collection_side_effect(name):
        mock_coll = MagicMock()
        if name == "spotlight_medium_articles":
            mock_coll.document.return_value.get.return_value = mock_medium_doc
        elif name == "spotlight_expose_articles":
            mock_coll.where.return_value.order_by.return_value.limit.return_value = (
                mock_query_exact
            )
            mock_coll.find_nearest.return_value = mock_query_tangent
        return mock_coll

    mock_client.collection.side_effect = mock_collection_side_effect

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_client,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_embedding",
            return_value=[0.1] * 768,
        ),
    ):
        context = get_historical_expose_context("ninja", "fake_key")
        assert "PAST MEDIUM-FORM ARTICLE FOR NINJA" in context
        assert "PAST LONG-FORM EXPOSE FOR NINJA" in context
        assert "TANGENTIALLY RELATED EXPOSE (SHROUD" in context
        assert "Fortnite" in context
        assert "Halo" in context
        assert "Valorant" in context


def test_get_expose_history_merging():
    """Verify get_expose_history fetches and merges expose and medium-form documents."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import get_expose_history

    mock_client = MagicMock()

    doc1 = MagicMock()
    doc1.to_dict.return_value = {"title": "Expose A", "timestamp": 1000}
    doc2 = MagicMock()
    doc2.to_dict.return_value = {"title": "Medium B", "timestamp": 2000}

    mock_expose_query = MagicMock()
    mock_expose_query.stream.return_value = [doc1]

    mock_medium_query = MagicMock()
    mock_medium_query.stream.return_value = [doc2]

    def mock_collection_side_effect(name):
        mock_coll = MagicMock()
        mock_coll.order_by.return_value.limit.return_value = (
            mock_expose_query
            if name == "spotlight_expose_articles"
            else mock_medium_query
        )
        return mock_coll

    mock_client.collection.side_effect = mock_collection_side_effect

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        return_value=mock_client,
    ):
        history = get_expose_history()
        assert len(history) == 2
        # Verify sorting by timestamp descending (Medium B timestamp 2000 first)
        assert history[0]["title"] == "Medium B"
        assert history[0]["type"] == "medium-form"
        assert history[1]["title"] == "Expose A"
        assert history[1]["type"] == "expose"


def test_custom_expose_logging():
    """Verify custom logging level EXPOSE is configured and works."""
    import logging

    from ag_kaggle_5day.logging_config import EXPOSE_LEVEL_NUM

    assert EXPOSE_LEVEL_NUM == 25
    assert logging.getLevelName(25) == "EXPOSE"

    logger = logging.getLogger("workflows")
    assert hasattr(logger, "expose")


def test_store_and_get_cached_sentiment():
    """Verify store_streamer_sentiment and get_cached_streamer_sentiment
    work as expected.
    """
    import time
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import (
        get_cached_streamer_sentiment,
        store_streamer_sentiment,
    )

    mock_fs = MagicMock()
    mock_bq = MagicMock()

    doc_mock = MagicMock()
    doc_mock.exists = True
    doc_mock.to_dict.return_value = {
        "streamer_handle": "teststreamer",
        "timestamp": time.time() - 100,
        "msg_per_minute": 15.5,
        "sentiment": "Positive",
        "total_messages": 5,
        "messages": ["test msg"],
    }
    mock_fs.collection.return_value.document.return_value.get.return_value = doc_mock

    # Mock BigQuery dataset/table creation
    mock_bq.project = "fake-proj"

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client",
            return_value=mock_bq,
        ),
    ):
        # 1. Test storing active sentiment
        store_streamer_sentiment(
            "teststreamer",
            {
                "msg_per_minute": 20.0,
                "sentiment": "Positive",
                "total_messages": 10,
                "messages": ["hype!"],
            },
            "scheduled",
        )

        assert mock_fs.collection.call_count == 3
        mock_fs.collection.assert_any_call("streamer_sentiment")
        mock_fs.collection.assert_any_call("streamer_sentiment_history")

        # 2. Test storing offline sentiment (skips Firestore)
        mock_fs.reset_mock()
        store_streamer_sentiment(
            "teststreamer",
            {
                "msg_per_minute": 0.0,
                "sentiment": "Offline",
                "total_messages": 0,
                "messages": [],
            },
            "on-demand",
        )
        mock_fs.collection.assert_not_called()

        # 3. Test retrieval
        cached = get_cached_streamer_sentiment("teststreamer")
        assert cached is not None
        assert cached["sentiment"] == "Positive"


def test_get_streamer_sentiment_data_tool():
    """Verify get_streamer_sentiment_data agent tool handles cache hits
    and misses.
    """
    import time
    from unittest.mock import patch

    from ag_kaggle_5day.advisor_agent.agent import get_streamer_sentiment_data

    # Cache hit scenario
    mock_cached = {
        "streamer_handle": "teststreamer",
        "timestamp": time.time() - 50,  # less than 5 min old
        "msg_per_minute": 12.0,
        "sentiment": "Positive",
        "total_messages": 4,
    }

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_cached_streamer_sentiment",
            return_value=mock_cached,
        ),
        patch("ag_kaggle_5day.agents.scraper.sample_live_chat") as mock_sample,
    ):
        result = get_streamer_sentiment_data("teststreamer")
        assert "cached" in result.lower()
        mock_sample.assert_not_called()

    # Cache miss / offline scenario
    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_cached_streamer_sentiment",
            return_value=None,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.sample_live_chat",
            return_value={
                "sentiment": "Offline",
                "total_messages": 0,
                "msg_per_minute": 0.0,
                "messages": [],
            },
        ) as mock_sample,
    ):
        result = get_streamer_sentiment_data("teststreamer")
        assert "offline" in result.lower()
        mock_sample.assert_called_once_with(
            "teststreamer", duration=30, source="on-demand"
        )


@pytest.mark.anyio
async def test_workflows_editor_and_refinement():
    """Verify that Editor Agent and Refinement nodes run successfully
    in the workflow.
    """
    from typing import Any
    from unittest.mock import MagicMock, patch

    from google.adk.runners import InMemoryRunner
    from google.adk.workflow import START, Workflow, node

    from ag_kaggle_5day.advisor_agent.workflows import (
        edit_article_node,
        refine_article_node,
    )

    @node(name="pass_through")
    def pass_through_node(node_input: Any) -> dict:
        if isinstance(node_input, dict):
            return node_input
        try:
            if hasattr(node_input, "parts"):
                return json.loads(node_input.parts[0].text)
            return json.loads(str(node_input))
        except Exception:
            return {}

    edit_workflow = Workflow(
        name="edit_workflow",
        edges=[
            (START, pass_through_node),
            (pass_through_node, edit_article_node),
        ],
    )

    refine_workflow = Workflow(
        name="refine_workflow",
        edges=[
            (START, pass_through_node),
            (pass_through_node, refine_article_node),
        ],
    )

    mock_article = {
        "streamer_handle": "teststreamer",
        "title": "Draft Title",
        "content": "<p>Content with em-dash -- and Mars rave.</p>",
        "links": {"twitch": "https://twitch.tv/teststreamer"},
    }

    mock_editor_response = MagicMock()
    mock_editor_response.text = (
        '{"approved": false, "editorial_notes": '
        '"Em dash and corny metaphor detected.", "suggestions": '
        '["Remove em dash", "Remove Mars metaphor"]}'
    )

    mock_refine_response = MagicMock()
    mock_refine_response.text = (
        '{"title": "Refined Title", "content": "<p>Clean content.</p>", '
        '"links": {"twitch": "https://twitch.tv/teststreamer"}}'
    )

    with (
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.safe_generate_content"
        ) as mock_gen,
        patch(
            "ag_kaggle_5day.agents.gcp_storage.store_medium_form_article"
        ) as mock_store,
    ):
        # 1. Test Editor Agent Node
        mock_gen.return_value = mock_editor_response
        input_data = {
            "streamer_handle": "teststreamer",
            "article": mock_article,
            "peers": ["shroud", "ninja"],
        }

        runner_edit = InMemoryRunner(node=edit_workflow)
        events_edit = await runner_edit.run_debug(
            json.dumps(input_data),
            user_id="test",
            session_id="test_sess",
            quiet=True,
        )
        res_edit = events_edit[-1].output
        assert res_edit["editorial_pass"]["approved"] is False
        assert "Em dash" in res_edit["editorial_pass"]["editorial_notes"]

        # 2. Test Writer Refinement Node
        mock_gen.reset_mock()
        mock_gen.return_value = mock_refine_response
        runner_refine = InMemoryRunner(node=refine_workflow)
        events_refine = await runner_refine.run_debug(
            json.dumps(res_edit),
            user_id="test",
            session_id="test_sess",
            quiet=True,
        )
        res_refine = events_refine[-1].output
        assert res_refine["article"]["title"] == "Refined Title"
        mock_store.assert_called_once()


def test_safe_generate_content_backup_key_fallback(monkeypatch):
    """Verify safe_generate_content falls back to GEMINI_API_KEY_BACKUP
    when the primary key returns a 429 error.
    """
    from google.genai.errors import ClientError

    import ag_kaggle_5day.agents.scraper as scraper
    from ag_kaggle_5day.agents.scraper import safe_generate_content

    scraper._api_key_rotation_index = 0

    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "backup_key_123")

    mock_client_primary = MagicMock()
    mock_client_primary.models.generate_content.side_effect = ClientError(
        429, "Quota exceeded / Resource exhausted"
    )

    mock_response = MagicMock()
    mock_response.text = "success from backup key"
    mock_client_backup = MagicMock()
    mock_client_backup.models.generate_content.return_value = mock_response

    def get_client_side_effect(api_key, timeout_ms=None):
        if api_key == "primary_key_456":
            return mock_client_primary
        elif api_key == "backup_key_123":
            return mock_client_backup
        raise ValueError("Unexpected key")

    with patch(
        "ag_kaggle_5day.agents.scraper._get_genai_client",
        side_effect=get_client_side_effect,
    ):
        res = safe_generate_content(
            api_key="primary_key_456",
            model="gemini-3.5-flash",
            contents="hello",
        )
        assert res.text == "success from backup key"


def test_get_embedding_backup_key_fallback(monkeypatch):
    """Verify get_embedding falls back to GEMINI_API_KEY_BACKUP
    when the primary key returns a 429 error.
    """
    from google.genai.errors import ClientError

    from ag_kaggle_5day.agents.gcp_storage import get_embedding

    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "backup_key_123")

    mock_client_primary = MagicMock()
    mock_client_primary.models.embed_content.side_effect = ClientError(
        429, "Quota exceeded / Resource exhausted"
    )

    mock_embed = MagicMock()
    mock_embed.values = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.embeddings = [mock_embed]
    mock_client_backup = MagicMock()
    mock_client_backup.models.embed_content.return_value = mock_response

    def get_client_side_effect(api_key, timeout_ms=None):
        if api_key == "primary_key_456":
            return mock_client_primary
        elif api_key == "backup_key_123":
            return mock_client_backup
        raise ValueError("Unexpected key")

    with patch(
        "ag_kaggle_5day.agents.scraper._get_genai_client",
        side_effect=get_client_side_effect,
    ):
        res = get_embedding("hello", api_key="primary_key_456")
        assert res == [0.1, 0.2, 0.3]


def test_get_historical_sentiment_summary():
    """Verify get_historical_sentiment_summary retrieves and sorts history
    documents in memory.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import get_historical_sentiment_summary

    mock_doc1 = MagicMock()
    mock_doc1.to_dict.return_value = {
        "streamer_handle": "ninja",
        "timestamp": 1000.0,
        "sentiment": "Positive",
        "msg_per_minute": 15.5,
        "total_messages": 30,
    }
    mock_doc2 = MagicMock()
    mock_doc2.to_dict.return_value = {
        "streamer_handle": "ninja",
        "timestamp": 2000.0,
        "sentiment": "Negative",
        "msg_per_minute": 2.0,
        "total_messages": 4,
    }

    mock_collection = MagicMock()
    mock_collection.where.return_value.limit.return_value.stream.return_value = [
        mock_doc1,
        mock_doc2,
    ]
    mock_firestore = MagicMock()
    mock_firestore.collection.return_value = mock_collection

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        return_value=mock_firestore,
    ):
        history = get_historical_sentiment_summary("ninja", limit=2)
        assert len(history) == 2
        # Verify in-memory sorting: timestamp 2000.0 must be first
        assert history[0]["timestamp"] == 2000.0
        assert history[0]["sentiment"] == "Negative"
        assert history[1]["timestamp"] == 1000.0
        assert history[1]["sentiment"] == "Positive"


def test_twitch_api_client_live_methods():
    """Verify TwitchAPIClient get_top_live_streams and get_online_streams call
    _helix_get correctly.
    """
    from unittest.mock import MagicMock

    from ag_kaggle_5day.agents.scraper import TwitchAPIClient

    twitch = TwitchAPIClient()
    twitch.client_id = "test_id"
    twitch._token = "test_token"

    mock_helix_get = MagicMock(
        return_value={
            "data": [
                {
                    "user_name": "Ninja",
                    "user_login": "ninja",
                    "title": "Playing Fortnite",
                    "viewer_count": 50000,
                    "game_id": "33214",
                    "game_name": "Fortnite",
                }
            ]
        }
    )
    twitch._helix_get = mock_helix_get

    streams = twitch.get_top_live_streams(limit=10)
    assert len(streams) == 1
    assert streams[0]["user_login"] == "ninja"
    mock_helix_get.assert_called_with("/streams", {"first": 10})

    online = twitch.get_online_streams(["ninja", "shroud"])
    assert len(online) == 1
    assert online[0]["user_login"] == "ninja"
    mock_helix_get.assert_called_with("/streams", {"user_login": ["ninja", "shroud"]})


def test_deduplicate_message_tokens():
    """Verify deduplicate_message_tokens removes consecutive duplicate words."""
    from ag_kaggle_5day.agents.scraper import deduplicate_message_tokens

    assert deduplicate_message_tokens("POG POG POG") == "POG"
    assert deduplicate_message_tokens("hello hello world world") == "hello world"
    assert deduplicate_message_tokens("GG GG GG") == "GG"
    assert deduplicate_message_tokens("") == ""


def test_deduplicate_chat_messages():
    """Verify deduplicate_chat_messages filters duplicate / near-duplicate messages."""
    from ag_kaggle_5day.agents.scraper import deduplicate_chat_messages

    input_msgs = [
        "GG!!!",
        "gg",
        "Kappa Kappa Kappa",
        "Kappa",
        "what is happening?",
        "what is happening",
    ]
    expected = ["GG!!!", "Kappa", "what is happening?"]
    assert deduplicate_chat_messages(input_msgs) == expected


def test_sample_live_chat_with_summary(monkeypatch):
    """Verify deduplication and LLM summarization inside sample_live_chat."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.scraper import sample_live_chat

    monkeypatch.setenv("GEMINI_API_KEY", "test_key")

    mock_sock = MagicMock()
    mock_ssl_sock = MagicMock()
    mock_ssl_sock.recv.side_effect = [
        b":user!user@user.tmi.twitch.tv PRIVMSG #test_channel :GG!!!\r\n"
        b":user!user@user.tmi.twitch.tv PRIVMSG #test_channel :gg\r\n"
        b":user!user@user.tmi.twitch.tv PRIVMSG #test_channel :Kappa Kappa\r\n",
        b"",
    ]

    mock_response = MagicMock()
    mock_response.text = "The chat is positive and saying GG and Kappa."

    with (
        patch("socket.socket", return_value=mock_sock),
        patch("ssl.create_default_context") as mock_ssl_context,
        patch(
            "ag_kaggle_5day.agents.scraper.safe_generate_content",
            return_value=mock_response,
        ) as mock_gen,
        patch("ag_kaggle_5day.agents.gcp_storage.store_streamer_sentiment"),
    ):
        mock_ssl_context.return_value.wrap_socket.return_value = mock_ssl_sock

        res = sample_live_chat("test_channel", duration=2)

        assert res["total_messages"] == 3
        assert res["messages"] == ["GG!!!", "Kappa"]
        assert res["summary"] == "The chat is positive and saying GG and Kappa."
        mock_gen.assert_called_once()
        prompt = mock_gen.call_args[1]["contents"]
        assert "GG!!!" in prompt
        assert "Kappa" in prompt
        assert "gg" not in prompt
        # Check default fallback metadata
        assert res["game_name"] == "Unknown"
        assert res["streamer_channel_url"] == "https://twitch.tv/test_channel"
        assert res["stream_url"] == "https://twitch.tv/test_channel"
        assert res["top_streamers_of_game"] == []


def test_sample_live_chat_enriched_metadata(monkeypatch):
    """Verify sample_live_chat queries Twitch Helix and returns enriched metadata."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.scraper import sample_live_chat

    monkeypatch.setenv("GEMINI_API_KEY", "test_key")

    mock_sock = MagicMock()
    mock_ssl_sock = MagicMock()
    mock_ssl_sock.recv.side_effect = [
        b":user!user@user.tmi.twitch.tv PRIVMSG #test_channel :hello\r\n",
        b"",
    ]

    mock_response = MagicMock()
    mock_response.text = "Chat summary."

    mock_twitch = MagicMock()
    mock_twitch.is_configured = True
    mock_twitch.get_online_streams.return_value = [
        {"game_id": "12345", "game_name": "Fortnite"}
    ]
    mock_twitch.get_top_streamers.return_value = [
        {"user_name": "Ninja", "viewer_count": 10000}
    ]
    mock_twitch.get_channel_details.return_value = {"id": "999"}
    mock_twitch.get_recent_vods.return_value = [{"id": "88888"}]

    with (
        patch("socket.socket", return_value=mock_sock),
        patch("ssl.create_default_context") as mock_ssl_context,
        patch(
            "ag_kaggle_5day.agents.scraper.safe_generate_content",
            return_value=mock_response,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.TwitchAPIClient", return_value=mock_twitch
        ),
        patch("ag_kaggle_5day.agents.gcp_storage.store_streamer_sentiment"),
    ):
        mock_ssl_context.return_value.wrap_socket.return_value = mock_ssl_sock

        res = sample_live_chat("test_channel", duration=2)

        assert res["game_name"] == "Fortnite"
        assert res["streamer_channel_url"] == "https://twitch.tv/test_channel"
        assert res["stream_url"] == "https://twitch.tv/videos/88888"
        assert len(res["top_streamers_of_game"]) == 1
        assert res["top_streamers_of_game"][0]["user_name"] == "Ninja"


def test_gcp_storage_bigquery_schema_upgrade():
    """Verify store_streamer_sentiment updates BigQuery schema if columns are
    missing.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import store_streamer_sentiment

    mock_fs = MagicMock()
    mock_bq = MagicMock()

    mock_field = MagicMock()
    mock_field.name = "timestamp"
    mock_table = MagicMock()
    mock_table.schema = [mock_field]
    mock_bq.get_table.return_value = mock_table

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client",
            return_value=mock_bq,
        ),
    ):
        store_streamer_sentiment(
            "teststreamer",
            {
                "msg_per_minute": 20.0,
                "sentiment": "Positive",
                "total_messages": 10,
                "messages": ["hype!"],
                "streamer_channel_url": "https://twitch.tv/test",
                "stream_url": "https://twitch.tv/test",
                "game_name": "Fortnite",
                "top_streamers_of_game": [],
            },
            "scheduled",
        )

        mock_bq.update_table.assert_called_once_with(mock_table, ["schema"])
        new_schema_names = [f.name for f in mock_table.schema]
        assert "streamer_channel_url" in new_schema_names
        assert "top_streamers_of_game" in new_schema_names


def test_safe_generate_content_sentiment_chain():
    """Verify safe_generate_content uses sentiment chain and falls back."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.scraper import safe_generate_content

    mock_client = MagicMock()
    called_models = []

    def side_effect(model, contents, config=None):
        called_models.append(model)
        if model == "gemma-4-31b-it":
            raise ValueError("Gemma 31B failed")
        resp = MagicMock()
        resp.text = "sentiment_ok"
        return resp

    mock_client.models.generate_content.side_effect = side_effect

    with patch(
        "ag_kaggle_5day.agents.scraper._get_genai_client", return_value=mock_client
    ):
        res = safe_generate_content(
            api_key="test-key",
            model="gemma-4-31b-it",
            contents="chat log",
            chain_name="sentiment",
        )
        assert res.text == "sentiment_ok"
        assert called_models == ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]


def test_streamer_analytics_aggregation():
    """Verify daily aggregation and profile fabric functions run as expected."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import (
        get_streamer_profile_fabric,
        query_streamer_connections,
        run_daily_analytics_aggregation,
    )

    mock_history = [
        {
            "timestamp": 1782480000,
            "game_name": "Valorant",
            "sentiment": "Positive",
            "msg_per_minute": 10.0,
            "summary": "Great stream",
        },
        {
            "timestamp": 1782490000,
            "game_name": "Valorant",
            "sentiment": "Positive",
            "msg_per_minute": 12.0,
            "summary": "Hype",
        },
        {
            "timestamp": 1782500000,
            "game_name": "Minecraft",
            "sentiment": "Neutral",
            "msg_per_minute": 5.0,
            "summary": "Chilling",
        },
    ]

    mock_bq = MagicMock()
    mock_firestore = MagicMock()

    # Mock BQ client unique handles query
    mock_row1 = MagicMock()
    mock_row1.streamer_handle = "shroud"
    mock_row1.new_moments_count = 5
    mock_bq.query.return_value = [mock_row1]

    # Mock Firestore collection for streamer_profiles
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "streamer_handle": "shroud",
        "archetype_cluster": "Highly_Competitive_Sweat",
        "peer_connections": ["ninja"],
        "time_active_cluster": "evening",
        "primary_game": "Valorant",
        "top_games": ["Valorant", "Minecraft"],
        "fabric_status": "preliminary",
        "composite_chat_summary": "Highly_Competitive_Sweat",
        "last_updated": 12345.0,
    }
    mock_profile_doc = MagicMock()
    mock_profile_doc.id = "shroud"
    mock_profile_doc.to_dict.return_value = {"timestamp": 12345.0}

    mock_moment_docs = []
    for _ in range(5):
        m_doc = MagicMock()
        m_doc.to_dict.return_value = {
            "streamer_handle": "shroud",
            "timestamp": 1782500000,
        }
        mock_moment_docs.append(m_doc)

    mock_doc_dict = MagicMock()
    mock_doc_dict.to_dict.return_value = mock_doc.to_dict.return_value

    def mock_collection_side_effect(name):
        mock_coll = MagicMock()
        if name == "streamer_profiles":
            mock_coll.select.return_value.stream.return_value = [mock_profile_doc]
            mock_coll.document.return_value.get.return_value = mock_doc
            mock_coll.where.return_value.stream.return_value = [mock_doc_dict]
        elif name == "streamer_moments":
            mock_coll.select.return_value.stream.return_value = mock_moment_docs
        else:
            mock_coll.where.return_value.stream.return_value = [mock_doc_dict]
        return mock_coll

    mock_firestore.collection.side_effect = mock_collection_side_effect

    with (
        patch(
            "ag_kaggle_5day.agents.advisor.get_unique_streamer_handles",
            return_value=["shroud"],
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary",
            return_value=mock_history,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client",
            return_value=mock_bq,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_firestore,
        ),
        patch("ag_kaggle_5day.agents.advisor.safe_generate_content") as mock_gen,
    ):
        # Mock LLM response for archetype and composite summary
        mock_resp = MagicMock()
        mock_resp.text = "Highly_Competitive_Sweat"
        mock_gen.return_value = mock_resp

        # Run aggregation
        run_daily_analytics_aggregation("test-key")

        # Verify calls to BQ and Firestore
        assert mock_gen.called

        # Verify tools
        fab = get_streamer_profile_fabric("shroud")
        assert fab["streamer_handle"] == "shroud"
        assert fab["archetype_cluster"] == "Highly_Competitive_Sweat"
        assert fab["composite_chat_summary"] == "Highly_Competitive_Sweat"

        conn = query_streamer_connections(
            {"archetype_cluster": "Highly_Competitive_Sweat"}
        )
        assert len(conn) == 1
        assert conn[0]["streamer_handle"] == "shroud"
        assert conn[0]["composite_chat_summary"] == "Highly_Competitive_Sweat"


def test_session_secret_persistence_and_cookies():
    """Verify session secret loading works and cookies are configured."""
    import os
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app, decrypt_key, encrypt_key

    # 1. Test encryption/decryption roundtrip
    test_key = "AIzaSyTestKey123"
    enc = encrypt_key(test_key)
    dec = decrypt_key(enc)
    assert dec == test_key

    # 2. Test persistent secret file exists in app directory
    secret_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src",
        "ag_kaggle_5day",
        ".session_secret",
    )
    assert os.path.exists(secret_file)

    # 3. Test connect endpoint dynamic secure cookie flag
    client = TestClient(app)
    with patch("google.genai.Client") as mock_client:
        # Mock Client validation list call
        mock_genai_instance = mock_client.return_value
        mock_genai_instance.models.list.return_value = []

        # Connect request over HTTP (scheme=http)
        response = client.post(
            "/api/auth/connect",
            json={"api_key": "AIzaSyTestKey123", "remember": False},
        )
        assert response.status_code == 200
        # Check set-cookie headers
        cookie_header = response.headers.get("set-cookie", "")
        # Since it is http, secure should NOT be present (secure=False)
        assert "secure" not in cookie_header.lower()
        assert "samesite=lax" in cookie_header.lower()

        # Connect request over HTTPS (scheme=https)
        https_response = client.post(
            "https://testserver/api/auth/connect",
            json={"api_key": "AIzaSyTestKey123", "remember": False},
        )
        assert https_response.status_code == 200
        https_cookie_header = https_response.headers.get("set-cookie", "")
        # Since it is https, secure SHOULD be present
        assert "secure" in https_cookie_header.lower()
        assert "samesite=lax" in https_cookie_header.lower()


def test_granular_sentiment_analytics_and_sanitization():
    """Verify aggregate sentiment query functions and response sanitization logic."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import (
        get_archetype_analytics_from_db,
        get_game_sentiment_metrics_from_db,
    )
    from ag_kaggle_5day.app import extract_chat_response_and_trace

    # 1. Test extract_chat_response_and_trace with mocked events
    mock_event_1 = MagicMock()
    mock_event_1.author = "streamer_metrics_advisor_agent"
    mock_event_1.content.parts = [MagicMock(text="Analyzing current market...")]
    mock_event_1.is_final_response.return_value = False

    mock_event_2 = MagicMock()
    mock_event_2.author = "streamer_metrics_advisor_agent"
    mock_event_2.content.parts = [MagicMock(text="The actual answer is here.")]
    mock_event_2.is_final_response.return_value = True

    rec, trace = extract_chat_response_and_trace([mock_event_1, mock_event_2])
    assert rec == "The actual answer is here."
    assert trace == "Thought: Analyzing current market..."

    # 2. Test Firestore fallback aggregation for get_archetype_analytics
    mock_doc = MagicMock()
    mock_doc.id = "streamer_foo"
    mock_doc.to_dict.return_value = {
        "archetype_cluster": "Cozy_Social_Interactive",
        "primary_game": "Stardew Valley",
        "last_updated": 1234567.0,
    }

    mock_ts_doc = MagicMock()
    mock_ts_doc.exists = True
    mock_ts_doc.to_dict.return_value = {
        "average_msg_per_minute": 15.5,
        "dominant_sentiment": "Positive",
        "primary_game": "Stardew Valley",
    }

    mock_fs = MagicMock()
    mock_fs.collection.return_value.stream.return_value = [mock_doc]
    mock_fs.collection.return_value.document.return_value.get.return_value = mock_ts_doc

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client", return_value=None
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
    ):
        res_arch = get_archetype_analytics_from_db()
        assert len(res_arch) > 0
        assert res_arch[0]["archetype_cluster"] == "Cozy_Social_Interactive"
        assert res_arch[0]["avg_msg_per_minute"] == 15.5
        assert res_arch[0]["positive_ratio"] == 1.0

        res_game = get_game_sentiment_metrics_from_db("Stardew Valley")
        assert len(res_game) > 0
        assert res_game[0]["game"] == "Stardew Valley"
        assert res_game[0]["avg_msg_per_minute"] == 15.5


def test_streamer_similarity_and_drift():
    """Verify similarity scoring, caching, and drift tracking functionality."""
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import (
        calculate_similarity_nvar,
        get_similar_streamers,
        get_similarity_drift,
    )

    # 1. Test calculate_similarity_nvar
    profile_a = {
        "streamer_handle": "StreamerA",
        "time_active_cluster": "evening",
        "average_msg_per_minute": 10.0,
        "top_games": ["Valorant", "Fortnite"],
    }
    profile_b = {
        "streamer_handle": "StreamerB",
        "time_active_cluster": "evening",
        "average_msg_per_minute": 12.0,
        "top_games": ["Valorant", "Minecraft"],
    }

    mock_get_viewers = MagicMock(
        side_effect=lambda handle: 1000 if handle == "StreamerA" else 2000
    )
    mock_get_sents = MagicMock(return_value=(0.6, 0.2, 0.1, 0.1))

    with (
        patch(
            "ag_kaggle_5day.agents.advisor.get_viewer_count_for_handle",
            mock_get_viewers,
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.get_sentiment_ratios_for_handle",
            mock_get_sents,
        ),
    ):
        score, metrics, why = calculate_similarity_nvar(profile_a, profile_b)
        assert 0.0 <= score <= 1.0
        assert "jaccard_overlap" in metrics
        assert metrics["jaccard_overlap"] == 1.0 / 3.0
        assert "StreamerA" in why and "StreamerB" in why

    # 2. Test get_similar_streamers with peer details in FS
    mock_fs_doc_with_peers = {
        "streamer_handle": "streamera",
        "archetype_cluster": "Cozy_Social_Interactive",
        "primary_game": "Minecraft",
        "peer_details": [
            {"handle": "streamerb", "similarity": 0.85, "why": "both active in evening"}
        ],
    }
    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_streamer_profile_fabric_from_fs",
        return_value=mock_fs_doc_with_peers,
    ):
        report = get_similar_streamers("streamera")
        assert "### Similarity Analysis for **streamera**" in report
        assert "streamerb" in report
        assert "85%" in report

    # 3. Test get_similar_streamers fallback / dynamic calculation
    mock_fs_doc_no_peers = {
        "streamer_handle": "streamera",
        "archetype_cluster": "Cozy_Social_Interactive",
        "primary_game": "Minecraft",
        "top_games": ["Minecraft"],
        "peer_details": [],
    }
    mock_peer_doc = {
        "streamer_handle": "streamerb",
        "archetype_cluster": "Cozy_Social_Interactive",
        "primary_game": "Minecraft",
        "top_games": ["Minecraft"],
    }

    mock_doc_a = MagicMock()
    mock_doc_a.to_dict.return_value = mock_fs_doc_no_peers
    mock_doc_a.id = "streamera"

    mock_doc_b = MagicMock()
    mock_doc_b.to_dict.return_value = mock_peer_doc
    mock_doc_b.id = "streamerb"

    mock_ts_doc = MagicMock()
    mock_ts_doc.exists = False

    mock_fs_client = MagicMock()
    mock_fs_client.collection.return_value.stream.return_value = [
        mock_doc_a,
        mock_doc_b,
    ]
    mock_fs_client.collection.return_value.document.return_value.get.return_value = (
        mock_ts_doc
    )

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_streamer_profile_fabric_from_fs",
            return_value=mock_fs_doc_no_peers,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs_client,
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.get_viewer_count_for_handle",
            return_value=100,
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.get_sentiment_ratios_for_handle",
            return_value=(0.3, 0.4, 0.2, 0.1),
        ),
    ):
        report_dynamic = get_similar_streamers("streamera")
        assert "Dynamic Calculation" in report_dynamic
        assert "streamerb" in report_dynamic

    # 4. Test get_similarity_drift with DB data
    mock_drift_data = [
        {
            "timestamp": 1719400000.0,
            "similarity_score": 0.8,
            "game_jaccard_overlap": 0.5,
            "why_explanation": "testing drift",
        },
        {
            "timestamp": 1719486400.0,
            "similarity_score": 0.85,
            "game_jaccard_overlap": 0.6,
            "why_explanation": "testing drift positive",
        },
    ]
    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_similarity_drift_from_db",
        return_value=mock_drift_data,
    ):
        drift_report = get_similarity_drift("streamera", "streamerb")
        assert "Similarity Drift Analysis" in drift_report
        assert "converged" in drift_report or "drifted apart" in drift_report
        assert "85%" in drift_report

    # 5. Test get_similarity_drift empty DB fallback projection
    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_similarity_drift_from_db",
        return_value=[],
    ):
        drift_fallback = get_similarity_drift("streamera", "streamerb")
        assert "Mock Drift Trend Projection" in drift_fallback


def test_strategy_planner_dossier_and_playbook_injection():
    """Verify that get_streamer_comprehensive_dossier compiles fabric and drift,
    and playbook workflows successfully inject matching streamer context.
    """
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.advisor_agent.agent import root_agent, strategy_planner
    from ag_kaggle_5day.advisor_agent.workflows import (
        generate_and_store_single_playbook_sync,
    )
    from ag_kaggle_5day.agents.advisor import get_streamer_comprehensive_dossier

    # 1. Test get_streamer_comprehensive_dossier
    mock_profile = {
        "streamer_handle": "streamera",
        "archetype_cluster": "Cozy_Social_Interactive",
        "primary_game": "Minecraft",
        "time_active_cluster": "evening",
        "fabric_status": "established",
        "top_games": ["Minecraft", "Stardew Valley"],
        "peer_details": [
            {"handle": "streamerb", "similarity": 0.85, "why": "both cozy"}
        ],
    }
    mock_drift = [
        {
            "timestamp": 1719400000.0,
            "similarity_score": 0.8,
            "game_jaccard_overlap": 0.5,
            "why_explanation": "stable",
        }
    ]

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_streamer_profile_fabric_from_fs",
            return_value=mock_profile,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_similarity_drift_from_db",
            return_value=mock_drift,
        ),
    ):
        dossier = get_streamer_comprehensive_dossier("streamera")
        assert "Comprehensive Dossier for **streamera**" in dossier
        assert "Archetype Cluster" in dossier
        assert "streamerb" in dossier
        assert "Drift Analysis: streamera vs streamerb" in dossier

    # 2. Test Playbook Reference Streamer Injection
    mock_fs_client = MagicMock()
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "streamer_handle": "streamer_valorant",
        "archetype_cluster": "Highly_Competitive_Sweat",
        "time_active_cluster": "evening",
        "fabric_status": "established",
        "top_games": ["Valorant"],
    }
    mock_fs_client.collection.return_value.stream.return_value = [mock_doc]

    mock_ts_doc = MagicMock()
    mock_ts_doc.exists = True
    mock_ts_doc.to_dict.return_value = {"average_msg_per_minute": 22.5}
    mock_fs_client.collection.return_value.document.return_value.get.return_value = (
        mock_ts_doc
    )

    mock_resp = MagicMock()
    mock_resp.text = (
        '{"platform": "Twitch", "hook": "test hook", '
        '"advice": "test advice", "preparation": "test prep"}'
    )

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs_client,
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.search_similar_playbooks",
            return_value=[],
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.search_similar_news",
            return_value=[],
        ),
        patch(
            "ag_kaggle_5day.advisor_agent.workflows.safe_generate_content",
            return_value=mock_resp,
        ) as mock_gen,
    ):
        res = generate_and_store_single_playbook_sync(
            vibe="competitive",
            scale="starting",
            duration=3.0,
            stream_goal="growth",
            g={
                "title": "Valorant",
                "category": "FPS",
                "twitch_viewers": 1000,
                "youtube_viewers": 500,
            },
            api_key="fake-key",
            custom_context="my custom context",
        )
        assert res["game"] == "Valorant"

        # Verify the matching streamer context was injected into the prompt
        called_prompt = mock_gen.call_args[1]["contents"]
        assert "Successful Streamers Playing This Game" in called_prompt
        assert "streamer_valorant" in called_prompt
        assert "22.5 messages/minute" in called_prompt

    # 3. Test Agent Tool Registrations and Sub-agent Binding
    assert strategy_planner.name == "strategy_planner_agent"
    assert "strategy_planner_agent" in [sa.name for sa in root_agent.sub_agents]
    assert "strategy_planner_agent" in root_agent.instruction


def test_ecosystem_starmap_tools():
    from ag_kaggle_5day.agents.advisor import (
        get_bellwether_rankings,
        get_ecosystem_overview,
        get_tribe_details,
    )

    mock_fs_client = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "timestamp": 1719400000.0,
        "streamers": ["streamera", "streamerb"],
        "vibe_tribes": {
            "0": {
                "label": "Midnight Variety Syndicate",
                "color": "#22d3ee",
                "members": ["streamera"],
                "dominant_archetype": "Cozy_Social_Interactive",
                "member_count": 1,
            }
        },
        "bellwether_scores": {"streamera": 0.87, "streamerb": 0.42},
        "convergence_velocity": [
            {
                "streamer_a": "streamera",
                "streamer_b": "streamerb",
                "velocity": 0.12,
                "direction": "converging",
            }
        ],
    }
    mock_fs_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc
    )

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
        return_value=mock_fs_client,
    ):
        overview = get_ecosystem_overview()
        assert "Streamer Ecosystem Macro Overview" in overview
        assert "Midnight Variety Syndicate" in overview
        assert "streamera" in overview
        assert "Centrality: 0.87" in overview

        details = get_tribe_details("0")
        assert "Vibe Tribe Deep-Dive: **Midnight Variety Syndicate**" in details
        assert "streamera" in details

        rankings = get_bellwether_rankings(5)
        assert "Top 5 Bellwether Streamers" in rankings
        assert "streamera" in rankings


def test_youtube_casing_preservation_moments():
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.gcp_storage import (
        get_historical_sentiment_summary,
        store_streamer_sentiment_moment,
    )

    mock_fs = MagicMock()
    # Mock resolve_streamer_link
    mock_link_doc = MagicMock()
    mock_link_doc.exists = True
    mock_link_doc.to_dict.return_value = {
        "youtube_channel_id": "UCI1vyXBgX3bruwvChLMNxjQ",
        "twitch_handle": "topstep",
    }

    mock_sentiment_doc = MagicMock()
    mock_sentiment_doc.to_dict.return_value = {
        "streamer_handle": "UCI1vyXBgX3bruwvChLMNxjQ",
        "sentiment": "Positive",
        "timestamp": 12345.0,
    }
    mock_sentiment_stream = MagicMock()
    mock_sentiment_stream.__iter__.return_value = [mock_sentiment_doc]

    mocks_cache = {}

    def collection_mock(name):
        if name not in mocks_cache:
            coll = MagicMock()
            if name == "streamer_account_links":
                coll.document.return_value.get.return_value = mock_link_doc
            elif name == "streamer_sentiment_history":
                coll.where.return_value.limit.return_value.stream.return_value = (
                    mock_sentiment_stream
                )
            mocks_cache[name] = coll
        return mocks_cache[name]

    mock_fs.collection.side_effect = collection_mock

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_bigquery_client", return_value=None
        ),
    ):
        # 1. Test store_streamer_sentiment_moment with lowercase youtube id
        store_streamer_sentiment_moment(
            streamer_handle="uci1vyxbgx3bruwvchlmnxjq",
            game_name="Retro Games",
            trigger_type="mpm_spike",
            trigger_value=12.0,
            mpm=15.0,
            sentiment="Positive",
            summary="Highlight",
            messages=["Cool highlight"],
        )
        # Should call add() on streamer_moments collection
        mock_fs.collection.assert_any_call("streamer_moments")
        added_data = mock_fs.collection("streamer_moments").add.call_args[0][0]
        # streamer_handle should be resolved/proper case!
        assert added_data["streamer_handle"] == "UCI1vyXBgX3bruwvChLMNxjQ"

        # 2. Test get_historical_sentiment_summary with lowercase youtube id
        history = get_historical_sentiment_summary("uci1vyxbgx3bruwvchlmnxjq")
        assert len(history) == 1
        assert history[0]["sentiment"] == "Positive"


def test_adk_model_resolution_fallback():
    """Verify that get_fallback_models resolves ADK wrapped model objects
    to clean strings and orders the fallbacks prioritizing
    gemini-3.1-flash-lite over gemini-3.5-flash.
    """
    from google.adk.models import Gemini

    from ag_kaggle_5day.workflow_init import get_fallback_models

    # Create an ADK wrapped model object
    adk_model = Gemini(model="gemma-4-26b-a4b-it")

    # Get fallbacks
    fallbacks = get_fallback_models(adk_model)

    # Asserts
    # First model in fallback list must be the requested model (as a clean string)
    # or the alternating partner (since get_fallback_models alternates first two models,
    # let's assert both are in the first two positions).
    assert "gemma-4-26b-a4b-it" in fallbacks[:2]
    assert "gemma-4-31b-it" in fallbacks[:2]

    # gemini-3.1-flash-lite should be prioritized before gemini-3.5-flash
    # in default_chain
    idx_lite = fallbacks.index("gemini-3.1-flash-lite")
    idx_flash = fallbacks.index("gemini-3.5-flash")
    assert idx_lite < idx_flash
