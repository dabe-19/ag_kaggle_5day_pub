from __future__ import annotations

import logging
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger("streamer_advisor.gcp_storage")

try:
    from google.cloud.firestore_v1.vector import Vector
except ImportError:
    Vector = None

try:
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
except ImportError:

    class DistanceMeasure:
        COSINE = "COSINE"
        EUCLIDEAN = "EUCLIDEAN"
        DOT_PRODUCT = "DOT_PRODUCT"


def store_playbook_vector(playbook: dict, text_content: str, api_key: str) -> None:
    """Generates embedding using gemini-embedding-001 (768 dimensions)
    and saves to Firestore 'playbooks' collection.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_embedding, get_firestore_client

    client = get_firestore_client()
    if not client:
        logger.warning(
            "Firestore client not available. Skipping storing playbook vector."
        )
        return

    try:
        embedding = get_embedding(text_content, api_key)
        if not embedding:
            logger.warning("Failed to generate embedding. Skipping playbook save.")
            return

        doc_data = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "game": playbook.get("game"),
            "category": playbook.get("category"),
            "platform": playbook.get("platform"),
            "hook": playbook.get("hook"),
            "advice": playbook.get("advice"),
            "text_content": text_content,
            "embedding": Vector(embedding) if Vector else embedding,
            "stream_goal": playbook.get("stream_goal"),
            "generated_at": playbook.get("generated_at"),
            "formatted_time": playbook.get("formatted_time"),
            "twitch_viewers": playbook.get("twitch_viewers"),
            "youtube_viewers": playbook.get("youtube_viewers"),
            "total_viewers": playbook.get("total_viewers"),
            "news_snapshot": playbook.get("news", []),
        }

        client.collection("playbooks").add(doc_data)
        logger.info(
            "Successfully stored playbook vector in Firestore for game "
            f"'{playbook.get('game')}'"
        )
    except Exception as e:
        logger.error(f"Error storing playbook vector in Firestore: {e}", exc_info=True)


def search_similar_playbooks(query: str, api_key: str, limit: int = 3) -> list[dict]:
    """Retrieves similar past playbooks from Firestore using kNN vector search."""
    from ag_kaggle_5day.agents.gcp_storage import get_embedding, get_firestore_client

    client = get_firestore_client()
    if not client:
        logger.warning("Firestore client not available. Skipping vector search.")
        return []

    try:
        query_embedding = get_embedding(query, api_key)
        if not query_embedding:
            logger.warning("Failed to generate embedding for query.")
            return []

        collection = client.collection("playbooks")
        vector_query = collection.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding) if Vector else query_embedding,
            distance_measure=DistanceMeasure.COSINE,
            limit=limit,
        )

        results = []
        for doc in vector_query.stream():
            data = doc.to_dict()
            data.pop("embedding", None)
            if "timestamp" in data and hasattr(data["timestamp"], "isoformat"):
                data["timestamp"] = data["timestamp"].isoformat()
            results.append(data)

        logger.info(
            f"Firestore vector search returned {len(results)} matches "
            f"for query '{query}'"
        )
        return results
    except Exception as e:
        logger.error(
            f"Error searching similar playbooks in Firestore: {e}", exc_info=True
        )
        if "FAILED_PRECONDITION" in str(e) or "index" in str(e).lower():
            logger.warning(
                "A Firestore Vector Index is required. You can create it with:\n"
                "gcloud alpha firestore indexes composite create "
                "--collection-group=playbooks --query-scope=COLLECTION "
                "--field-config=vector-config="
                '\'{"dimension":"768","flat":{}}\',field-path=embedding'
            )
        return []


def store_comparison_report_vector(
    report_html: str, custom_games: list[str], api_key: str
) -> None:
    """Generates embedding for a comparison report (disabled/deprecated)"""
    logger.info(
        "store_comparison_report_vector: Storing comparison report vectors is disabled."
    )
    return


def store_news_vector(
    game: str,
    headline: str,
    summary: str,
    url: str,
    api_key: str,
    embedding: Optional[list[float]] = None,
) -> None:
    """Generates embedding for a news article (if not pre-computed)
    and saves to Firestore 'news_articles' collection.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_embedding, get_firestore_client

    client = get_firestore_client()
    if not client:
        logger.warning(
            "Firestore client not available. Skipping storing news article vector."
        )
        return

    try:
        text_content = f"Game: {game}. Headline: {headline}. Summary: {summary}"

        # Check if this article already exists to prevent duplicate entries
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            duplicates = (
                client.collection("news_articles")
                .where(filter=FieldFilter("game", "==", game))
                .where(filter=FieldFilter("headline", "==", headline))
                .limit(1)
                .get()
            )
            if len(duplicates) > 0:
                logger.info(
                    f"News article '{headline}' for game '{game}' "
                    "already exists in Firestore. Skipping."
                )
                return
        except Exception as check_err:
            logger.warning(f"Error checking duplicates in Firestore: {check_err}")

        if not embedding:
            embedding = get_embedding(text_content, api_key)

        if not embedding:
            logger.warning(
                "Failed to generate embedding for news article. Skipping save."
            )
            return

        doc_data = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "game": game,
            "headline": headline,
            "summary": summary,
            "url": url,
            "text_content": text_content,
            "embedding": Vector(embedding) if Vector else embedding,
        }

        client.collection("news_articles").add(doc_data)
        logger.info(
            f"Successfully stored news article vector in Firestore for game '{game}'"
        )
    except Exception as e:
        logger.error(
            f"Error storing news article vector in Firestore: {e}", exc_info=True
        )


def search_similar_comparison_reports(
    query: str, api_key: str, limit: int = 3
) -> list[dict]:
    """Retrieves similar past comparison reports from Firestore
    (disabled/deprecated)."""
    logger.info(
        "search_similar_comparison_reports: "
        "Searching comparison report vectors is disabled."
    )
    return []


def search_similar_news(query: str, api_key: str, limit: int = 3) -> list[dict]:
    """Retrieves similar past news articles from Firestore using kNN vector search."""
    from ag_kaggle_5day.agents.gcp_storage import get_embedding, get_firestore_client

    client = get_firestore_client()
    if not client:
        logger.warning(
            "Firestore client not available. Skipping vector search for news."
        )
        return []

    try:
        query_embedding = get_embedding(query, api_key)
        if not query_embedding:
            logger.warning("Failed to generate embedding for query.")
            return []

        collection = client.collection("news_articles")
        vector_query = collection.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding) if Vector else query_embedding,
            distance_measure=DistanceMeasure.COSINE,
            limit=limit,
        )

        results = []
        for doc in vector_query.stream():
            data = doc.to_dict()
            data.pop("embedding", None)
            if "timestamp" in data and hasattr(data["timestamp"], "isoformat"):
                data["timestamp"] = data["timestamp"].isoformat()
            results.append(data)

        logger.info(
            f"Firestore news articles vector search returned {len(results)} "
            f"matches for query '{query}'"
        )
        return results
    except Exception as e:
        logger.error(f"Error searching similar news in Firestore: {e}", exc_info=True)
        if "FAILED_PRECONDITION" in str(e) or "index" in str(e).lower():
            logger.warning(
                "A Firestore Vector Index is required. You can create it with:\n"
                "gcloud alpha firestore indexes composite create "
                "--collection-group=news_articles --query-scope=COLLECTION "
                "--field-config=vector-config="
                '\'{"dimension":"768","flat":{}}\',field-path=embedding'
            )
        return []


def store_expose_article_vector(article: dict, text_content: str, api_key: str) -> None:
    """Generates embedding using gemini-embedding-001 and saves to Firestore
    'spotlight_expose_articles' collection for RAG searches.
    """
    from ag_kaggle_5day.agents.gcp_storage import get_embedding, get_firestore_client

    client = get_firestore_client()
    if not client:
        return

    embedding = None
    if api_key:
        try:
            embedding = get_embedding(text_content, api_key)
        except Exception as e:
            logger.warning(
                f"Failed to generate embedding for expose article: {e}. "
                "The article will be stored without a vector embedding."
            )

    try:
        import time

        doc_data = {
            "timestamp": time.time(),
            "streamer_handle": article.get("streamer_handle"),
            "title": article.get("title"),
            "content": article.get("content"),
            "associated_links": article.get("links"),
            "text_content": text_content,
        }
        if embedding is not None:
            doc_data["embedding"] = Vector(embedding) if Vector else embedding

        client.collection("spotlight_expose_articles").add(doc_data)
        logger.info(
            f"Successfully stored daily expose for {article.get('streamer_handle')}."
        )
    except Exception as e:
        logger.error(
            f"Error storing expose article in Firestore: {e}",
            exc_info=True,
        )
