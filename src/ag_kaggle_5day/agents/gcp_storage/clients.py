from __future__ import annotations

import logging
from typing import Optional

from google.cloud import bigquery, firestore

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


_bq_client: Optional[bigquery.Client] = None
_db_client: Optional[firestore.Client] = None


def get_bigquery_client() -> Optional[bigquery.Client]:
    """Returns a singleton BigQuery client, initialized lazily."""
    global _bq_client
    if _bq_client is not None:
        return _bq_client

    try:
        # Check if environment is configured or GCP credentials are present
        _bq_client = bigquery.Client()
        return _bq_client
    except Exception as e:
        logger.warning(
            f"Failed to initialize BigQuery client (local development fallback): {e}"
        )
        return None


def get_firestore_client() -> Optional[firestore.Client]:
    """Returns a singleton Firestore client, initialized lazily."""
    global _db_client
    if _db_client is not None:
        return _db_client

    try:
        _db_client = firestore.Client()
        return _db_client
    except Exception as e:
        logger.warning(
            f"Failed to initialize Firestore client (local development fallback): {e}"
        )
        return None
