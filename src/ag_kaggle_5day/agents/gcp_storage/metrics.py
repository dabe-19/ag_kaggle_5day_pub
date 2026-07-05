from __future__ import annotations

import datetime
import json
import logging

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def write_metrics_to_bigquery(games: list[dict]) -> None:
    """Inserts hourly metrics into BigQuery streamer_metrics.hourly_stats table."""
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    client = get_bigquery_client()
    if not client:
        logger.warning("BigQuery client not available. Skipping metrics write.")
        return

    # Use current project ID
    dataset_id = f"{client.project}.streamer_metrics"
    table_id = f"{dataset_id}.hourly_stats"

    # 1. Create dataset if not exists
    try:
        client.get_dataset(dataset_id)
    except Exception:
        try:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            client.create_dataset(dataset, timeout=30)
            logger.info(f"Created BigQuery dataset {dataset_id}")
        except Exception as e:
            logger.error(f"Failed to create BigQuery dataset {dataset_id}: {e}")
            return

    # 2. Create table if not exists
    schema = [
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("title", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("category", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("avg_viewers", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("twitch_viewers", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("youtube_viewers", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("avg_length_hours", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("score", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("tier", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("data_quality", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("source", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("top_streamers", "STRING", mode="NULLABLE"),
    ]

    try:
        table = client.get_table(table_id)
        # Migrate schema if top_streamers column is missing
        schema_names = [field.name for field in table.schema]
        if "top_streamers" not in schema_names:
            new_schema = list(table.schema)
            new_schema.append(
                bigquery.SchemaField("top_streamers", "STRING", mode="NULLABLE")
            )
            table.schema = new_schema
            client.update_table(table, ["schema"], timeout=30)
            logger.info(
                "Updated BigQuery table schema to add 'top_streamers' "
                f"column for {table_id}"
            )
    except Exception:
        try:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="timestamp"
            )
            client.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")
        except Exception as e:
            logger.error(f"Failed to create BigQuery table {table_id}: {e}")
            return

    # Create or update daily game summary view
    _create_bigquery_views(client, dataset_id, table_id)

    # 3. Format and insert rows

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = []
    for g in games:
        rows.append(
            {
                "timestamp": now_str,
                "title": g.get("title"),
                "category": g.get("category"),
                "avg_viewers": g.get("avg_viewers"),
                "twitch_viewers": g.get("twitch_viewers", 0),
                "youtube_viewers": g.get("youtube_viewers", 0),
                "avg_length_hours": g.get("avg_length_hours"),
                "score": float(g.get("score", 0))
                if g.get("score") is not None
                else None,
                "tier": g.get("tier"),
                "data_quality": g.get("data_quality"),
                "source": g.get("source"),
                "top_streamers": json.dumps(g.get("top_streamers", []))
                if g.get("top_streamers") is not None
                else None,
            }
        )

    if not rows:
        return

    try:
        errors = client.insert_rows_json(table_id, rows, timeout=30)
        if errors:
            logger.error(f"Failed to insert rows into BigQuery: {errors}")
        else:
            logger.info(
                f"Successfully inserted {len(rows)} rows into BigQuery table {table_id}"
            )
    except Exception as e:
        logger.error(f"Exception inserting rows to BigQuery: {e}")


def _create_bigquery_views(client, dataset_id: str, table_id: str) -> None:
    view_id = f"{dataset_id}.daily_game_summary"
    view = bigquery.Table(view_id)
    view.view_query = f"""
        SELECT
          DATE(timestamp) AS event_date,
          title,
          category,
          tier,
          AVG(
            COALESCE(twitch_viewers, 0) + COALESCE(youtube_viewers, 0)
          ) AS avg_total_viewers,
          MAX(
            COALESCE(twitch_viewers, 0) + COALESCE(youtube_viewers, 0)
          ) AS max_total_viewers,
          AVG(twitch_viewers) AS avg_twitch_viewers,
          AVG(youtube_viewers) AS avg_youtube_viewers,
          AVG(score) AS avg_score,
          COUNT(1) AS hourly_samples_count
        FROM `{table_id}`
        GROUP BY event_date, title, category, tier
    """
    try:
        client.get_table(view_id)
        # Update view query by recreating it
        client.delete_table(view_id)
        client.create_table(view, timeout=30)
        logger.info(f"Updated BigQuery view {view_id}")
    except Exception:
        try:
            client.create_table(view, timeout=30)
            logger.info(f"Created BigQuery view {view_id}")
        except Exception as e:
            logger.error(f"Failed to create BigQuery view {view_id}: {e}")


def upgrade_bigquery_constraints(bq_client) -> None:
    """Attempts to apply Primary Key and Foreign Key constraints to BigQuery tables.
    Since constraints are not enforced, these are metadata declarations used by
    BigQuery for query optimizations and doc schemas.
    """
    project = bq_client.project
    dataset = "streamer_metrics"

    # 1. Add Primary Key to streamer_profile_fabric
    try:
        query = f"""
            ALTER TABLE `{project}.{dataset}.streamer_profile_fabric`
            ADD PRIMARY KEY (streamer_handle) NOT ENFORCED;
        """
        bq_client.query(query).result()
        logger.info("Successfully added PRIMARY KEY to streamer_profile_fabric.")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("PRIMARY KEY on streamer_profile_fabric already exists.")
        else:
            logger.warning(f"Note: Could not add PRIMARY KEY constraint: {e}")

    # 2. Add Foreign Key to streamer_analytics_timeseries
    try:
        query = f"""
            ALTER TABLE `{project}.{dataset}.streamer_analytics_timeseries`
            ADD CONSTRAINT fk_analytics_streamer
            FOREIGN KEY (streamer_handle)
            REFERENCES `{project}.{dataset}.streamer_profile_fabric`
              (streamer_handle) NOT ENFORCED;
        """
        bq_client.query(query).result()
        logger.info("Successfully added FOREIGN KEY to streamer_analytics_timeseries.")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("FOREIGN KEY fk_analytics_streamer already exists.")
        else:
            logger.warning(
                f"Note: Could not add FOREIGN KEY fk_analytics_streamer: {e}"
            )

    # 3. Add Foreign Key to sentiment_history
    try:
        query = f"""
            ALTER TABLE `{project}.{dataset}.sentiment_history`
            ADD CONSTRAINT fk_sentiment_streamer
            FOREIGN KEY (streamer_handle)
            REFERENCES `{project}.{dataset}.streamer_profile_fabric`
              (streamer_handle) NOT ENFORCED;
        """
        bq_client.query(query).result()
        logger.info("Successfully added FOREIGN KEY to sentiment_history.")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("FOREIGN KEY fk_sentiment_streamer already exists.")
        else:
            logger.warning(
                f"Note: Could not add FOREIGN KEY fk_sentiment_streamer: {e}"
            )

    # 4. Add Foreign Keys to streamer_similarity_history
    try:
        query = f"""
            ALTER TABLE `{project}.{dataset}.streamer_similarity_history`
            ADD CONSTRAINT fk_similarity_streamer_a
            FOREIGN KEY (streamer_a)
            REFERENCES `{project}.{dataset}.streamer_profile_fabric`
              (streamer_handle) NOT ENFORCED;
        """
        bq_client.query(query).result()
        logger.info("Successfully added FOREIGN KEY fk_similarity_streamer_a.")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("FOREIGN KEY fk_similarity_streamer_a already exists.")
        else:
            logger.warning(
                f"Note: Could not add FOREIGN KEY fk_similarity_streamer_a: {e}"
            )

    try:
        query = f"""
            ALTER TABLE `{project}.{dataset}.streamer_similarity_history`
            ADD CONSTRAINT fk_similarity_streamer_b
            FOREIGN KEY (streamer_b)
            REFERENCES `{project}.{dataset}.streamer_profile_fabric`
              (streamer_handle) NOT ENFORCED;
        """
        bq_client.query(query).result()
        logger.info("Successfully added FOREIGN KEY fk_similarity_streamer_b.")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("FOREIGN KEY fk_similarity_streamer_b already exists.")
        else:
            logger.warning(
                f"Note: Could not add FOREIGN KEY fk_similarity_streamer_b: {e}"
            )
