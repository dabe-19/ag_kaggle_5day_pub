from __future__ import annotations

import logging
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def store_daily_streamer_analytics_timeseries(streamer_handle: str, data: dict) -> None:
    """Stores the daily aggregated timeseries snapshot for a streamer in BigQuery."""
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq_client = get_bigquery_client()
    if not bq_client:
        logger.warning(
            "BigQuery client not available. Skipping daily timeseries store."
        )
        return

    import time

    try:
        project = bq_client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.streamer_analytics_timeseries"

        try:
            bq_client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            bq_client.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("streamer_handle", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("average_msg_per_minute", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("dominant_sentiment", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(
                "consolidated_chat_summary", "STRING", mode="NULLABLE"
            ),
            bigquery.SchemaField("primary_game", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("top_games", "STRING", mode="REPEATED"),
            bigquery.SchemaField("viewer_count", "INTEGER", mode="NULLABLE"),
        ]

        try:
            bq_client.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            bq_client.create_table(table, timeout=30)

        import datetime
        import re

        raw_handle = streamer_handle.strip()
        is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", raw_handle))
        if is_yt:
            handle = raw_handle
            if handle.lower().startswith("uc") and not handle.startswith("UC"):
                handle = "UC" + handle[2:]
        else:
            handle = raw_handle.lower()

        row = {
            "timestamp": datetime.datetime.fromtimestamp(
                time.time(), datetime.timezone.utc
            ).isoformat(),
            "streamer_handle": handle,
            "average_msg_per_minute": float(data.get("average_msg_per_minute", 0.0)),
            "dominant_sentiment": data.get("dominant_sentiment", "Neutral"),
            "consolidated_chat_summary": data.get("consolidated_chat_summary", ""),
            "primary_game": data.get("primary_game", ""),
            "top_games": data.get("top_games", []),
            "viewer_count": int(data.get("viewer_count", 0)),
        }

        errors = bq_client.insert_rows_json(table_id, [row])
        if errors:
            logger.error(f"Failed to insert daily timeseries row to BQ: {errors}")
        else:
            logger.info(f"Logged daily timeseries for '{streamer_handle}' in BigQuery.")
    except Exception as e:
        logger.error(f"Error storing daily timeseries in BigQuery: {e}")


def store_streamer_profile_fabric(streamer_handle: str, profile: dict) -> None:
    """Stores current cluster mappings in BQ and Firestore 'streamer_profiles'."""
    import re
    import time

    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_case_preserved_youtube_id,
        get_firestore_client,
        upgrade_bigquery_constraints,
    )

    raw_handle = streamer_handle.strip()
    is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", raw_handle))
    fs_client = get_firestore_client()
    if is_yt:
        handle = get_case_preserved_youtube_id(raw_handle.lower(), None, fs_client)
    else:
        handle = raw_handle.lower()

    # 1. Sync to Firestore
    if fs_client:
        try:
            doc_data = {
                "streamer_handle": handle,
                "archetype_cluster": profile.get(
                    "archetype_cluster", "Cozy_Social_Interactive"
                ),
                "peer_connections": profile.get("peer_connections", []),
                "time_active_cluster": profile.get("time_active_cluster", "evening"),
                "category_cluster": profile.get("category_cluster", "Variety"),
                "primary_game": profile.get("primary_game", ""),
                "top_games": profile.get("top_games", []),
                "fabric_status": profile.get("fabric_status", "preliminary"),
                "peer_details": profile.get("peer_details", []),
                "composite_chat_summary": profile.get("composite_chat_summary", ""),
                "average_msg_per_minute": profile.get("average_msg_per_minute", 10.0),
                "std_msg_per_minute": profile.get("std_msg_per_minute", 3.0),
                "average_chat_volatility": profile.get("average_chat_volatility", 0.5),
                "std_chat_volatility": profile.get("std_chat_volatility", 0.15),
                "youtube_subscribers": profile.get("youtube_subscribers"),
                "youtube_views": profile.get("youtube_views"),
                "youtube_videos": profile.get("youtube_videos"),
                "youtube_avatar": profile.get("youtube_avatar"),
                "youtube_description": profile.get("youtube_description"),
                "youtube_title": profile.get("youtube_title"),
                "twitch_avatar": profile.get("twitch_avatar"),
                "twitch_description": profile.get("twitch_description"),
                "recent_youtube_video_title": profile.get("recent_youtube_video_title"),
                "recent_youtube_video_url": profile.get("recent_youtube_video_url"),
                "recent_twitch_video_title": profile.get("recent_twitch_video_title"),
                "recent_twitch_video_url": profile.get("recent_twitch_video_url"),
                "tier": profile.get("tier", "affiliate"),
                "closest_gravity_well": profile.get("closest_gravity_well", ""),
                "language": profile.get("language"),
                "schedule": profile.get("schedule"),
                "recent_clips": profile.get("recent_clips"),
                "interaction_density": profile.get(
                    "interaction_density",
                    {
                        "msg_per_minute": profile.get("average_msg_per_minute", 10.0),
                        "chat_volatility": profile.get("average_chat_volatility", 0.5),
                        "interactive_density_rate": profile.get(
                            "average_msg_per_minute", 10.0
                        )
                        / (profile.get("viewer_count") or 50.0)
                        if (profile.get("viewer_count") or 50.0) > 0
                        else 0.0,
                    },
                ),
                "starfield_coordinates": profile.get(
                    "starfield_coordinates", {"x": 0.0, "y": 0.0, "z": 0.0}
                ),
                "current_vibe_tribe": str(profile.get("current_vibe_tribe", "0")),
                "bootstrap_context": profile.get("bootstrap_context", {}),
                "last_updated": time.time(),
                "last_aggregated": time.time(),
            }
            if is_yt:
                doc_data["youtube_channel_id"] = handle

            fs_client.collection("streamer_profiles").document(handle).set(
                doc_data, merge=True
            )
            logger.info(f"Cached profile fabric for streamer '{handle}' in Firestore.")
        except Exception as e:
            logger.error(f"Failed to cache profile fabric in Firestore: {e}")

    # 2. Write to BigQuery
    bq_client = get_bigquery_client()
    if bq_client:
        try:
            project = bq_client.project
            dataset_id = f"{project}.streamer_metrics"
            table_id = f"{dataset_id}.streamer_profile_fabric"

            try:
                bq_client.get_dataset(dataset_id)
            except Exception:
                dataset = bigquery.Dataset(dataset_id)
                dataset.location = "US"
                bq_client.create_dataset(dataset, timeout=30)

            schema = [
                bigquery.SchemaField("streamer_handle", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("archetype_cluster", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("peer_connections", "STRING", mode="REPEATED"),
                bigquery.SchemaField("time_active_cluster", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("category_cluster", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("primary_game", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("top_games", "STRING", mode="REPEATED"),
                bigquery.SchemaField("fabric_status", "STRING", mode="NULLABLE"),
                bigquery.SchemaField(
                    "composite_chat_summary", "STRING", mode="NULLABLE"
                ),
                bigquery.SchemaField("tier", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("closest_gravity_well", "STRING", mode="NULLABLE"),
                bigquery.SchemaField(
                    "interactive_density_rate", "FLOAT", mode="NULLABLE"
                ),
                bigquery.SchemaField("last_updated", "TIMESTAMP", mode="REQUIRED"),
            ]

            try:
                table = bq_client.get_table(table_id)
                existing_fields = {field.name for field in table.schema}
                new_fields = []
                if "composite_chat_summary" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "composite_chat_summary", "STRING", mode="NULLABLE"
                        )
                    )
                if "tier" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField("tier", "STRING", mode="NULLABLE")
                    )
                if "closest_gravity_well" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "closest_gravity_well", "STRING", mode="NULLABLE"
                        )
                    )
                if "interactive_density_rate" not in existing_fields:
                    new_fields.append(
                        bigquery.SchemaField(
                            "interactive_density_rate", "FLOAT", mode="NULLABLE"
                        )
                    )
                if new_fields:
                    table.schema = list(table.schema) + new_fields
                    bq_client.update_table(table, ["schema"])
                    logger.info(f"Updated schema for BigQuery table {table_id}")
            except Exception:
                table = bigquery.Table(table_id, schema=schema)
                bq_client.create_table(table, timeout=30)

            import datetime

            row = {
                "streamer_handle": handle,
                "archetype_cluster": profile.get(
                    "archetype_cluster", "Cozy_Social_Interactive"
                ),
                "peer_connections": profile.get("peer_connections", []),
                "time_active_cluster": profile.get("time_active_cluster", "evening"),
                "category_cluster": profile.get("category_cluster", "Variety"),
                "primary_game": profile.get("primary_game", ""),
                "top_games": profile.get("top_games", []),
                "fabric_status": profile.get("fabric_status", "preliminary"),
                "composite_chat_summary": profile.get("composite_chat_summary", ""),
                "tier": profile.get("tier", "affiliate"),
                "closest_gravity_well": profile.get("closest_gravity_well", ""),
                "interactive_density_rate": float(
                    profile.get("interaction_density", {}).get(
                        "interactive_density_rate", 0.0
                    )
                ),
                "last_updated": datetime.datetime.fromtimestamp(
                    time.time(), datetime.timezone.utc
                ).isoformat(),
            }

            errors = bq_client.insert_rows_json(table_id, [row])
            if errors:
                logger.error(f"Failed to insert profile fabric row to BQ: {errors}")
            else:
                logger.info(f"Logged profile fabric for '{handle}' in BigQuery.")
                upgrade_bigquery_constraints(bq_client)
        except Exception as e:
            logger.error(f"Error storing profile fabric in BigQuery: {e}")


def update_streamer_adaptive_metrics(
    streamer_handle: str, adaptive_metrics: dict
) -> None:
    """Updates only the adaptive_metrics field for a streamer in

    the streamer_profiles collection.
    """
    import time

    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    handle = streamer_handle.strip().lower()
    fs_client = get_firestore_client()
    if fs_client:
        try:
            fs_client.collection("streamer_profiles").document(handle).set(
                {"adaptive_metrics": adaptive_metrics, "last_updated": time.time()},
                merge=True,
            )
            logger.info(
                f"Updated adaptive metrics for streamer '{handle}' in Firestore."
            )
        except Exception as e:
            logger.error(f"Failed to update adaptive metrics in Firestore: {e}")


def get_archetype_analytics_from_db() -> list[dict]:
    """Queries BigQuery or falls back to Firestore to retrieve aggregate metrics
    grouped by streamer archetype.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_firestore_client,
    )

    bq_client = get_bigquery_client()
    if bq_client:
        try:
            project = bq_client.project
            query = f"""
                SELECT
                  f.archetype_cluster,
                  COUNT(DISTINCT f.streamer_handle) as streamer_count,
                  AVG(t.average_msg_per_minute) as avg_msg_per_minute,
                  SAFE_DIVIDE(
                    COUNTIF(t.dominant_sentiment = 'Positive'), COUNT(*)
                  ) as positive_ratio,
                  SAFE_DIVIDE(
                    COUNTIF(t.dominant_sentiment = 'Neutral'), COUNT(*)
                  ) as neutral_ratio,
                  SAFE_DIVIDE(
                    COUNTIF(t.dominant_sentiment = 'Negative'), COUNT(*)
                  ) as negative_ratio,
                  SAFE_DIVIDE(
                    COUNTIF(t.dominant_sentiment = 'Mixed'), COUNT(*)
                  ) as mixed_ratio,
                  ARRAY_TO_STRING(
                    ARRAY_AGG(DISTINCT f.primary_game IGNORE NULLS LIMIT 5),
                    ', '
                  ) as top_games
                FROM `{project}.streamer_metrics.streamer_profile_fabric` f
                LEFT JOIN `{project}.streamer_metrics.streamer_analytics_timeseries` t
                  ON f.streamer_handle = t.streamer_handle
                GROUP BY f.archetype_cluster
            """
            query_job = bq_client.query(query)
            results = []
            for row in query_job:
                results.append(
                    {
                        "archetype_cluster": row.archetype_cluster or "Unknown",
                        "streamer_count": row.streamer_count or 0,
                        "avg_msg_per_minute": round(row.avg_msg_per_minute or 0.0, 2),
                        "positive_ratio": round(row.positive_ratio or 0.0, 4),
                        "neutral_ratio": round(row.neutral_ratio or 0.0, 4),
                        "negative_ratio": round(row.negative_ratio or 0.0, 4),
                        "mixed_ratio": round(row.mixed_ratio or 0.0, 4),
                        "top_games": row.top_games or "Variety",
                    }
                )
            if results:
                return results
        except Exception as e:
            logger.error(f"BigQuery archetype aggregation query failed: {e}")

    # Firestore fallback
    fs_client = get_firestore_client()
    if not fs_client:
        return []

    try:
        profiles = list(fs_client.collection("streamer_profiles").stream())
        if not profiles:
            return []

        archetype_data = {}
        for p_doc in profiles:
            p = p_doc.to_dict()
            arch = p.get("archetype_cluster", "Cozy_Social_Interactive")
            handle = p_doc.id.lower()

            if arch not in archetype_data:
                archetype_data[arch] = {
                    "archetype_cluster": arch,
                    "streamers": set(),
                    "msg_speeds": [],
                    "sentiments": [],
                    "games": {},
                }

            archetype_data[arch]["streamers"].add(handle)
            pg = p.get("primary_game")
            if pg and pg != "Unknown" and pg != "Variety":
                archetype_data[arch]["games"][pg] = (
                    archetype_data[arch]["games"].get(pg, 0) + 1
                )

            # Fetch daily timeseries
            ts_doc = (
                fs_client.collection("streamer_analytics_timeseries")
                .document(handle)
                .get()
            )
            if ts_doc.exists:
                ts = ts_doc.to_dict()
                speed = ts.get("average_msg_per_minute", 0.0)
                if speed > 0:
                    archetype_data[arch]["msg_speeds"].append(speed)
                sent = ts.get("dominant_sentiment")
                if sent and sent != "Offline":
                    archetype_data[arch]["sentiments"].append(sent)

        results = []
        for arch, d in archetype_data.items():
            from collections import Counter

            total_sent = len(d["sentiments"])
            sent_counts = Counter(d["sentiments"])

            top_games_sorted = sorted(
                d["games"].items(), key=lambda x: x[1], reverse=True
            )
            top_games_str = (
                ", ".join([g[0] for g in top_games_sorted[:5]])
                if top_games_sorted
                else "Variety"
            )

            results.append(
                {
                    "archetype_cluster": arch,
                    "streamer_count": len(d["streamers"]),
                    "avg_msg_per_minute": round(
                        sum(d["msg_speeds"]) / len(d["msg_speeds"])
                        if d["msg_speeds"]
                        else 0.0,
                        2,
                    ),
                    "positive_ratio": round(
                        sent_counts.get("Positive", 0) / max(1, total_sent), 4
                    ),
                    "neutral_ratio": round(
                        sent_counts.get("Neutral", 0) / max(1, total_sent), 4
                    ),
                    "negative_ratio": round(
                        sent_counts.get("Negative", 0) / max(1, total_sent), 4
                    ),
                    "mixed_ratio": round(
                        sent_counts.get("Mixed", 0) / max(1, total_sent), 4
                    ),
                    "top_games": top_games_str,
                }
            )
        return results
    except Exception as e:
        logger.error(f"Firestore fallback archetype aggregation failed: {e}")
        return []


def get_game_sentiment_metrics_from_db(game_name: str = None) -> list[dict]:
    """Queries BigQuery or falls back to Firestore to calculate

    sentiment metrics for games.
    If game_name is provided, filters for that specific game.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        get_firestore_client,
    )

    bq_client = get_bigquery_client()
    if bq_client:
        try:
            project = bq_client.project
            if game_name:
                query = f"""
                    SELECT
                      COALESCE(f.primary_game, t.primary_game) as game,
                      AVG(t.average_msg_per_minute) as avg_msg_per_minute,
                      COUNT(DISTINCT t.streamer_handle) as streamer_count,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Positive'), COUNT(*)
                      ) as positive_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Neutral'), COUNT(*)
                      ) as neutral_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Negative'), COUNT(*)
                      ) as negative_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Mixed'), COUNT(*)
                      ) as mixed_ratio,
                      ARRAY_TO_STRING(
                        ARRAY_AGG(
                          DISTINCT f.archetype_cluster IGNORE NULLS LIMIT 3
                        ),
                        ', '
                      ) as archetypes
                    FROM `{project}.streamer_metrics.streamer_profile_fabric` f
                    JOIN `{project}.streamer_metrics.streamer_analytics_timeseries` t
                      ON f.streamer_handle = t.streamer_handle
                    WHERE LOWER(f.primary_game) = @game_name
                      OR LOWER(t.primary_game) = @game_name
                    GROUP BY game
                """
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter(
                            "game_name", "STRING", game_name.strip().lower()
                        )
                    ]
                )
                query_job = bq_client.query(query, job_config=job_config)
            else:
                query = f"""
                    SELECT
                      COALESCE(f.primary_game, t.primary_game) as game,
                      AVG(t.average_msg_per_minute) as avg_msg_per_minute,
                      COUNT(DISTINCT t.streamer_handle) as streamer_count,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Positive'), COUNT(*)
                      ) as positive_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Neutral'), COUNT(*)
                      ) as neutral_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Negative'), COUNT(*)
                      ) as negative_ratio,
                      SAFE_DIVIDE(
                        COUNTIF(t.dominant_sentiment = 'Mixed'), COUNT(*)
                      ) as mixed_ratio,
                      '' as archetypes
                    FROM `{project}.streamer_metrics.streamer_profile_fabric` f
                    JOIN `{project}.streamer_metrics.streamer_analytics_timeseries` t
                      ON f.streamer_handle = t.streamer_handle
                    GROUP BY game
                    ORDER BY avg_msg_per_minute DESC
                    LIMIT 10
                """
                query_job = bq_client.query(query)

            results = []
            for row in query_job:
                results.append(
                    {
                        "game": row.game or "Variety",
                        "avg_msg_per_minute": round(row.avg_msg_per_minute or 0.0, 2),
                        "streamer_count": row.streamer_count or 0,
                        "positive_ratio": round(row.positive_ratio or 0.0, 4),
                        "neutral_ratio": round(row.neutral_ratio or 0.0, 4),
                        "negative_ratio": round(row.negative_ratio or 0.0, 4),
                        "mixed_ratio": round(row.mixed_ratio or 0.0, 4),
                        "archetypes": row.archetypes
                        if hasattr(row, "archetypes")
                        else "",
                    }
                )
            if results:
                return results
        except Exception as e:
            logger.error(f"BigQuery game sentiment aggregation failed: {e}")

    # Firestore fallback
    fs_client = get_firestore_client()
    if not fs_client:
        return []

    try:
        profiles = list(fs_client.collection("streamer_profiles").stream())
        if not profiles:
            return []

        game_data = {}
        for p_doc in profiles:
            p = p_doc.to_dict()
            handle = p_doc.id.lower()
            arch = p.get("archetype_cluster", "Cozy_Social_Interactive")

            # Fetch daily timeseries
            ts_doc = (
                fs_client.collection("streamer_analytics_timeseries")
                .document(handle)
                .get()
            )
            if ts_doc.exists:
                ts = ts_doc.to_dict()
                pg = ts.get("primary_game") or p.get("primary_game") or "Variety"

                if game_name and pg.strip().lower() != game_name.strip().lower():
                    continue

                if pg not in game_data:
                    game_data[pg] = {
                        "game": pg,
                        "msg_speeds": [],
                        "sentiments": [],
                        "archetypes": set(),
                        "streamers": set(),
                    }

                game_data[pg]["streamers"].add(handle)
                game_data[pg]["archetypes"].add(arch)
                speed = ts.get("average_msg_per_minute", 0.0)
                if speed > 0:
                    game_data[pg]["msg_speeds"].append(speed)
                sent = ts.get("dominant_sentiment")
                if sent and sent != "Offline":
                    game_data[pg]["sentiments"].append(sent)

        results = []
        for g, d in game_data.items():
            from collections import Counter

            total_sent = len(d["sentiments"])
            sent_counts = Counter(d["sentiments"])

            results.append(
                {
                    "game": g,
                    "avg_msg_per_minute": round(
                        sum(d["msg_speeds"]) / len(d["msg_speeds"])
                        if d["msg_speeds"]
                        else 0.0,
                        2,
                    ),
                    "streamer_count": len(d["streamers"]),
                    "positive_ratio": round(
                        sent_counts.get("Positive", 0) / max(1, total_sent), 4
                    ),
                    "neutral_ratio": round(
                        sent_counts.get("Neutral", 0) / max(1, total_sent), 4
                    ),
                    "negative_ratio": round(
                        sent_counts.get("Negative", 0) / max(1, total_sent), 4
                    ),
                    "mixed_ratio": round(
                        sent_counts.get("Mixed", 0) / max(1, total_sent), 4
                    ),
                    "archetypes": ", ".join(list(d["archetypes"])[:3]),
                }
            )

        if not game_name:
            results.sort(key=lambda x: x["avg_msg_per_minute"], reverse=True)
            results = results[:10]

        return results
    except Exception as e:
        logger.error(f"Firestore fallback game sentiment aggregation failed: {e}")
        return []


def get_streamer_profile_fabric_from_fs(streamer_handle: str) -> Optional[dict]:
    """Retrieves cached streamer profile fabric from Firestore if it exists."""
    from ag_kaggle_5day.agents.gcp_storage import (
        get_case_preserved_youtube_id,
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

        import re

        target_handle = handle
        if link_info:
            target_handle = link_info.get("twitch_handle") or handle

        is_yt = bool(re.match(r"^[uU][cC][a-zA-Z0-9_-]{22}$", target_handle))
        if is_yt:
            target_handle = get_case_preserved_youtube_id(
                target_handle, None, fs_client
            )

        doc = fs_client.collection("streamer_profiles").document(target_handle).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        logger.error(f"Error getting cached profile fabric for {streamer_handle}: {e}")
    return None


def query_streamer_connections_from_fs(filters: dict) -> list[dict]:
    """Queries the streamer_profiles collection in Firestore using filters."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    fs_client = get_firestore_client()
    if not fs_client:
        return []
    try:
        query = fs_client.collection("streamer_profiles")
        for key, val in filters.items():
            if val is not None:
                query = query.where(key, "==", val)
        docs = query.stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        logger.error(f"Error querying streamer connections in Firestore: {e}")
    return []
