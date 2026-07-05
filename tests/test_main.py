import os

from fastapi.testclient import TestClient

from ag_kaggle_5day.app import app

client = TestClient(app)


def test_get_dashboard():
    response = client.get("/")
    assert response.status_code == 200
    assert "STREAMER ADVISOR" in response.text


def test_api_get_games():
    """
    /api/games reads from the HourlyCacheStore. In a test context there's no
    live startup event, so we seed the store directly with STAPLE_GAMES.
    """
    import time

    from ag_kaggle_5day.agents.advisor import get_hourly_cache
    from ag_kaggle_5day.agents.scraper import STAPLE_GAMES, _build_canonical_game

    # Seed the in-memory store so the endpoint returns data
    store = get_hourly_cache()
    seeded = []
    for g in STAPLE_GAMES:
        avg = g["avg_viewers"]
        twitch_v = int(avg * 0.7)
        youtube_v = avg - twitch_v
        seeded.append(
            _build_canonical_game(
                title=g["title"],
                category=g["category"],
                twitch_viewers=twitch_v,
                youtube_viewers=youtube_v,
                avg_length_hours=g["avg_length_hours"],
                score=g["score"],
                source="Test Seed",
                source_url="https://twitchtracker.com",
                tier="staple",
            )
        )
    store.combined_games = seeded
    store.staples = seeded
    store.refreshed_at = time.time()

    response = client.get("/api/games")
    assert response.status_code == 200
    games = response.json()
    assert len(games) > 0
    assert "title" in games[0]
    # Verify tier field is present (new field)
    assert "tier" in games[0]


def test_api_cache_status():
    """Verify the new /api/cache/status endpoint."""
    response = client.get("/api/cache/status")
    assert response.status_code == 200
    data = response.json()
    assert "age_seconds" in data
    assert "report_cached" in data
    assert "top5_count" in data


def test_api_recommend_fallback():
    # Force GEMINI_API_KEY to be empty for fallback check
    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    try:
        response = client.post(
            "/api/recommend", json={"query": "What game should I stream?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "recommendation" in data
        assert "GEMINI_API_KEY is not set" in data["recommendation"]
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_api_collect_metrics():
    # Force GEMINI_API_KEY to be empty so scraper uses fast simulation fallback
    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    try:
        response = client.post(
            "/api/collect", json={"custom_games": ["Tetris", "Pong"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "logs" in data
        assert "games" in data
        assert len(data["logs"]) > 0
        assert len(data["games"]) > 0
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_api_news_fallback():
    # Force GEMINI_API_KEY to be empty for fallback check
    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    try:
        response = client.get("/api/news?game=Minecraft")
        assert response.status_code == 200
        data = response.json()
        assert "news" in data
        assert len(data["news"]) > 0
        assert "title" in data["news"][0]
        assert "summary" in data["news"][0]
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_api_compare_fallback():
    # POST /api/compare should return deprecation message
    response = client.post("/api/compare", json={"custom_games": ["Minecraft"]})
    assert response.status_code == 200
    data = response.json()
    assert "report" in data
    assert "Comparative reports are no longer generated" in data["report"]


def test_api_compare_headers():
    # Verify compare endpoint accepts both search and analysis model headers
    headers = {
        "x-gemini-api-key": "AIzaSyFakeKeyForTest",
        "x-gemini-search-model": "gemini-3.5-flash",
        "x-gemini-analysis-model": "gemini-3-flash",
    }
    # Since we are using a fake key, the actual Gemini client instantiation
    # or call would fail,
    # but we verify that it is processed and doesn't crash on the schema layer.
    response = client.post("/api/compare", json={"custom_games": []}, headers=headers)
    assert response.status_code == 200


def test_api_admin_endpoints_removed():
    """Verify that /api/admin/health and /api/admin/logs are removed and return 404."""
    for path in ("/api/admin/health", "/api/admin/logs"):
        response = client.get(path)
        assert response.status_code == 404


def test_api_config():
    # Verify the config endpoint correctly identifies whether each API key
    # is configured.
    orig_gemini = os.environ.get("GEMINI_API_KEY")
    orig_twitch_id = os.environ.get("TWITCH_CLIENT_ID")
    orig_twitch_secret = os.environ.get("TWITCH_CLIENT_SECRET")
    orig_youtube = os.environ.get("YOUTUBE_API_KEY")
    try:
        # 1. Gemini key set, platform keys absent
        os.environ["GEMINI_API_KEY"] = "AIzaSyFakeKeyForTest"
        for k in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "YOUTUBE_API_KEY"):
            os.environ.pop(k, None)
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["server_key_configured"] is True
        assert data["twitch_configured"] is False
        assert data["youtube_configured"] is False

        # 2. No keys set
        os.environ.pop("GEMINI_API_KEY", None)
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["server_key_configured"] is False
        assert data["twitch_configured"] is False
        assert data["youtube_configured"] is False

        # 3. All keys set
        os.environ["GEMINI_API_KEY"] = "fake_gemini"
        os.environ["TWITCH_CLIENT_ID"] = "fake_id"
        os.environ["TWITCH_CLIENT_SECRET"] = "fake_secret"
        os.environ["YOUTUBE_API_KEY"] = "fake_yt"
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["server_key_configured"] is True
        assert data["twitch_configured"] is True
        assert data["youtube_configured"] is True
    finally:
        # Restore original environment
        for k, v in [
            ("GEMINI_API_KEY", orig_gemini),
            ("TWITCH_CLIENT_ID", orig_twitch_id),
            ("TWITCH_CLIENT_SECRET", orig_twitch_secret),
            ("YOUTUBE_API_KEY", orig_youtube),
        ]:
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_api_playbook():
    """Verify that the playbook API returns structured playbooks."""
    orig_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    try:
        response = client.post(
            "/api/playbook",
            json={
                "vibe": "chill",
                "scale": "starting",
                "duration": 3.5,
                "stream_goal": "growth",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["vibe"] == "chill"
        assert data["scale"] == "starting"
        assert data["duration"] == 3.5
        assert "playbooks" in data
        # Even offline fallback returns baseline mock playbooks
        assert len(data["playbooks"]) > 0
        assert "game" in data["playbooks"][0]
        assert "platform" in data["playbooks"][0]
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key


def test_api_cron_refresh():
    """Verify that the /api/cron/refresh endpoint is removed and returns 404."""
    response = client.post("/api/cron/refresh")
    assert response.status_code == 404


def test_cron_refresh_cli():
    """Verify that the cron CLI task successfully runs updates."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from ag_kaggle_5day.cron import run_cron_refresh

    with (
        patch("ag_kaggle_5day.cron.start_raid_sentinel", new=AsyncMock()),
        patch("ag_kaggle_5day.cron.stop_raid_sentinel", new=AsyncMock()),
        patch(
            "ag_kaggle_5day.agents.advisor.trigger_daily_expose_job", new=AsyncMock()
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.calculate_hourly_correlation",
            new=MagicMock(),
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.run_daily_analytics_aggregation",
            new=MagicMock(),
        ),
        patch("ag_kaggle_5day.cron.refresh_hourly_cache") as mock_refresh,
        patch(
            "ag_kaggle_5day.cron.query_remote_agent", new_callable=AsyncMock
        ) as mock_query,
        patch("ag_kaggle_5day.cron.get_effective_key", return_value="AIzaSyTestKey"),
    ):
        asyncio.run(run_cron_refresh())
        mock_refresh.assert_called_once()
        mock_query.assert_called_once()


def test_docs_unauthorized():
    """Verify that requests to documentation routes return 401 without auth."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Basic"


def test_docs_authorized():
    """Verify that requests to documentation routes succeed with basic auth."""
    import base64

    auth_header = "Basic " + base64.b64encode(b"admin:admin").decode("utf-8")

    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path, headers={"Authorization": auth_header})
        assert response.status_code == 200


def test_rate_limiting():
    """Verify that exceeding rate limits returns 429 Too Many Requests."""
    from unittest.mock import patch

    from ag_kaggle_5day.app import recommend_limiter

    recommend_limiter.requests.clear()

    # We allow 5 requests per 30 seconds for recommend
    headers = {"x-gemini-api-key": "AIzaSyFakeKeyForTest"}
    with patch(
        "ag_kaggle_5day.app.query_remote_agent",
        return_value=("Mocked recommendation response", "Mocked reasoning trace"),
    ):
        for i in range(5):
            response = client.post(
                "/api/recommend",
                json={"query": "Test query"},
                headers=headers,
            )
            assert response.status_code == 200

        # 6th request should fail with 429
        response = client.post(
            "/api/recommend",
            json={"query": "Test query"},
            headers=headers,
        )
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]


def test_compare_cache_on_post():
    """Verify that POST /api/compare returns the deprecation placeholder."""
    response = client.post(
        "/api/compare",
        json={
            "custom_games": ["Minecraft"],
            "category": "overall",
            "force_refresh": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "Comparative reports are no longer generated" in data["report"]
    assert data.get("cached") is True


def test_admin_seed_endpoint_removed():
    """Verify that POST /api/admin/seed is removed and returns 404."""
    response = client.post("/api/admin/seed")
    assert response.status_code == 404


def test_cron_seed_cli(monkeypatch):
    """Verify that the cron CLI seed task runs seeding successfully."""
    import asyncio

    seeded_called = False

    def mock_seed(force=False):
        nonlocal seeded_called
        seeded_called = True

    monkeypatch.setattr(
        "ag_kaggle_5day.agents.advisor.seed_firestore_cache_if_empty", mock_seed
    )

    from ag_kaggle_5day.cron import run_db_seed

    asyncio.run(run_db_seed())
    assert seeded_called is True


def test_api_news_random():
    """Verify that /api/news/random returns a list of shuffled articles."""
    response = client.get("/api/news/random?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert "articles" in data
    assert isinstance(data["articles"], list)
    assert len(data["articles"]) <= 3
    if len(data["articles"]) > 0:
        assert "title" in data["articles"][0]
        assert "summary" in data["articles"][0]
        assert "url" in data["articles"][0]
        assert "game" in data["articles"][0]


def test_get_deployment_nonce():
    """Verify get_deployment_nonce retrieves nonce from env or yaml."""
    from unittest.mock import mock_open, patch

    from ag_kaggle_5day.app import get_deployment_nonce

    # Test 1: From environment variable
    with patch.dict("os.environ", {"DEPLOY_NONCE": "env-nonce-123"}):
        assert get_deployment_nonce() == "env-nonce-123"

    # Test 2: From mock service.yaml file
    fake_yaml = """
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: streamer-advisor
spec:
  template:
    metadata:
      labels:
        client.knative.dev/nonce: yaml-nonce-456
    """
    with patch.dict("os.environ", {}):
        if "DEPLOY_NONCE" in os.environ:
            del os.environ["DEPLOY_NONCE"]
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=fake_yaml)):
                assert get_deployment_nonce() == "yaml-nonce-456"

    # Test 3: Fallback when not found
    with patch.dict("os.environ", {}):
        if "DEPLOY_NONCE" in os.environ:
            del os.environ["DEPLOY_NONCE"]
        with patch("os.path.exists", return_value=False):
            assert get_deployment_nonce() == "local-dev"


def test_api_expose_endpoints_http_exception_handling(monkeypatch):
    """Verify latest expose endpoint returns 404 rather than 500
    when no daily exposes exist.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    client = TestClient(app)

    # Mock get_latest_expose_article to return None, causing HTTPException(404)
    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_latest_expose_article",
        return_value=None,
    ):
        response = client.get("/api/articles/expose/latest")
        assert response.status_code == 404
        assert "No daily exposes found." in response.json()["detail"]


def test_byok_auth_endpoints():
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    client = TestClient(app)

    # 1. Connect with empty key -> 400
    res = client.post("/api/auth/connect", json={"api_key": "", "remember": False})
    assert res.status_code == 400

    # 2. Connect with valid key -> 200, sets cookie
    mock_genai_client = MagicMock()
    with patch("google.genai.Client", return_value=mock_genai_client):
        res = client.post(
            "/api/auth/connect",
            json={"api_key": "AIzaSyTestApiKey", "remember": True},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "connected"}
        assert "gemini_session_key" in res.cookies
        encrypted_cookie = res.cookies["gemini_session_key"]

    # 3. Connect with invalid key (Client raises exception) -> 401
    with patch("google.genai.Client", side_effect=Exception("Invalid key")):
        res = client.post(
            "/api/auth/connect",
            json={"api_key": "bad_key", "remember": False},
        )
        assert res.status_code == 401

    # 4. Request with valid encrypted cookie -> succeeds (e.g., /api/compare)
    client.cookies.set("gemini_session_key", encrypted_cookie)
    res = client.post("/api/compare", json={"custom_games": []})
    assert res.status_code == 200

    # 5. Disconnect -> clears cookie
    res = client.post("/api/auth/disconnect")
    assert res.status_code == 200
    assert res.json() == {"status": "disconnected"}
    assert res.cookies.get("gemini_session_key") is None


def test_streamer_profile_extended():
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    client = TestClient(app)

    # Mock Firestore and storage functions
    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_prof = patch(
        "ag_kaggle_5day.agents.gcp_storage.get_streamer_profile_fabric_from_fs"
    )
    p_sent = patch("ag_kaggle_5day.agents.gcp_storage.get_cached_streamer_sentiment")
    p_hist = patch("ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary")
    p_link = patch("ag_kaggle_5day.agents.gcp_storage.resolve_streamer_link")

    with (
        p_fs as mock_get_fs,
        p_prof as mock_get_prof,
        p_sent as mock_get_sent,
        p_hist as mock_get_hist,
        p_link as mock_resolve_link,
    ):
        mock_fs = MagicMock()
        mock_get_fs.return_value = mock_fs

        mock_resolve_link.return_value = {
            "twitch_handle": "theburntpeanut",
            "youtube_channel_id": "uc-burntpeanut",
            "display_name": "TheBurntPeanut",
        }

        mock_get_prof.return_value = {
            "streamer_handle": "theburntpeanut",
            "archetype_cluster": "Competitive_Variety_Core",
            "fabric_status": "established",
        }

        mock_get_sent.return_value = {
            "streamer_handle": "theburntpeanut",
            "viewer_count": 1500,
            "source": "both",
            "game_name": "Minecraft",
        }

        mock_get_hist.return_value = []

        # Mock Firestore spotlight checks (pretend spotlight exists but not expose)
        mock_spot_doc = MagicMock()
        mock_spot_doc.exists = True

        mock_doc_ref = mock_fs.collection.return_value.document.return_value
        mock_doc_ref.get.return_value = mock_spot_doc

        # Mock expose collection stream to be empty
        mock_where = mock_fs.collection.return_value.where.return_value
        mock_where.limit.return_value.stream.return_value = []

        response = client.get("/api/streamers/theburntpeanut/profile")
        assert response.status_code == 200
        data = response.json()
        assert data["has_spotlight"] is True
        assert data["has_expose"] is False
        assert data["linked_twitch"] == "theburntpeanut"
        assert data["linked_youtube"] == "uc-burntpeanut"
        assert data["display_name"] == "TheBurntPeanut"


def test_standalone_seo_routes():
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    client = TestClient(app)

    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_link = patch("ag_kaggle_5day.agents.gcp_storage.resolve_streamer_link")

    with p_fs as mock_get_fs, p_link as mock_resolve_link:
        mock_fs = MagicMock()
        mock_get_fs.return_value = mock_fs
        mock_resolve_link.return_value = None

        # 1. Test spotlight route when cache is missing
        mock_doc = MagicMock()
        mock_doc.exists = False

        mock_doc_ref = mock_fs.collection.return_value.document.return_value
        mock_doc_ref.get.return_value = mock_doc

        res = client.get("/spotlight/nonexistentstreamer")
        assert res.status_code == 200
        assert "Dossier Missing" in res.text
        assert "GENERATE DOSSIER" in res.text

        # 2. Test spotlight route when cache exists
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "title": "Spotlight on a Variety Gamer",
            "content": (
                "<p>A detailed long-form analytical report about gameplay style.</p>"
            ),
            "timestamp": 1780000000.0,
            "associated_links": {
                "twitch": "https://twitch.tv/variety",
                "youtube": "https://youtube.com",
            },
        }

        res = client.get("/spotlight/variety")
        assert res.status_code == 200
        assert "Spotlight on a Variety Gamer" in res.text
        assert "badge-twitch" in res.text

        # 3. Test expose route when cache exists
        mock_expose_doc = MagicMock()
        mock_expose_doc.to_dict.return_value = {
            "title": "Expose on Variety",
            "content": "<p>Tense and chaotic chat logs.</p>",
            "timestamp": 1780000000.0,
        }

        mock_coll = mock_fs.collection.return_value
        mock_stream = mock_coll.where.return_value.order_by.return_value
        mock_stream.limit.return_value.stream.return_value = [mock_expose_doc]

        res = client.get("/expose/variety")
        assert res.status_code == 200
        assert "Expose on Variety" in res.text
        assert "DAILY EXPOSE DOSSIER" in res.text


def test_streamer_profile_endpoint_ondemand_checking():
    import time
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    client = TestClient(app)

    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_prof = patch(
        "ag_kaggle_5day.agents.gcp_storage.get_streamer_profile_fabric_from_fs"
    )
    p_sent = patch("ag_kaggle_5day.agents.gcp_storage.get_cached_streamer_sentiment")
    p_hist = patch("ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary")
    p_link = patch("ag_kaggle_5day.agents.gcp_storage.resolve_streamer_link")
    p_check = patch("ag_kaggle_5day.agents.scraper.check_streamer_live_status_ondemand")

    with (
        p_fs as mock_get_fs,
        p_prof as mock_get_prof,
        p_sent as mock_get_sent,
        p_hist as _,
        p_link as mock_resolve_link,
        p_check as mock_live_check,
    ):
        mock_fs = MagicMock()
        mock_get_fs.return_value = mock_fs

        mock_resolve_link.return_value = {
            "twitch_handle": "teststreamer",
            "youtube_channel_id": "uc-teststreamer",
            "display_name": "TestStreamer",
        }

        mock_get_prof.return_value = {
            "streamer_handle": "teststreamer",
            "archetype_cluster": "Cozy_Social_Interactive",
        }

        # Case 1: Cache is fresh (last_live_check_timestamp is recent) -> no
        # check_streamer_live_status_ondemand is called
        mock_get_sent.return_value = {
            "streamer_handle": "teststreamer",
            "viewer_count": 500,
            "source": "twitch",
            "game_name": "Dota 2",
            "last_live_check_timestamp": time.time() - 30.0,
        }

        # Mock Firestore spotlight/expose checks
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_fs.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )
        (
            mock_fs.collection.return_value.where.return_value.limit.return_value.stream.return_value
        ) = []

        response = client.get("/api/streamers/teststreamer/profile")
        assert response.status_code == 200
        mock_live_check.assert_not_called()

        # Case 2: Cache is stale (last_live_check_timestamp is old/missing) ->
        # check_streamer_live_status_ondemand is called
        mock_get_sent.return_value = {
            "streamer_handle": "teststreamer",
            "viewer_count": 500,
            "source": "twitch",
            "game_name": "Dota 2",
            "last_live_check_timestamp": time.time() - 300.0,  # 5 mins ago
        }

        mock_live_check.return_value = {
            "is_live": True,
            "viewer_count": 1200,
            "game_name": "Dota 2",
            "title": "Playing ranked match",
            "source": "twitch",
            "twitch_viewers": 1200,
            "youtube_viewers": 0,
        }

        # Mock collection set
        mock_set = mock_fs.collection.return_value.document.return_value.set

        response = client.get("/api/streamers/teststreamer/profile")
        assert response.status_code == 200
        mock_live_check.assert_called_once()
        assert mock_set.call_count >= 1


def test_recent_videos_and_top_games():
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import _process_single_streamer

    # Mock TwitchAPIClient
    mock_twitch = MagicMock()
    mock_twitch.is_configured = True
    mock_twitch.get_channel_details.return_value = {
        "description": "Twitch Test Streamer Channel",
        "profile_image_url": "https://twitch.tv/avatar.png",
    }
    mock_twitch.get_most_recent_video.return_value = {
        "title": "Twitch VOD Hype",
        "url": "https://www.twitch.tv/videos/999",
    }

    # Mock YouTubeAPIClient
    mock_yt = MagicMock()
    mock_yt.get_channel_stats.return_value = {
        "youtube_subscribers": 1000,
        "youtube_views": 50000,
        "youtube_videos": 120,
        "youtube_avatar": "https://youtube.com/avatar.png",
        "youtube_description": "YT Channel Description",
        "youtube_title": "YT Title",
    }
    mock_yt.get_most_recent_video.return_value = {
        "title": "YouTube Video Hype",
        "url": "https://www.youtube.com/watch?v=111",
    }

    p_twitch = patch(
        "ag_kaggle_5day.agents.scraper.TwitchAPIClient", return_value=mock_twitch
    )
    p_yt = patch("ag_kaggle_5day.agents.scraper.YouTubeAPIClient", return_value=mock_yt)
    p_hist = patch(
        "ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary",
        return_value=[
            {
                "timestamp": 1782930000.0,
                "game_name": "VALORANT",
                "viewer_count": 500,
                "msg_per_minute": 10.0,
                "chat_volatility": 0.5,
                "sentiment": "Neutral",
                "summary": "Cozy chat session",
            }
        ],
    )
    p_timeseries = patch(
        "ag_kaggle_5day.agents.gcp_storage.store_daily_streamer_analytics_timeseries"
    )
    p_link = patch(
        "ag_kaggle_5day.agents.gcp_storage.resolve_streamer_link",
        return_value={
            "twitch_handle": "teststreamer",
            "youtube_channel_id": "UC_youtube_test_id",
            "display_name": "teststreamer",
        },
    )

    with p_twitch, p_yt, p_hist, p_timeseries, p_link:
        profile = _process_single_streamer("teststreamer", "dummy-key")
        assert profile is not None
        assert profile["recent_youtube_video_title"] == "YouTube Video Hype"
        assert (
            profile["recent_youtube_video_url"] == "https://www.youtube.com/watch?v=111"
        )
        assert profile["recent_twitch_video_title"] == "Twitch VOD Hype"
        assert profile["recent_twitch_video_url"] == "https://www.twitch.tv/videos/999"


def test_ensure_and_enrich_profile():
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.app import ensure_and_enrich_profile

    mock_fs = MagicMock()
    mock_doc = MagicMock()
    mock_fs.collection.return_value.document.return_value = mock_doc

    # Case 1: Profile exists and is_bootstrap = False (should preserve profile
    # untouched)
    mock_doc.get.return_value.exists = True
    mock_doc.get.return_value.to_dict.return_value = {
        "streamer_handle": "existing_user",
        "tier": "bellwether",
        "bootstrap_context": {
            "bio_description": "Keep this bio",
            "vibe_tags": ["Elite", "Sweaty"],
        },
    }

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client", return_value=mock_fs
    ):
        res = ensure_and_enrich_profile("existing_user", is_bootstrap=False)
        assert res["tier"] == "bellwether"
        assert res["bootstrap_context"]["bio_description"] == "Keep this bio"
        assert not mock_doc.set.called

    # Case 2: Profile does not exist (fallback bootstrap with enrichment)
    mock_doc.set.reset_mock()
    mock_doc.get.return_value.exists = False

    mock_twitch = MagicMock()
    mock_twitch.is_configured = True
    mock_twitch.get_channel_details.return_value = {
        "description": "Scraped Twitch Bio",
        "display_name": "NewUserDisplayName",
        "profile_image_url": "https://twitch.tv/new_user.png",
    }
    mock_twitch.get_online_streams.return_value = [{"game_name": "Forza Horizon 5"}]
    mock_twitch.get_stream_tags.return_value = ["Racing", "Chill"]

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
        patch(
            "ag_kaggle_5day.agents.scraper.TwitchAPIClient", return_value=mock_twitch
        ),
    ):
        res = ensure_and_enrich_profile("new_user", is_bootstrap=False)
        assert res["tier"] == "bootstrapped"
        assert res["bootstrap_context"]["bio_description"] == "Scraped Twitch Bio"
        assert res["bootstrap_context"]["vibe_tags"] == ["Racing", "Chill"]
        assert res["primary_game"] == "Forza Horizon 5"
        assert mock_doc.set.called


def test_api_matchmaker_register_endpoint():
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from ag_kaggle_5day.app import app

    test_client = TestClient(app)

    mock_fs = MagicMock()
    mock_doc = MagicMock()
    mock_fs.collection.return_value.document.return_value = mock_doc
    mock_doc.get.return_value.exists = True
    mock_doc.get.return_value.to_dict.return_value = {
        "streamer_handle": "test_user",
        "tier": "bellwether",
        "bootstrap_context": {
            "bio_description": "Existing Bio",
            "vibe_tags": ["Gaming"],
        },
    }

    with patch(
        "ag_kaggle_5day.agents.gcp_storage.get_firestore_client", return_value=mock_fs
    ):
        response = test_client.post(
            "/api/matchmaker/register",
            json={
                "streamer_handle": "test_user",
                "bio_description": "New Bootstrap Bio",
                "vibe_tags": ["NewTag"],
                "is_bootstrap": False,
            },
        )
        assert response.status_code == 200
        assert "processed successfully" in response.json()["message"]


def test_matchmaker_pipeline_raid_playbook():
    from unittest.mock import MagicMock, patch

    from ag_kaggle_5day.agents.advisor import run_matchmaker_pipeline

    mock_fs = MagicMock()
    mock_doc = MagicMock()
    mock_fs.collection.return_value.document.return_value = mock_doc

    mock_doc_snap = MagicMock()
    mock_doc_snap.exists = True
    mock_doc_snap.to_dict.return_value = {
        "streamer_handle": "raider",
        "tier": "bootstrapped",
        "bootstrap_context": {
            "bio_description": "Raider Bio",
            "vibe_tags": ["Variety"],
        },
        "primary_game": "Forza Horizon 5",
    }
    mock_doc.get.return_value = mock_doc_snap

    # Mock correlation document containing vibe tribes & coords
    mock_corr_doc = MagicMock()
    mock_corr_snap = MagicMock()
    mock_corr_snap.exists = True
    mock_corr_snap.to_dict.return_value = {
        "bellwether_scores": {"bellwether_x": 0.9},
        "vibe_tribes": {
            "1": {
                "label": "Neon Dusk Syndicate",
                "members": ["bellwether_x", "raider", "peer_y"],
            }
        },
        "constellation_coords": {
            "clusters": {"1": {"bellwether_x": {"x": 1.0, "y": 1.0, "z": 1.0}}}
        },
    }
    mock_corr_doc.get.return_value = mock_corr_snap

    # Mock peer profile doc
    mock_peer_doc = MagicMock()
    mock_peer_snap = MagicMock()
    mock_peer_snap.exists = True
    mock_peer_snap.to_dict.return_value = {
        "streamer_handle": "peer_y",
        "tier": "micro_streamer",
        "primary_game": "Forza Horizon 5",
        "current_vibe_tribe": "1",
        "bootstrap_context": {"bio_description": "Peer Bio", "vibe_tags": ["Racing"]},
    }
    mock_peer_doc.get.return_value = mock_peer_snap

    def document_side_effect(handle):
        if handle == "raider":
            return mock_doc
        elif handle == "current":
            return mock_corr_doc
        elif handle == "peer_y" or handle == "bellwether_x":
            return mock_peer_doc
        non_exist = MagicMock()
        non_exist.get.return_value.exists = False
        return non_exist

    mock_fs.collection.return_value.document.side_effect = document_side_effect

    # Mock stream references query return
    mock_stream = MagicMock()
    mock_stream.to_dict.return_value = mock_peer_snap.to_dict()
    mock_fs.collection.return_value.where.return_value.stream.return_value = [
        mock_stream
    ]
    mock_fs.collection.return_value.where.return_value.limit.return_value.stream.return_value = [  # noqa: E501
        mock_stream
    ]

    with (
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_firestore_client",
            return_value=mock_fs,
        ),
        patch(
            "ag_kaggle_5day.agents.advisor.get_cached_games",
            return_value=[{"title": "Forza Horizon 5", "tier": "trending"}],
        ),
        patch(
            "ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary",
            return_value=[],
        ),
        patch.dict(os.environ),
    ):
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        # Run matchmaker with API key disabled to trigger offline fallback and test
        # playbook templates
        result = run_matchmaker_pipeline("raider", api_key=None)
        assert "alliance_arcs" in result
        assert len(result["alliance_arcs"]) > 0

        arc = result["alliance_arcs"][0]
        assert "raid_playbook" in arc
        assert arc["raid_playbook"]["target_streamer"] == "peer_y"
        assert "copypasta" in arc["raid_playbook"]
        assert "opener" in arc["raid_playbook"]
        assert "why_it_works" in arc["raid_playbook"]
