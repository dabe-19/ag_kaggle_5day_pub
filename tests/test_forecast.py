import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from ag_kaggle_5day.app import app, forecast_client_limiter, forecast_global_limiter

client = TestClient(app)


def setup_function():
    # Reset rate limiters before each test run
    forecast_client_limiter.requests.clear()
    forecast_global_limiter.requests.clear()


def test_api_streamer_forecast_insufficient_data():
    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_hist = patch("ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary")

    with p_fs as mock_fs, p_hist as mock_hist:
        mock_fs.return_value = MagicMock()
        # Return only 1 check (insufficient data: < 2 points)
        mock_hist.return_value = [
            {"timestamp": time.time(), "viewer_count": 100, "msg_per_minute": 10}
        ]

        response = client.get("/api/streamers/ninja/forecast")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "insufficient_data"
        assert "At least 2 data points" in data["message"]


def test_api_streamer_forecast_success():
    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_hist = patch("ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary")

    with p_fs as mock_fs, p_hist as mock_hist:
        mock_fs.return_value = MagicMock()
        # Return 8 hourly checks to have enough data points
        now = time.time()
        mock_hist.return_value = [
            {
                "timestamp": now - i * 3600.0,
                "viewer_count": 100 + i * 10,
                "msg_per_minute": 10 + i,
                "rolling_sentiment_score": 0.1 * i,
            }
            for i in range(8)
        ]

        response = client.get("/api/streamers/ninja/forecast?horizon=3")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["sample_count"] == 12  # padded to min 12 hours
        assert "predictions" in data
        assert "viewer_count" in data["predictions"]
        assert len(data["predictions"]["viewer_count"]["forecast"]) == 3


def test_api_tribe_forecast_success():
    p_fs = patch("ag_kaggle_5day.agents.gcp_storage.get_firestore_client")
    p_hist = patch("ag_kaggle_5day.agents.gcp_storage.get_historical_sentiment_summary")

    with p_fs as mock_fs, p_hist as mock_hist:
        mock_db = MagicMock()
        mock_fs.return_value = mock_db

        # Mock tribe names retrieval
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "0": {"label": "Midnight Faction", "members": ["ninja", "shroud"]}
        }
        mock_db.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        # Mock checks retrieval
        now = time.time()
        mock_hist.return_value = [
            {
                "timestamp": now - i * 3600.0,
                "viewer_count": 100 + i * 10,
                "msg_per_minute": 10 + i,
                "rolling_sentiment_score": 0.1 * i,
            }
            for i in range(8)
        ]

        response = client.get("/api/tribes/0/forecast?horizon=2")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["predictions"]["viewer_count"]["forecast"]) == 2
