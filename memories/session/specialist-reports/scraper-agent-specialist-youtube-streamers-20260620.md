## Full Report

### Layer: scraper-agent-specialist

### Files Touched
- `src/ag_kaggle_5day/agents/scraper.py`
- `src/ag_kaggle_5day/agents/test_agents.py`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/agents/scraper.py b/src/ag_kaggle_5day/agents/scraper.py
--- a/src/ag_kaggle_5day/agents/scraper.py
+++ b/src/ag_kaggle_5day/agents/scraper.py
@@ -782,7 +782,7 @@ def get_viewers_for_game(self, game_name: str, max_results: int = 10) -> dict:
                 time.sleep(0.5)
                 return {"youtube_viewers": 0, "stream_count": 0}
 
-            # Step 2: videos.list — get liveStreamingDetails
+            # Step 2: videos.list — get liveStreamingDetails and snippet
             try:
                 videos_resp = requests.get(
                     self._VIDEOS_URL,
@@ -789,6 +789,6 @@
                         "key": self.api_key,
                         "id": ",".join(video_ids),
-                        "part": "liveStreamingDetails",
+                        "part": "liveStreamingDetails,snippet",
                     },
                     timeout=3,
                 )
@@ -801,7 +801,7 @@
                         f"{videos_resp.status_code}). Disabling YouTube client "
                         f"for this run."
                     )
-                    return {"youtube_viewers": 0, "stream_count": 0}
+                    return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}
                 videos_resp.raise_for_status()
             except Exception as err:
                 logger.warning(
@@ -808,6 +808,6 @@
                 )
                 time.sleep(0.5)
-                return {"youtube_viewers": 0, "stream_count": 0}
+                return {"youtube_viewers": 0, "stream_count": 0, "top_streamers": []}
 
             videos_data = videos_resp.json()
 
@@ -814,12 +814,35 @@
             stream_count = 0
+            streams_list = []
             for video in videos_data.get("items", []):
                 details = video.get("liveStreamingDetails", {})
+                snippet = video.get("snippet", {})
                 viewers_str = details.get("concurrentViewers", "0")
                 try:
-                    total_viewers += int(viewers_str)
+                    v_count = int(viewers_str)
+                    total_viewers += v_count
                     stream_count += 1
                 except (ValueError, TypeError):
-                    pass
+                    v_count = 0
+
+                channel_title = snippet.get("channelTitle") or "Unknown YouTuber"
+                channel_id = snippet.get("channelId") or ""
+                video_title = snippet.get("title") or ""
+
+                streams_list.append(
+                    {
+                        "user_name": channel_title,
+                        "user_login": channel_id,
+                        "title": video_title,
+                        "viewer_count": v_count,
+                        "platform": "youtube",
+                    }
+                )
+
+            # Sort and retrieve top 3 YouTube streamers by viewer count
+            streams_list.sort(key=lambda x: x.get("viewer_count", 0), reverse=True)
+            top_streamers = [s for s in streams_list if s.get("viewer_count", 0) > 0][:3]
+            if not top_streamers and streams_list:
+                top_streamers = streams_list[:3]
 
             logger.info(
                 f"YouTube viewers for '{game_name}': {total_viewers:,} "
@@ -826,6 +826,10 @@
             )
             time.sleep(0.5)
-            return {"youtube_viewers": total_viewers, "stream_count": stream_count}
+            return {
+                "youtube_viewers": total_viewers,
+                "stream_count": stream_count,
+                "top_streamers": top_streamers,
+            }
```

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Exit code: 0, 51 passed)

### Decisions & Alternatives
- Requested `part="liveStreamingDetails,snippet"` on YouTube `videos.list` step instead of `search.list` which preserves the 100-unit search quota cost while getting all required channel name, channel ID, and stream title data.
- Structured YouTube streamer profiles with `"platform": "youtube"` to separate them from Twitch streams for targeted rendering on the client dashboard.
- Integrated merging and sorting of Twitch and YouTube streams by viewership count before saving/indexing them, ensuring a clean hybrid list is stored.

### Risks / Follow-ups
- None.
