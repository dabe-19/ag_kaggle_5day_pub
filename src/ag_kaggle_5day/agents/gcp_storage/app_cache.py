from __future__ import annotations

import logging
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger("streamer_advisor.gcp_storage")


def store_app_cache_state(key: str, data: dict) -> None:
    """Persists serialized state data to a system_cache document in Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return
    try:
        client.collection("system_cache").document(key).set(
            {"data": data, "timestamp": firestore.SERVER_TIMESTAMP}
        )
        logger.info(
            f"Successfully stored system cache state for key '{key}' in Firestore."
        )
    except Exception as e:
        logger.error(f"Error storing system cache state for key '{key}': {e}")


def get_app_cache_state(key: str) -> Optional[dict]:
    """Retrieves state data from a system_cache document in Firestore."""
    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    client = get_firestore_client()
    if not client:
        return None
    try:
        doc = client.collection("system_cache").document(key).get()
        if doc.exists:
            val = doc.to_dict().get("data")
            if val is not None:
                return val
    except Exception as e:
        logger.error(f"Error getting system cache state for key '{key}': {e}")
    return None
