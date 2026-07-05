import json
import logging
import os

logger = logging.getLogger("streamer_advisor.scraper")

CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache.json")
_CACHE_LOCK_FILE = CACHE_FILE + ".lock"

_MODELS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "models.json")


def load_model_config() -> dict:
    """Loads the externalized model config from models.json.

    Returns a dict with keys: default_model, report_model, fallback_chain, timeouts.
    Reads from disk dynamically to support hot-reloading.
    """
    try:
        with open(_MODELS_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config
    except Exception as e:
        logger.warning(f"Failed to load models.json ({e}), using built-in defaults.")
        return {
            "default_model": "gemma-4-26b-a4b-it",
            "report_model": "gemini-3.5-flash",
            "report_chain": [
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-3.1-flash-lite",
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
            ],
            "default_chain": [
                "gemma-4-26b-a4b-it",
                "gemma-4-31b-it",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-3.1-flash-lite",
            ],
            "timeouts": {
                "gemini-3.5-flash": 120,
                "gemini-2.5-flash": 120,
                "gemini-3.1-flash-lite": 120,
                "gemma-4-31b-it": 300,
                "gemma-4-26b-a4b-it": 300,
            },
        }


def get_model_timeout(model_name: str) -> float:
    """Returns the configured timeout for a model, defaulting to 120s for
    unknown models."""
    config = load_model_config()
    return float(config.get("timeouts", {}).get(model_name, 120))


# ---------------------------------------------------------------------------
# Google GenAI SDK client — initialized lazily with HTTP/2 transport
# ---------------------------------------------------------------------------
