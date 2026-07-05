from __future__ import annotations

import datetime
import json
import logging
from typing import Optional

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def store_streamer_sentiment(
    streamer_handle: str, sentiment_data: dict, source: str
) -> None:
    """Stores the streamer chat sentiment metrics in Firestore (cache) and
    BigQuery (history).
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_firestore_client,
    )

    fs_client = get_firestore_client()
    original_handle = streamer_handle.strip()
    handle = original_handle.lower()
    now_ts = time.time()
    is_offline = sentiment_data.get("sentiment") == "Offline"

    if fs_client and not is_offline:
        try:
            # Read last known cached values to avoid zeroing out fields in history
            cached_ref = (
                fs_client.collection("streamer_sentiment").document(handle).get()
            )
            cached_data = cached_ref.to_dict() if cached_ref.exists else {}

            doc_data = {
                "streamer_handle": original_handle
                if original_handle.lower().startswith("uc")
                else handle,
                "timestamp": now_ts,
                "msg_per_minute": sentiment_data.get("msg_per_minute", 0.0),
                "sentiment": sentiment_data.get("sentiment", "Neutral"),
                "total_messages": sentiment_data.get("total_messages", 0),
                "messages": sentiment_data.get("messages", []),
                "source": source,
                "game_name": sentiment_data.get("game_name")
                or cached_data.get("game_name")
                or "Unknown",
                "chat_volatility": sentiment_data.get("chat_volatility", 0.0),
                "rolling_sentiment_score": sentiment_data.get(
                    "rolling_sentiment_score", 0.0
                ),
            }
            if original_handle.lower().startswith("uc"):
                doc_data["youtube_channel_id"] = original_handle
            for field in [
                "summary",
                "streamer_channel_url",
                "stream_url",
                "top_streamers_of_game",
                "viewer_count",
                "last_highlight",
                "spectator_ratio",
                "recent_clips",
                "game_tags",
                "user_name",
                "display_name",
            ]:
                if field in sentiment_data:
                    doc_data[field] = sentiment_data[field]
                elif field in cached_data:
                    doc_data[field] = cached_data[field]

            # Cache the latest document with merge=True
            fs_client.collection("streamer_sentiment").document(handle).set(
                doc_data, merge=True
            )
            logger.info(f"Cached sentiment for streamer '{handle}' in Firestore.")

            # Save historical snapshot with 7-day TTL
            history_id = f"{handle}_{int(now_ts)}"
            doc_data_history = dict(doc_data)
            expire_dt = datetime.datetime.fromtimestamp(
                now_ts + 7 * 86400, datetime.timezone.utc
            )
            doc_data_history["expire_at"] = expire_dt
            fs_client.collection("streamer_sentiment_history").document(history_id).set(
                doc_data_history
            )
            logger.info(
                f"Saved historical sentiment for streamer '{handle}' in Firestore."
            )
        except Exception as e:
            logger.error(f"Failed to cache streamer sentiment in Firestore: {e}")

    bq_client = get_bigquery_client()
    if bq_client:
        try:
            project = bq_client.project
            dataset_id = f"{project}.streamer_metrics"
            table_id = f"{dataset_id}.sentiment_history"

            try:
                bq_client.get_dataset(dataset_id)
            except Exception:
                dataset = bigquery.Dataset(dataset_id)
                dataset.location = "US"
                bq_client.create_dataset(dataset, timeout=30)

            schema = [
                bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("streamer_handle", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("total_messages", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("msg_per_minute", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("sentiment", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("source", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("streamer_channel_url", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("stream_url", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("game_name", "STRING", mode="NULLABLE"),
                bigquery.SchemaField(
                    "top_streamers_of_game", "STRING", mode="NULLABLE"
                ),
                bigquery.SchemaField("viewer_count", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("chat_volatility", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("spectator_ratio", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("summary", "STRING", mode="NULLABLE"),
                bigquery.SchemaField(
                    "rolling_sentiment_score", "FLOAT", mode="NULLABLE"
                ),
            ]

            try:
                table = bq_client.get_table(table_id)
                # Check if schema needs updates for new fields
                existing_fields = {field.name for field in table.schema}
                new_fields = []
                if "streamer_channel_url" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "streamer_channel_url", "STRING", mode="NULLABLE"
                        )
                    )
                if "stream_url" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField("stream_url", "STRING", mode="NULLABLE")
                    )
                if "game_name" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField("game_name", "STRING", mode="NULLABLE")
                    )
                if "top_streamers_of_game" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "top_streamers_of_game", "STRING", mode="NULLABLE"
                        )
                    )
                if "viewer_count" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField("viewer_count", "INTEGER", mode="NULLABLE")
                    )
                if "chat_volatility" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "chat_volatility", "FLOAT", mode="NULLABLE"
                        )
                    )
                if "spectator_ratio" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "spectator_ratio", "FLOAT", mode="NULLABLE"
                        )
                    )
                if "summary" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField("summary", "STRING", mode="NULLABLE")
                    )
                if "rolling_sentiment_score" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "rolling_sentiment_score", "FLOAT", mode="NULLABLE"
                        )
                    )
                if new_fields:
                    table.schema = list(table.schema) + new_fields
                    bq_client.update_table(table, ["schema"])
                    logger.info(f"Updated schema for BigQuery table {table_id}")
            except NotFound:
                try:
                    table = bigquery.Table(table_id, schema=schema)
                    table.time_partitioning = bigquery.TimePartitioning(
                        field="timestamp",
                        expiration_ms=90 * 24 * 3600 * 1000,  # 90 days in ms
                    )
                    bq_client.create_table(table, timeout=30)
                    logger.info(f"Created BigQuery table {table_id}")
                except Conflict:
                    pass

            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

            top_streamers = sentiment_data.get("top_streamers_of_game", [])
            import json

            try:
                top_streamers_str = json.dumps(top_streamers)
            except Exception:
                top_streamers_str = "[]"

            row = {
                "timestamp": now_str,
                "streamer_handle": original_handle
                if original_handle.lower().startswith("uc")
                else handle,
                "total_messages": sentiment_data.get("total_messages", 0),
                "msg_per_minute": sentiment_data.get("msg_per_minute", 0.0),
                "sentiment": sentiment_data.get("sentiment", "Neutral"),
                "source": source,
                "streamer_channel_url": sentiment_data.get("streamer_channel_url", ""),
                "stream_url": sentiment_data.get("stream_url", ""),
                "game_name": sentiment_data.get("game_name", "Unknown"),
                "top_streamers_of_game": top_streamers_str,
                "viewer_count": sentiment_data.get("viewer_count", 0),
                "chat_volatility": sentiment_data.get("chat_volatility", 0.0),
                "spectator_ratio": sentiment_data.get("spectator_ratio"),
                "summary": sentiment_data.get("summary", ""),
                "rolling_sentiment_score": sentiment_data.get(
                    "rolling_sentiment_score", 0.0
                ),
            }
            errors = bq_client.insert_rows_json(table_id, [row], timeout=30)
            if errors:
                logger.error(f"Failed to insert sentiment row into BigQuery: {errors}")
            else:
                logger.info(f"Logged sentiment for streamer '{handle}' in BigQuery.")
        except Exception as e:
            logger.error(f"Failed to log streamer sentiment in BigQuery: {e}")


def get_cached_streamer_sentiment(streamer_handle: str) -> Optional[dict]:
    """Retrieves cached streamer sentiment from Firestore if it exists and
    is less than 1 hour old.
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_firestore_client,
        resolve_streamer_link,
    )

    fs_client = get_firestore_client()
    if not fs_client:
        return None
    try:
        handle = streamer_handle.strip().lower()

        link_info = None
        try:
            if not getattr(resolve_streamer_link, "_running", False):
                resolve_streamer_link._running = True
                link_info = resolve_streamer_link(handle, fs_client)
                resolve_streamer_link._running = False
        except Exception:
            resolve_streamer_link._running = False

        handles_to_fetch = [handle]
        if link_info:
            twitch_h = link_info.get("twitch_handle")
            yt_h = link_info.get("youtube_channel_id")
            if twitch_h and twitch_h.strip().lower() not in [
                x.lower() for x in handles_to_fetch
            ]:
                handles_to_fetch.append(twitch_h.strip().lower())
            if yt_h and yt_h.strip().lower() not in [
                x.lower() for x in handles_to_fetch
            ]:
                handles_to_fetch.append(yt_h.strip().lower())

        merged_sentiment = {}
        twitch_s = None
        youtube_s = None
        for h in handles_to_fetch:
            doc = fs_client.collection("streamer_sentiment").document(h).get()
            if doc.exists:
                data = doc.to_dict()
                ts = data.get("timestamp")
                if ts and (time.time() - ts < 3600):
                    src = data.get("source", "").lower()
                    if src == "youtube" or h.lower().startswith("uc"):
                        youtube_s = data
                    else:
                        twitch_s = data

        if twitch_s or youtube_s:
            if twitch_s:
                merged_sentiment.update(twitch_s)
            if youtube_s:
                for k, v in youtube_s.items():
                    if v and (k not in merged_sentiment or not merged_sentiment[k]):
                        merged_sentiment[k] = v

            t_v = twitch_s.get("viewer_count", 0) if twitch_s else 0
            yt_v = youtube_s.get("viewer_count", 0) if youtube_s else 0
            merged_sentiment["twitch_viewers"] = t_v
            merged_sentiment["youtube_viewers"] = yt_v
            merged_sentiment["viewer_count"] = t_v + yt_v

            # Populate platform-specific sentiment metrics to keep them independent
            merged_sentiment["twitch_rolling_sentiment"] = (
                twitch_s.get("rolling_sentiment_score", 0.0) if twitch_s else 0.0
            )
            merged_sentiment["twitch_chat_volatility"] = (
                twitch_s.get("chat_volatility", 0.0) if twitch_s else 0.0
            )
            merged_sentiment["twitch_msg_per_minute"] = (
                twitch_s.get("msg_per_minute", 0.0) if twitch_s else 0.0
            )
            merged_sentiment["twitch_sentiment_label"] = (
                twitch_s.get("sentiment", "Offline") if twitch_s else "Offline"
            )

            merged_sentiment["youtube_rolling_sentiment"] = (
                youtube_s.get("rolling_sentiment_score", 0.0) if youtube_s else 0.0
            )
            merged_sentiment["youtube_chat_volatility"] = (
                youtube_s.get("chat_volatility", 0.0) if youtube_s else 0.0
            )
            merged_sentiment["youtube_msg_per_minute"] = (
                youtube_s.get("msg_per_minute", 0.0) if youtube_s else 0.0
            )
            merged_sentiment["youtube_sentiment_label"] = (
                youtube_s.get("sentiment", "Offline") if youtube_s else "Offline"
            )

            if twitch_s:
                merged_sentiment["twitch_url"] = (
                    twitch_s.get("streamer_channel_url")
                    or f"https://twitch.tv/{twitch_s.get('streamer_handle')}"
                )
            else:
                merged_sentiment["twitch_url"] = (
                    f"https://twitch.tv/{link_info.get('twitch_handle')}"
                    if link_info and link_info.get("twitch_handle")
                    else None
                )

            if youtube_s:
                merged_sentiment["youtube_url"] = (
                    youtube_s.get("streamer_channel_url")
                    or f"https://youtube.com/channel/{youtube_s.get('streamer_handle')}"
                )
            else:
                merged_sentiment["youtube_url"] = (
                    f"https://youtube.com/channel/{link_info.get('youtube_channel_id')}"
                    if link_info and link_info.get("youtube_channel_id")
                    else None
                )

            if t_v >= yt_v and twitch_s:
                merged_sentiment["source"] = "twitch"
                merged_sentiment["streamer_channel_url"] = merged_sentiment[
                    "twitch_url"
                ]
            elif youtube_s:
                merged_sentiment["source"] = "youtube"
                merged_sentiment["streamer_channel_url"] = merged_sentiment[
                    "youtube_url"
                ]

            if twitch_s and youtube_s:
                merged_sentiment["source"] = "both"

            return merged_sentiment
        else:
            # Fallback to single doc if no link or no timestamp match
            doc = fs_client.collection("streamer_sentiment").document(handle).get()
            if doc.exists:
                data = doc.to_dict()
                ts = data.get("timestamp")
                if ts and (time.time() - ts < 3600):
                    return data
    except Exception as e:
        logger.error(f"Error getting cached sentiment for {streamer_handle}: {e}")
    return None


def get_historical_sentiment_summary(
    streamer_handle: str, limit: int = 10
) -> list[dict]:
    """Retrieves historical sentiment logs for a streamer and sorts them in memory
    to avoid index overhead.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_case_preserved_youtube_id,
        get_firestore_client,
        resolve_streamer_link,
    )

    fs_client = get_firestore_client()
    if not fs_client:
        return []
    try:
        handle_clean = streamer_handle.strip()
        if handle_clean.lower().startswith("uc"):
            handle = get_case_preserved_youtube_id(
                handle_clean.lower(), None, fs_client
            )
        else:
            handle = handle_clean.lower()

        target_handles = [handle]
        link_info = resolve_streamer_link(handle, fs_client)
        if link_info:
            twitch_h = link_info.get("twitch_handle")
            yt_h = link_info.get("youtube_channel_id")
            if twitch_h and twitch_h.strip().lower() not in target_handles:
                target_handles.append(twitch_h.strip().lower())
            if yt_h:
                yt_preserved = get_case_preserved_youtube_id(
                    yt_h.strip().lower(), None, fs_client
                )
                if yt_preserved not in target_handles:
                    target_handles.append(yt_preserved)

        history_list = []
        for th in target_handles:
            docs = (
                fs_client.collection("streamer_sentiment_history")
                .where("streamer_handle", "==", th)
                .limit(50)
                .stream()
            )
            for doc in docs:
                d = doc.to_dict()
                history_list.append(d)

        # Sort and de-duplicate by timestamp (rounded to 5s to group overlaps)
        history_list = sorted(
            history_list, key=lambda x: x.get("timestamp") or 0.0, reverse=True
        )
        seen_timestamps = set()
        history = []
        for d in history_list:
            ts = d.get("timestamp")
            if ts:
                ts_rounded = round(ts / 5.0) * 5
                if ts_rounded in seen_timestamps:
                    continue
                seen_timestamps.add(ts_rounded)
            history.append(
                {
                    "timestamp": d.get("timestamp"),
                    "sentiment": d.get("sentiment", "Neutral"),
                    "msg_per_minute": d.get("msg_per_minute", 0.0),
                    "total_messages": d.get("total_messages", 0),
                    "summary": d.get("summary", ""),
                    "messages": d.get("messages", []),
                    "streamer_channel_url": d.get("streamer_channel_url", ""),
                    "stream_url": d.get("stream_url", ""),
                    "game_name": d.get("game_name", "Unknown"),
                    "top_streamers_of_game": d.get("top_streamers_of_game", []),
                    "viewer_count": d.get("viewer_count", 0),
                    "chat_volatility": d.get("chat_volatility", 0.0),
                    "rolling_sentiment_score": d.get("rolling_sentiment_score", 0.0),
                    "last_highlight": d.get("last_highlight"),
                }
            )
        return history[:limit]
    except Exception as e:
        logger.error(
            f"Error getting historical sentiment summary for {streamer_handle}: {e}"
        )
        return []


def store_streamer_sentiment_moment(
    streamer_handle: str,
    game_name: str,
    trigger_type: str,
    trigger_value: float,
    mpm: float,
    sentiment: str,
    summary: str,
    messages: Optional[list[str]] = None,
) -> None:
    """Stores high-interest chat events/highlights in BQ and

    Firestore 'streamer_moments'.
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_case_preserved_youtube_id,
        get_firestore_client,
    )

    fs = get_firestore_client()
    original_handle = streamer_handle.strip()
    if original_handle.lower().startswith("uc"):
        h = get_case_preserved_youtube_id(original_handle.lower(), None, fs)
    else:
        h = original_handle.lower()

    now_ts = time.time()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. Store to Firestore (cache with 7-day TTL)
    if fs:
        try:
            expire_dt = datetime.datetime.fromtimestamp(
                now_ts + 7 * 86400, datetime.timezone.utc
            )
            doc_data = {
                "streamer_handle": h,
                "timestamp": now_ts,
                "trigger_type": trigger_type,
                "trigger_value": float(trigger_value)
                if trigger_value is not None
                else 0.0,
                "msg_per_minute": float(mpm),
                "dominant_sentiment": sentiment,
                "summary": summary,
                "game_name": game_name,
                "expire_at": expire_dt,
            }
            if messages:
                doc_data["messages"] = messages
            fs.collection("streamer_moments").add(doc_data)
            logger.info(f"Cached sentiment highlight moment for '{h}' in Firestore.")
        except Exception as e:
            logger.error(f"Failed to cache sentiment moment in Firestore: {e}")

    # 2. Store to BigQuery (long term partition)
    bq = get_bigquery_client()
    if bq:
        try:
            project = bq.project
            dataset_id = f"{project}.streamer_metrics"
            table_id = f"{dataset_id}.streamer_sentiment_moments"

            try:
                bq.get_dataset(dataset_id)
            except Exception:
                dataset = bigquery.Dataset(dataset_id)
                dataset.location = "US"
                bq.create_dataset(dataset, timeout=30)

            schema = [
                bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("streamer_handle", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("game_name", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("trigger_type", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("trigger_value", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("msg_per_minute", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("dominant_sentiment", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("moment_summary", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("chat_snippet", "STRING", mode="NULLABLE"),
            ]

            try:
                table = bq.get_table(table_id)
                existing_fields = [f.name for f in table.schema]
                if "chat_snippet" not in existing_fields:
                    new_fields = [
                        bigquery.SchemaField("chat_snippet", "STRING", mode="NULLABLE")
                    ]
                    table.schema = list(table.schema) + new_fields
                    bq.update_table(table, ["schema"])
                    logger.info(f"Updated schema for BigQuery table {table_id}")
            except NotFound:
                try:
                    table = bigquery.Table(table_id, schema=schema)
                    table.time_partitioning = bigquery.TimePartitioning(
                        field="timestamp",
                        expiration_ms=90 * 24 * 3600 * 1000,
                    )
                    bq.create_table(table, timeout=30)
                    logger.info(f"Created BigQuery table {table_id}")
                except Conflict:
                    pass

            row = {
                "timestamp": now_str,
                "streamer_handle": h,
                "game_name": game_name,
                "trigger_type": trigger_type,
                "trigger_value": float(trigger_value)
                if trigger_value is not None
                else 0.0,
                "msg_per_minute": float(mpm),
                "dominant_sentiment": sentiment,
                "moment_summary": summary,
                "chat_snippet": json.dumps(messages) if messages else "[]",
            }
            errors = bq.insert_rows_json(table_id, [row], timeout=30)
            if errors:
                logger.error(f"Failed to insert sentiment moment row to BQ: {errors}")
            else:
                logger.info(f"Logged sentiment moment for '{h}' in BigQuery.")
        except Exception as e:
            logger.error(f"Exception saving sentiment moment to BigQuery: {e}")
