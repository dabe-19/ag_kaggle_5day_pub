from __future__ import annotations

import logging
import os

logger = logging.getLogger("streamer_advisor.gcp_storage")


def get_embedding(text: str, api_key: str) -> list[float]:
    """Generates text embedding using standard Google GenAI SDK
    and gemini-embedding-001 with 768 dimensions.

    Supports automatic retry with GEMINI_API_KEY_BACKUP if the primary key
    is rate-limited (HTTP 429 / RESOURCE_EXHAUSTED).
    """

    from google.genai import types as genai_types

    from ag_kaggle_5day.agents.scraper import _get_genai_client

    client = _get_genai_client(api_key)
    try:
        res = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=genai_types.EmbedContentConfig(output_dimensionality=768),
        )
        if hasattr(res, "embeddings") and res.embeddings:
            return res.embeddings[0].values
        elif hasattr(res, "embedding") and res.embedding:
            return res.embedding.values
        else:
            raise ValueError("Unexpected response structure from embed_content")
    except Exception as e:
        err_str = str(e).upper()
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            backup_1 = (
                os.environ.get("GEMINI_API_KEY_BACKUP", "")
                .strip()
                .strip('"')
                .strip("'")
            )
            backup_2 = (
                os.environ.get("GEMINI_API_KEY_TERTIARY", "")
                .strip()
                .strip('"')
                .strip("'")
            )
            backups = [b for b in [backup_1, backup_2] if b and b != api_key]

            for backup_key in backups:
                logger.warning(
                    "Primary Gemini API key rate-limited during embedding. "
                    "Retrying request with fallback key..."
                )
                try:
                    backup_client = _get_genai_client(backup_key)
                    res = backup_client.models.embed_content(
                        model="gemini-embedding-001",
                        contents=text,
                        config=genai_types.EmbedContentConfig(
                            output_dimensionality=768
                        ),
                    )
                    if hasattr(res, "embeddings") and res.embeddings:
                        return res.embeddings[0].values
                    elif hasattr(res, "embedding") and res.embedding:
                        return res.embedding.values
                    else:
                        raise ValueError(
                            "Unexpected response structure from backup embed_content"
                        )
                except Exception as backup_err:
                    logger.error(
                        f"Fallback Gemini API key failed for embedding: {backup_err}"
                    )
        logger.error(f"Failed to generate embedding for text: {e}")
        raise


def get_embeddings_batch(texts: list[str], api_key: str) -> list[list[float]]:
    """Generates text embeddings in batch using standard Google GenAI SDK
    and gemini-embedding-001 with 768 dimensions.

    Supports automatic retry with GEMINI_API_KEY_BACKUP if the primary key
    is rate-limited (HTTP 429 / RESOURCE_EXHAUSTED).
    """
    if not texts:
        return []

    from google.genai import types as genai_types

    from ag_kaggle_5day.agents.scraper import _get_genai_client

    client = _get_genai_client(api_key)
    try:
        res = client.models.embed_content(
            model="gemini-embedding-001",
            contents=texts,
            config=genai_types.EmbedContentConfig(output_dimensionality=768),
        )
        if hasattr(res, "embeddings") and res.embeddings:
            return [emb.values for emb in res.embeddings]
        else:
            raise ValueError("Unexpected response structure from embed_content batch")
    except Exception as e:
        err_str = str(e).upper()
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            backup_1 = (
                os.environ.get("GEMINI_API_KEY_BACKUP", "")
                .strip()
                .strip('"')
                .strip("'")
            )
            backup_2 = (
                os.environ.get("GEMINI_API_KEY_TERTIARY", "")
                .strip()
                .strip('"')
                .strip("'")
            )
            backups = [b for b in [backup_1, backup_2] if b and b != api_key]

            for backup_key in backups:
                logger.warning(
                    "Primary Gemini API key rate-limited during batch embedding. "
                    "Retrying request with fallback key..."
                )
                try:
                    backup_client = _get_genai_client(backup_key)
                    res = backup_client.models.embed_content(
                        model="gemini-embedding-001",
                        contents=texts,
                        config=genai_types.EmbedContentConfig(
                            output_dimensionality=768
                        ),
                    )
                    if hasattr(res, "embeddings") and res.embeddings:
                        return [emb.values for emb in res.embeddings]
                except Exception as backup_err:
                    logger.error(
                        "Fallback Gemini API key failed for batch "
                        f"embedding: {backup_err}"
                    )
        logger.error(f"Failed to generate batch embeddings: {e}")
        return []
