from __future__ import annotations

import logging

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def store_streamer_similarity_history(pairs_data: list[dict]) -> None:
    """Stores the daily pairwise similarity score and metrics differences

    in BigQuery.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_bigquery_client,
        upgrade_bigquery_constraints,
    )

    if not pairs_data:
        return

    bq_client = get_bigquery_client()
    if not bq_client:
        logger.warning(
            "BigQuery client not available. Skipping similarity timeseries store."
        )
        return

    import time

    try:
        project = bq_client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.streamer_similarity_history"

        try:
            bq_client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            bq_client.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("streamer_a", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("streamer_b", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("similarity_score", "FLOAT", mode="REQUIRED"),
            bigquery.SchemaField("game_jaccard_overlap", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("engagement_density_diff", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("polarization_diff", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("why_explanation", "STRING", mode="NULLABLE"),
        ]

        try:
            bq_client.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                field="timestamp",
                expiration_ms=365 * 24 * 3600 * 1000,
            )
            bq_client.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        import datetime

        rows = []
        now_iso = datetime.datetime.fromtimestamp(
            time.time(), datetime.timezone.utc
        ).isoformat()

        for p in pairs_data:
            rows.append(
                {
                    "timestamp": now_iso,
                    "streamer_a": p["streamer_a"].strip().lower(),
                    "streamer_b": p["streamer_b"].strip().lower(),
                    "similarity_score": float(p["similarity_score"]),
                    "game_jaccard_overlap": float(p.get("game_jaccard_overlap", 0.0)),
                    "engagement_density_diff": float(
                        p.get("engagement_density_diff", 0.0)
                    ),
                    "polarization_diff": float(p.get("polarization_diff", 0.0)),
                    "why_explanation": p.get("why_explanation", ""),
                }
            )

        errors = bq_client.insert_rows_json(table_id, rows, timeout=30)
        if errors:
            logger.error(f"Failed to insert daily similarity rows to BQ: {errors}")
        else:
            logger.info(
                f"Successfully logged {len(rows)} similarity pairs in BigQuery."
            )
            upgrade_bigquery_constraints(bq_client)
    except Exception as e:
        logger.error(f"Error storing daily similarity in BigQuery: {e}")


def get_similarity_drift_from_db(
    streamer_a: str, streamer_b: str, limit_days: int = 30
) -> list[dict]:
    """Queries BigQuery to retrieve historical similarity scores between

    two streamers.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    bq_client = get_bigquery_client()
    if not bq_client:
        return []

    project = bq_client.project
    dataset = "streamer_metrics"
    sa = streamer_a.strip().lower()
    sb = streamer_b.strip().lower()

    try:
        query = f"""
            SELECT
              timestamp,
              similarity_score,
              game_jaccard_overlap,
              engagement_density_diff,
              polarization_diff,
              why_explanation
            FROM `{project}.{dataset}.streamer_similarity_history`
            WHERE
              ((LOWER(streamer_a) = @sa AND LOWER(streamer_b) = @sb)
               OR (LOWER(streamer_a) = @sb AND LOWER(streamer_b) = @sa))
              AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            ORDER BY timestamp ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sa", "STRING", sa),
                bigquery.ScalarQueryParameter("sb", "STRING", sb),
                bigquery.ScalarQueryParameter("days", "INTEGER", limit_days),
            ]
        )
        query_job = bq_client.query(query, job_config=job_config)
        results = []
        for row in query_job:
            results.append(
                {
                    "timestamp": row.timestamp.timestamp(),
                    "similarity_score": round(row.similarity_score, 4),
                    "game_jaccard_overlap": round(row.game_jaccard_overlap or 0.0, 4),
                    "engagement_density_diff": round(
                        row.engagement_density_diff or 0.0, 4
                    ),
                    "polarization_diff": round(row.polarization_diff or 0.0, 4),
                    "why_explanation": row.why_explanation or "",
                }
            )
        return results
    except Exception as e:
        logger.error(f"Failed to query similarity drift from BigQuery: {e}")
        return []
