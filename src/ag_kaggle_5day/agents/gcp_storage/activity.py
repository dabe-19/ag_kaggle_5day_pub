from __future__ import annotations

import datetime
import json
import logging
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def store_user_activity(
    visitor_id: str,
    session_hash: Optional[str],
    action_type: str,
    payload_data: Optional[dict],
    duration_ms: int,
    status: str,
    error_details: Optional[str] = None,
) -> None:
    """Logs anonymous user/visitor activities to BigQuery."""
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    client = get_bigquery_client()
    if not client:
        return

    try:
        project = client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.user_activity"

        try:
            client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            client.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("visitor_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("session_hash", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("action_type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("payload", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("duration_ms", "INTEGER", mode="REQUIRED"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("error_details", "STRING", mode="NULLABLE"),
        ]

        try:
            client.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            client.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        import datetime
        import json

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {
            "timestamp": now_str,
            "visitor_id": visitor_id,
            "session_hash": session_hash,
            "action_type": action_type,
            "payload": json.dumps(payload_data) if payload_data else None,
            "duration_ms": duration_ms,
            "status": status,
            "error_details": error_details,
        }
        errors = client.insert_rows_json(table_id, [row], timeout=30)
        if errors:
            logger.error(f"Failed to insert user activity row: {errors}")
    except Exception as e:
        logger.error(f"Exception saving user activity to BigQuery: {e}")


def store_streamer_raid_event(
    raider_handle: str, target_handle: str, viewer_count: int
) -> None:
    """Logs Twitch raid events to BigQuery table

    streamer_metrics.streamer_raid_history.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    client = get_bigquery_client()
    if not client:
        return

    try:
        project = client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.streamer_raid_history"

        try:
            client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            client.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("raider_handle", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("target_handle", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("viewer_count", "INTEGER", mode="NULLABLE"),
        ]

        try:
            client.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                field="timestamp",
                expiration_ms=90 * 24 * 3600 * 1000,
            )
            client.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        import datetime

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {
            "timestamp": now_str,
            "raider_handle": raider_handle.strip().lower(),
            "target_handle": target_handle.strip().lower(),
            "viewer_count": int(viewer_count) if viewer_count is not None else None,
        }
        errors = client.insert_rows_json(table_id, [row], timeout=30)
        if errors:
            logger.error(f"Failed to insert raid history row: {errors}")
        else:
            logger.info(
                "Logged raid event in BigQuery: "
                f"{raider_handle} -> {target_handle} "
                f"({viewer_count} viewers)"
            )
    except Exception as e:
        logger.error(f"Exception saving raid history to BigQuery: {e}")


def store_correlation_history(records: list[dict]) -> None:
    """Streams pairwise correlation records into BigQuery table

    'streamer_metrics.correlation_history'.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    if not records:
        return

    from google.cloud import bigquery

    bq = get_bigquery_client()
    if not bq:
        return

    try:
        project = bq.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.correlation_history"

        # Check and create dataset
        try:
            bq.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            bq.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("streamer_a", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("streamer_b", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("volatility_cov", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("sentiment_cov", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("msg_rate_cov", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("viewer_count_cov", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("convergence_velocity", "FLOAT", mode="NULLABLE"),
        ]

        try:
            bq.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                field="timestamp",
                expiration_ms=90 * 24 * 3600 * 1000,  # 90-day retention
            )
            bq.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = []
        for r in records:
            rows.append(
                {
                    "timestamp": now_str,
                    "streamer_a": r.get("streamer_a"),
                    "streamer_b": r.get("streamer_b"),
                    "volatility_cov": float(r.get("volatility_cov"))
                    if r.get("volatility_cov") is not None
                    else None,
                    "sentiment_cov": float(r.get("sentiment_cov"))
                    if r.get("sentiment_cov") is not None
                    else None,
                    "msg_rate_cov": float(r.get("msg_rate_cov"))
                    if r.get("msg_rate_cov") is not None
                    else None,
                    "viewer_count_cov": float(r.get("viewer_count_cov"))
                    if r.get("viewer_count_cov") is not None
                    else None,
                    "convergence_velocity": float(r.get("convergence_velocity"))
                    if r.get("convergence_velocity") is not None
                    else None,
                }
            )

        # Batch insert
        errors = bq.insert_rows_json(table_id, rows, timeout=30)
        if errors:
            logger.error(f"Failed to insert correlation records to BQ: {errors}")
        else:
            logger.info(f"Logged {len(rows)} correlation records in BigQuery.")
    except Exception as e:
        logger.error(f"Exception saving correlation history to BigQuery: {e}")


def store_ecosystem_snapshot(snapshot: dict) -> None:
    """Writes one row per computation cycle to

    'streamer_metrics.ecosystem_snapshots'."""

    from google.cloud import bigquery

    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq = get_bigquery_client()
    if not bq:
        return

    try:
        project = bq.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.ecosystem_snapshots"

        # Check and create dataset
        try:
            bq.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            bq.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("num_tribes", "INTEGER", mode="REQUIRED"),
            bigquery.SchemaField("tribe_assignments", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("tribe_labels", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("bellwether_rankings", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(
                "constellation_coords_galaxy", "STRING", mode="NULLABLE"
            ),
        ]

        try:
            bq.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                field="timestamp",
                expiration_ms=90 * 24 * 3600 * 1000,  # 90-day retention
            )
            bq.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {
            "timestamp": now_str,
            "num_tribes": int(snapshot.get("num_tribes", 0)),
            "tribe_assignments": json.dumps(snapshot.get("tribe_assignments", {})),
            "tribe_labels": json.dumps(snapshot.get("tribe_labels", {})),
            "bellwether_rankings": json.dumps(snapshot.get("bellwether_rankings", {})),
            "constellation_coords_galaxy": json.dumps(
                snapshot.get("constellation_coords_galaxy", {})
            ),
        }

        errors = bq.insert_rows_json(table_id, [row], timeout=30)
        if errors:
            logger.error(f"Failed to insert ecosystem snapshot to BQ: {errors}")
        else:
            logger.info("Logged ecosystem snapshot in BigQuery.")
    except Exception as e:
        logger.error(f"Exception saving ecosystem snapshot to BigQuery: {e}")
