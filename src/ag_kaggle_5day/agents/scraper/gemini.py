import json
import logging
import os
import random
import re
import time
from typing import Optional

import httpx
from google import genai
from google.genai import types as genai_types

from ag_kaggle_5day.agents.scraper.config import get_model_timeout

logger = logging.getLogger("streamer_advisor.scraper")

_client_cache: dict[tuple[str, int], genai.Client] = {}
_api_key_rotation_index = 0
_model_rotation_index = 0


def _get_genai_client(api_key: str, timeout_ms: int = 300_000) -> genai.Client:
    """Returns a cached google-genai SDK client, keyed by API key and timeout.

    Uses httpx HTTP/2 transport for better connection reuse and performance.
    The IPv4-preference system config in the Dockerfile (gai.conf) prevents
    the IPv6 ENETUNREACH issues that originally blocked SDK usage.
    """
    global _client_cache
    clean_key = (api_key or "").strip().strip('"').strip("'")
    cache_key = (clean_key, timeout_ms)
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    client = genai.Client(
        api_key=clean_key,
        http_options=genai_types.HttpOptions(
            timeout=timeout_ms,
        ),
    )
    _client_cache[cache_key] = client
    logger.info(f"Initialized google-genai SDK client with timeout {timeout_ms}ms.")
    return client


class _GeminiError(Exception):
    """Wraps a Gemini API error with a status code for abort logic."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"HTTP {code}: {message}")


class _SDKResponse:
    """Thin wrapper around the SDK response to expose a consistent .text interface."""

    def __init__(self, sdk_response):
        self._response = sdk_response

    @property
    def text(self) -> str:
        try:
            return self._response.text or ""
        except (AttributeError, ValueError):
            return ""


def safe_generate_content(
    api_key: str,
    model: Optional[str],
    contents: str,
    system_instruction: Optional[str] = None,
    use_google_search: bool = False,
    timeout: float = 180.0,
    chain_name: str = "default",
) -> _SDKResponse:
    """
    Generates content via the google-genai SDK with a sequential model fallback chain.

    The fallback chain and per-model timeouts are read from models.json config.
    Use chain_name='report' for comparison reports (Flash-first, quality-focused).
    Use chain_name='default' for news/chat/aggressive requests (Gemma-first, high RPD).

    Aborts immediately (without trying other models) on:
      - HTTP 403 (auth/key error)
      - Connection errors (network unreachable)

    On 429 (rate limit), falls through to the next model (per-model quota buckets).
    Retries the next model on HTTP 5xx or transient errors.
    """
    from ag_kaggle_5day.agents.scraper import _get_genai_client, load_model_config

    config = load_model_config()

    if chain_name == "report":
        primary = model or config.get("report_model", "gemini-3.5-flash")
        fallback_chain = config.get(
            "report_chain",
            [
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-3.1-flash-lite",
            ],
        )
    elif chain_name == "affiliate":
        primary = model or config.get("affiliate_model", "gemma-4-26b-a4b-it")
        fallback_chain = config.get(
            "affiliate_chain",
            [
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
            ],
        )
    elif chain_name == "expose":
        primary = model or config.get("expose_model", "gemini-3.5-flash")
        fallback_chain = config.get(
            "expose_chain",
            [
                "gemini-3.5-flash",
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
            ],
        )
    elif chain_name == "editor":
        primary = model or config.get("editor_model", "gemini-3.5-flash")
        fallback_chain = config.get(
            "editor_chain",
            [
                "gemma-4-31b-it",
                "gemini-3.5-flash",
                "gemma-4-26b-a4b-it",
            ],
        )
    elif chain_name == "refinement":
        primary = model or config.get("refinement_model", "gemini-3.5-flash")
        fallback_chain = config.get(
            "refinement_chain",
            [
                "gemini-3.5-flash",
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
            ],
        )
    elif chain_name == "sentiment":
        primary = model or config.get("sentiment_model", "gemma-4-31b-it")
        fallback_chain = config.get(
            "sentiment_chain",
            [
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
            ],
        )
    else:
        primary = model or config.get("default_model", "gemma-4-31b-it")
        fallback_chain = config.get(
            "default_chain",
            [
                "gemma-4-31b-it",
                "gemma-4-26b-a4b-it",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-3.1-flash-lite",
            ],
        )

    # Build attempt list: primary first, then remaining fallbacks in config order
    attempts = [primary] + [fb for fb in fallback_chain if fb != primary]

    # Rotate first two slots if they are both Gemma models
    if (
        len(attempts) >= 2
        and "gemma" in attempts[0].lower()
        and "gemma" in attempts[1].lower()
    ):
        global _model_rotation_index
        if _model_rotation_index % 2 == 1:
            attempts[0], attempts[1] = attempts[1], attempts[0]
        _model_rotation_index += 1

    # Load all unique keys and construct rotation pool

    backup_1 = os.environ.get("GEMINI_API_KEY_BACKUP", "").strip().strip('"').strip("'")
    backup_2 = (
        os.environ.get("GEMINI_API_KEY_TERTIARY", "").strip().strip('"').strip("'")
    )
    backup_3 = (
        os.environ.get("GEMINI_API_KEY_QUATERNARY", "").strip().strip('"').strip("'")
    )
    backup_4 = (
        os.environ.get("GEMINI_API_KEY_QUINARY", "").strip().strip('"').strip("'")
    )

    all_keys = []
    for k in [api_key, backup_1, backup_2, backup_3, backup_4]:
        if k and k not in all_keys:
            all_keys.append(k)

    global _api_key_rotation_index
    if not all_keys:
        chosen_key = api_key
        fallback_keys = []
        chosen_index = 0
    else:
        chosen_index = _api_key_rotation_index % len(all_keys)
        chosen_key = all_keys[chosen_index]
        _api_key_rotation_index += 1
        fallback_keys = [k for k in all_keys if k != chosen_key]

    last_err: Optional[Exception] = None
    for attempt_model in attempts:
        model_timeout = get_model_timeout(attempt_model)
        client = _get_genai_client(chosen_key, timeout_ms=int(model_timeout * 1000))

        max_retries = 3
        for retry_idx in range(max_retries):
            try:
                logger.info(
                    f"Attempting to generate content using model "
                    f"'{attempt_model}' (key index {chosen_index}, "
                    f"timeout={model_timeout}s, "
                    f"attempt {retry_idx + 1}/{max_retries})..."
                )

                # Build SDK config — timeout is set at client level (300s)
                gen_config = genai_types.GenerateContentConfig()

                # System instruction (supported by all models via SDK)
                if system_instruction:
                    gen_config.system_instruction = system_instruction

                # Google Search grounding tool - enable on Gemini and Gemma models
                # that support it
                if use_google_search and (
                    "gemini" in attempt_model.lower()
                    or "gemma" in attempt_model.lower()
                ):
                    gen_config.tools = [
                        genai_types.Tool(google_search=genai_types.GoogleSearch())
                    ]

                logger.debug(
                    f"Gemini API Call Details:\n"
                    f"- Model: {attempt_model}\n"
                    f"- System Instruction: {system_instruction}\n"
                    f"- Contents: {contents}"
                )
                response = client.models.generate_content(
                    model=attempt_model,
                    contents=contents,
                    config=gen_config,
                )
                try:
                    res_text = response.text or ""
                except Exception as read_err:
                    res_text = f"<unreadable response: {read_err}>"
                logger.debug(
                    f"Gemini API Response Details:\n"
                    f"- Model: {attempt_model}\n"
                    f"- Output: {res_text}"
                )
                return _SDKResponse(response)

            except genai.errors.ClientError as e:
                last_err = e
                err_str = str(e)
                # 429 = rate limit — try fallback keys sequentially (different
                # project/keys quota bucket)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    for backup_key in fallback_keys:
                        logger.warning(
                            f"Rate limit on '{attempt_model}' with active key. "
                            f"Retrying request with fallback key..."
                        )
                        try:
                            backup_client = _get_genai_client(
                                backup_key,
                                timeout_ms=int(model_timeout * 1000),
                            )
                            response = backup_client.models.generate_content(
                                model=attempt_model,
                                contents=contents,
                                config=gen_config,
                            )
                            return _SDKResponse(response)
                        except Exception as backup_err:
                            logger.warning(
                                f"Fallback key failed on '{attempt_model}': "
                                f"{backup_err}."
                            )

                    if retry_idx < max_retries - 1:
                        wait_time = (2**retry_idx) + random.uniform(0.1, 0.5)
                        logger.warning(
                            f"Rate limit on '{attempt_model}' "
                            f"(no fallback keys available). "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(
                            f"Rate limit on '{attempt_model}': {e}. "
                            f"Trying next model in fallback chain..."
                        )
                        break

                # 403 = auth/permission error — abort, no other model will work
                elif (
                    "403" in err_str
                    or "PERMISSION_DENIED" in err_str
                    or "API key not valid" in err_str
                    or "API_KEY_INVALID" in err_str
                ):
                    logger.error(
                        f"Gemini API auth/key error on '{attempt_model}': {e}. "
                        f"Aborting fallback chain."
                    )
                    raise _GeminiError(403, str(e))
                else:
                    logger.warning(
                        f"Client error on '{attempt_model}': {e}. "
                        f"Trying next fallback..."
                    )
                    break

            except genai.errors.ServerError as e:
                last_err = e
                # Try fallback keys first to bypass transient server load
                for backup_key in fallback_keys:
                    logger.warning(
                        f"Server error on '{attempt_model}' with active key. "
                        f"Retrying request with fallback key..."
                    )
                    try:
                        backup_client = _get_genai_client(
                            backup_key,
                            timeout_ms=int(model_timeout * 1000),
                        )
                        response = backup_client.models.generate_content(
                            model=attempt_model,
                            contents=contents,
                            config=gen_config,
                        )
                        return _SDKResponse(response)
                    except Exception as backup_err:
                        logger.warning(
                            f"Fallback key failed on '{attempt_model}': {backup_err}."
                        )

                if retry_idx < max_retries - 1:
                    wait_time = (2**retry_idx) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Server error on '{attempt_model}' "
                        f"(no fallback keys available). "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(
                        f"Server error on '{attempt_model}': {e}. "
                        f"Trying next fallback..."
                    )
                    break

            except (httpx.ConnectError, ConnectionError, OSError) as e:
                last_err = e
                logger.error(
                    f"Network connectivity error on '{attempt_model}': {e}. "
                    "Aborting fallback chain — check GEMINI_API_KEY and outbound HTTPS."
                )
                raise

            except Exception as e:
                last_err = e
                err_str = str(e)
                # Catch httpx timeout errors (read timeouts etc.)
                if "timed out" in err_str.lower() or "timeout" in err_str.lower():
                    if retry_idx < max_retries - 1:
                        wait_time = (2**retry_idx) + random.uniform(0.1, 0.5)
                        logger.warning(
                            f"Timeout on '{attempt_model}' after {model_timeout}s: "
                            f"{e}. Retrying in {wait_time:.2f}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(
                            f"Timeout on '{attempt_model}' after {model_timeout}s: "
                            f"{e}. Trying next fallback..."
                        )
                        break
                else:
                    logger.warning(
                        f"Failed on '{attempt_model}': {e}. Trying next fallback..."
                    )
                    break
    if last_err:
        err_str = str(last_err)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            raise _GeminiError(429, err_str)
        raise last_err
    raise RuntimeError("safe_generate_content: no models attempted")


def parse_json_response(text: str):
    """
    Cleans up markdown code fences (e.g. ```json ... ```) from a string
    and parses it as JSON.
    Uses a robust fallback parsing loop to handle leading/trailing
    conversational text containing brackets.
    """
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            text = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE
            ).strip()

    # Try parsing from each possible start index ([ or {) in the text
    last_err = None
    for match in re.finditer(r"[\[\{]", text):
        start_idx = match.start()
        sub_text = text[start_idx:]
        try:
            return json.loads(sub_text)
        except json.JSONDecodeError as e:
            if "Extra data" in str(e):
                try:
                    return json.loads(sub_text[: e.pos].strip())
                except Exception:
                    pass
            last_err = e

    # Fallback to direct json.loads if no bracket matches or loop failed
    if last_err:
        raise last_err
    return json.loads(text)


# ---------------------------------------------------------------------------
# Canonical game dict builder
# ---------------------------------------------------------------------------
