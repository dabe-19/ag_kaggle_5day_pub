from unittest.mock import MagicMock, patch

from ag_kaggle_5day.agents.scraper import (
    YouTubeAPIClient,
    _scrape_youtube_live_chat,
    get_youtube_channel_live_video_id,
)


def test_scrape_viewers_via_html():
    client = YouTubeAPIClient(api_key="mock_key")

    dummy_html = """
    <html>
        <body>
            <script>
                var ytInitialData = {
"contents": {
    "twoColumnSearchResultsRenderer": {
        "primaryContents": {
            "sectionListRenderer": {
                "contents": [{
                    "itemSectionRenderer": {
                        "contents": [{
                            "videoRenderer": {
                                "videoId": "abc123xyz77",
                                "viewCountText": {
                                    "simpleText": "1,200 watching now"
                                },
                                "badges": [{
                                    "metadataBadgeRenderer": {
                                        "label": "LIVE"
                                    }
                                }],
                                "ownerText": {
                                    "runs": [{
                                        "text": "Top Streamer",
                                        "navigationEndpoint": {
                                            "browseEndpoint": {
                                                "browseId": "UCmockchannelid"
                                            }
                                        }
                                    }]
                                },
                                "title": {
                                    "runs": [{
                                        "text": "Minecraft Live Stream"
                                    }]
                                }
                            }
                        }]
                    }
                }]
            }
        }
    }
}
                };
            </script>
        </body>
    </html>
    """

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = dummy_html
        mock_get.return_value = mock_resp

        res = client._scrape_viewers_via_html("Minecraft")
        assert res is not None
        assert res["youtube_viewers"] == 1200
        assert res["stream_count"] == 1
        assert len(res["top_streamers"]) == 1
        assert res["top_streamers"][0]["user_name"] == "Top Streamer"
        assert res["top_streamers"][0]["user_login"] == "UCmockchannelid"
        assert res["top_streamers"][0]["title"] == "Minecraft Live Stream"


def test_get_channel_stats():
    client = YouTubeAPIClient(api_key="mock_key")

    dummy_api_response = {
        "items": [
            {
                "statistics": {
                    "subscriberCount": "150000",
                    "viewCount": "12000000",
                    "videoCount": "340",
                },
                "snippet": {
                    "title": "Mock Channel",
                    "description": "Fun streams",
                    "thumbnails": {
                        "default": {"url": "https://avatar.url/default.jpg"}
                    },
                },
            }
        ]
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dummy_api_response
        mock_get.return_value = mock_resp

        stats = client.get_channel_stats("UCmockchannelid")
        assert stats["youtube_subscribers"] == 150000
        assert stats["youtube_views"] == 12000000
        assert stats["youtube_videos"] == 340
        assert stats["youtube_avatar"] == "https://avatar.url/default.jpg"
        assert stats["youtube_title"] == "Mock Channel"


def test_get_youtube_channel_live_video_id():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        # Mock a redirect to watch?v=XYZ123ABC99
        mock_resp.url = "https://www.youtube.com/watch?v=XYZ123ABC99"
        mock_resp.text = '"isLive":true'
        mock_get.return_value = mock_resp

        vid_id = get_youtube_channel_live_video_id("UCmockchannelid")
        assert vid_id == "XYZ123ABC99"


def test_scrape_youtube_live_chat():
    dummy_chat_html = """
    <html>
        <body>
            <script>
                var ytInitialData = {
                    "contents": {
                        "liveChatRenderer": {
                            "actions": [
                                {
                                    "addChatItemAction": {
                                        "item": {
                                            "liveChatTextMessageRenderer": {
                                                "authorName": {
                                                    "simpleText": "Chatter1"
                                                },
                                                "message": {
                                                    "runs": [
                                                        {
                                                            "text": "Hello world!"
                                                        }
                                                    ]
                                                },
                                                "timestampUsec": "1782779702240000"
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                };
            </script>
        </body>
    </html>
    """

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = dummy_chat_html
        mock_get.return_value = mock_resp

        msgs = _scrape_youtube_live_chat("XYZ123ABC99")
        assert len(msgs) == 1
        assert msgs[0]["author"] == "Chatter1"
        assert msgs[0]["message"] == "Hello world!"
        assert msgs[0]["timestamp"] == 1782779702.24
