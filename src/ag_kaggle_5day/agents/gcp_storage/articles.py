from __future__ import annotations

import datetime
import logging
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger("streamer_advisor.gcp_storage")


def get_cached_medium_form_article(handle: str) -> Optional[dict]:
    """Retrieves a cached medium-form article from Firestore if less than 7 days old."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return None
    try:
        doc = (
            client.collection("spotlight_medium_articles")
            .document(handle.lower())
            .get()
        )
        if doc.exists:
            data = doc.to_dict()
            ts = data.get("timestamp")
            import time

            if ts and (time.time() - ts < 7 * 86400):
                return data
    except Exception as e:
        logger.error(f"Error getting cached medium-form article for {handle}: {e}")
    return None


def store_medium_form_article(handle: str, article: dict) -> None:
    """Stores a medium-form article in Firestore with the current timestamp."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return
    try:
        import time

        doc_data = {
            "streamer_handle": handle,
            "title": article.get("title"),
            "content": article.get("content"),
            "associated_links": article.get("links"),
            "timestamp": time.time(),
        }
        client.collection("spotlight_medium_articles").document(handle.lower()).set(
            doc_data
        )
        logger.info(
            f"Successfully cached medium-form article for {handle} in Firestore."
        )
    except Exception as e:
        logger.error(f"Error storing medium-form article for {handle}: {e}")


def get_latest_expose_article() -> Optional[dict]:
    """Retrieves the latest daily expose article from Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return None
    try:
        from google.cloud import firestore

        docs = (
            client.collection("spotlight_expose_articles")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for doc in docs:
            return doc.to_dict()
    except Exception as e:
        logger.error(f"Error getting latest expose article: {e}")
    return None


def get_expose_history() -> list[dict]:
    """Retrieves a list of historical expose articles (both daily exposes
    and user-generated medium-form articles) from Firestore,
    sorted by timestamp descending.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return []
    try:
        from google.cloud import firestore

        # 1. Fetch daily exposes
        expose_docs = (
            client.collection("spotlight_expose_articles")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(15)
            .stream()
        )
        history = []
        for doc in expose_docs:
            data = doc.to_dict()
            data.pop("embedding", None)
            data["type"] = "expose"
            history.append(data)

        # 2. Fetch medium-form articles
        medium_docs = (
            client.collection("spotlight_medium_articles")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(15)
            .stream()
        )
        for doc in medium_docs:
            data = doc.to_dict()
            data["type"] = "medium-form"
            history.append(data)

        # Sort combined list by timestamp descending
        history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return history[:20]
    except Exception as e:
        logger.error(f"Error getting expose history: {e}")
    return []


def get_historical_expose_context(handle: str, api_key: str, limit: int = 3) -> str:
    """Retrieves past exposes and medium form articles for the streamer
    and tangentially related streamers, and formats it as context.
    """
    from ag_kaggle_5day.agents.gcp_storage import (
        get_embedding,
        get_firestore_client,
    )

    client = get_firestore_client()
    if not client:
        return ""

    context_pieces = []
    seen_ids = set()

    # 1. Exact match for the streamer themselves (medium articles)
    try:
        doc = (
            client.collection("spotlight_medium_articles")
            .document(handle.lower())
            .get()
        )
        if doc.exists:
            data = doc.to_dict()
            title = data.get("title", "")
            content = data.get("content", "")
            # Strip HTML tags from content for embedding context
            import re

            clean_content = re.sub("<[^<]+?>", "", content)
            context_pieces.append(
                f"PAST MEDIUM-FORM ARTICLE FOR {handle.upper()}:\n"
                f"Title: {title}\n"
                f"Content Summary: {clean_content[:1500]}\n"
            )
    except Exception as e:
        logger.warning(f"Error reading past medium article for {handle}: {e}")

    # 2. Exact matches in spotlight_expose_articles
    try:
        from google.cloud import firestore

        docs = (
            client.collection("spotlight_expose_articles")
            .where("streamer_handle", "==", handle.lower())
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(2)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            doc_id = doc.id
            seen_ids.add(doc_id)
            title = data.get("title", "")
            text_content = data.get("text_content") or data.get("content", "")
            import re

            clean_content = re.sub("<[^<]+?>", "", text_content)
            context_pieces.append(
                f"PAST LONG-FORM EXPOSE FOR {handle.upper()}:\n"
                f"Title: {title}\n"
                f"Content Summary: {clean_content[:1500]}\n"
            )
    except Exception as e:
        logger.warning(f"Error reading past exposes for {handle}: {e}")

    # 3. Vector search for tangentially related streamers (sharing games/co-streamers)
    if api_key:
        try:
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

            # Formulate a query to find similar/tangential exposes
            query_str = (
                "Streamer profile research, gameplay, co-streamers, "
                f"and games played by {handle}"
            )
            embedding = get_embedding(query_str, api_key)

            coll = client.collection("spotlight_expose_articles")
            vector_query = coll.find_nearest(
                vector_field="embedding",
                query_vector=embedding,
                distance_measure=DistanceMeasure.COSINE,
                limit=limit + 2,  # fetch a few more in case of overlap
            )

            tangent_count = 0
            for doc in vector_query.stream():
                if doc.id in seen_ids:
                    continue
                data = doc.to_dict()
                other_handle = data.get("streamer_handle", "")
                if not other_handle or other_handle.lower() == handle.lower():
                    continue

                title = data.get("title", "")
                text_content = data.get("text_content") or data.get("content", "")
                import re

                clean_content = re.sub("<[^<]+?>", "", text_content)
                context_pieces.append(
                    f"TANGENTIALLY RELATED EXPOSE "
                    f"({other_handle.upper()} - shared games/vibe):\n"
                    f"Title: {title}\n"
                    f"Content Summary: {clean_content[:1000]}\n"
                )
                tangent_count += 1
                if tangent_count >= limit:
                    break
        except Exception as e:
            logger.warning(f"Error doing vector search for related exposes: {e}")

    if not context_pieces:
        return ""

    return (
        "\n=== RELATED HISTORICAL EXPOSES & CONTEXT ===\n"
        + "\n".join(context_pieces)
        + "\n============================================\n"
    )


def poll_past_week_streamers_from_bq() -> list[str]:
    """Polls the past week's list of streamers logged in BigQuery."""
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    client = get_bigquery_client()
    if not client:
        # Fallback to local cache if BQ is disabled (development mode)
        from ag_kaggle_5day.agents.advisor import get_cached_games

        games = get_cached_games()
        streamers = set()
        for g in games:
            for s in g.get("top_streamers", []):
                if s.get("user_login"):
                    streamers.add(s.get("user_login"))
        return list(streamers)

    try:
        project = client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.hourly_stats"

        query = f"""
            SELECT DISTINCT LOWER(JSON_EXTRACT_SCALAR(s, '$.user_login')) as streamer
            FROM `{table_id}`,
            UNNEST(JSON_EXTRACT_ARRAY(top_streamers)) as s
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        """
        query_job = client.query(query, timeout=15)
        rows = list(query_job.result())
        streamers = [row.streamer for row in rows if row.streamer]
        return streamers
    except Exception as e:
        logger.warning(
            f"Failed to poll streamers from BigQuery: {e}. "
            "Falling back to startup cache."
        )
        from ag_kaggle_5day.agents.advisor import get_cached_games

        games = get_cached_games()
        streamers = set()
        for g in games:
            for s in g.get("top_streamers", []):
                if s.get("user_login"):
                    streamers.add(s.get("user_login"))
        return list(streamers)


def store_expose_candidates_to_bq(candidates: list[str], selected: str) -> None:
    """Stores the daily selections and chosen streamer of the day to BigQuery."""
    from ag_kaggle_5day.agents.gcp_storage import get_bigquery_client

    client = get_bigquery_client()
    if not client:
        logger.warning("BigQuery client not available. Skipping candidates save.")
        return

    try:
        project = client.project
        dataset_id = f"{project}.streamer_metrics"
        table_id = f"{dataset_id}.expose_candidates"

        try:
            client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            client.create_dataset(dataset, timeout=30)

        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("candidate_streamers", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("selected_streamer", "STRING", mode="REQUIRED"),
        ]

        try:
            client.get_table(table_id)
        except Exception:
            table = bigquery.Table(table_id, schema=schema)
            client.create_table(table, timeout=30)
            logger.info(f"Created BigQuery table {table_id}")

        import json

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {
            "timestamp": now_str,
            "candidate_streamers": json.dumps(candidates),
            "selected_streamer": selected,
        }
        errors = client.insert_rows_json(table_id, [row], timeout=30)
        if errors:
            logger.error(f"Failed to insert candidates into BigQuery: {errors}")
        else:
            logger.info(
                f"Saved expose candidates for selected streamer '{selected}' in BQ."
            )
    except Exception as e:
        logger.error(f"Exception saving expose candidates to BigQuery: {e}")
