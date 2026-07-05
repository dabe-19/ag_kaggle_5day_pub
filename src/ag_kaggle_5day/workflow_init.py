import asyncio
import itertools
import logging
import threading

from google.genai._interactions.resources.interactions import (
    AsyncInteractionsResource,
    InteractionsResource,
)
from google.genai.errors import APIError, ServerError
from google.genai.models import AsyncModels, Models

logger = logging.getLogger("streamer_advisor.workflow_init")

# Monkeypatch original GenAI SDK methods to intercept, retry, and fall back
_orig_generate_content = Models.generate_content
_orig_async_generate_content = AsyncModels.generate_content
_orig_interactions_create = InteractionsResource.create
_orig_async_interactions_create = AsyncInteractionsResource.create

# Thread-safe counter to alternate primary and secondary models across successive calls
_call_counter = itertools.count()

# Thread-safe global cache for thought signatures to bridge ADK compatibility gap
_thought_signatures_cache = {}
_cache_lock = threading.Lock()


def get_next_call_index() -> int:
    return next(_call_counter)


def should_retry(e: Exception) -> bool:
    """Returns True if the exception is a transient or rate-limiting API error."""
    if isinstance(e, ServerError):
        return True
    if isinstance(e, APIError):
        if e.code == 429:
            return True
        err_str = str(e).lower()
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            return True
    return False


def cache_thought_signatures(response) -> None:
    """Caches thought signatures from a GenerateContentResponse."""
    if not response or not hasattr(response, "candidates") or not response.candidates:
        return
    for candidate in response.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.function_call and part.thought_signature:
                    key = (part.function_call.name, str(part.function_call.args))
                    with _cache_lock:
                        if len(_thought_signatures_cache) > 1000:
                            _thought_signatures_cache.clear()
                        _thought_signatures_cache[key] = part.thought_signature


def restore_thought_signatures(contents) -> None:
    """Restores missing thought signatures in the conversation history."""
    if not contents:
        return
    contents_list = contents if isinstance(contents, list) else [contents]
    for content in contents_list:
        if not hasattr(content, "parts") or not content.parts:
            continue
        for part in content.parts:
            if part.function_call and not part.thought_signature:
                key = (part.function_call.name, str(part.function_call.args))
                with _cache_lock:
                    sig = _thought_signatures_cache.get(key)
                if sig:
                    part.thought_signature = sig


def get_fallback_models(requested_model: str) -> list[str]:
    """Resolves the fallback model chain from models.json default_chain."""
    # Resolve actual model string if ADK wrapped object
    if not isinstance(requested_model, str) and requested_model is not None:
        if hasattr(requested_model, "model"):
            requested_model = requested_model.model
        elif hasattr(requested_model, "value"):
            requested_model = requested_model.value

    try:
        from ag_kaggle_5day.agents.scraper.config import load_model_config

        config = load_model_config()
        chain = config.get("default_chain", [])
    except Exception as e:
        logger.warning(f"Failed to load fallback chain from config: {e}")
        chain = [
            "gemma-4-26b-a4b-it",
            "gemma-4-31b-it",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
        ]

    # Standardize to string
    req_model_str = str(requested_model).strip()
    if "Omit" in req_model_str or not req_model_str:
        return chain

    # If the requested model is already in the chain, we try it first,
    # followed by the remaining models in the chain.
    if req_model_str in chain:
        idx = chain.index(req_model_str)
        models = [req_model_str] + [m for m in chain[idx + 1 :] if m != req_model_str]
    else:
        models = [req_model_str] + [m for m in chain if m != req_model_str]

    # Swap the first two models on alternating calls to balance API rate limits
    if len(models) >= 2:
        call_idx = get_next_call_index()
        if call_idx % 2 == 1:
            models[0], models[1] = models[1], models[0]

    return models


def log_request_details(model: str, contents) -> None:
    """Logs details of the outgoing GenAI request for monitoring."""
    try:
        req_desc = []
        if contents:
            contents_list = contents if isinstance(contents, list) else [contents]
            for content in contents_list:
                role = getattr(content, "role", "user") or "user"
                if getattr(content, "parts", None):
                    for part in content.parts:
                        if getattr(part, "text", None):
                            # Truncate long prompts for readability in logs
                            txt = part.text
                            if len(txt) > 200:
                                txt = txt[:197] + "..."
                            req_desc.append(f"[{role}]: {txt}")
                        elif getattr(part, "function_call", None):
                            req_desc.append(
                                f"[{role} Call]: {part.function_call.name}"
                                f"({part.function_call.args})"
                            )
                        elif getattr(part, "function_response", None):
                            resp_val = str(part.function_response.response)
                            if len(resp_val) > 200:
                                resp_val = resp_val[:197] + "..."
                            req_desc.append(
                                f"[{role} Response]: {part.function_response.name} "
                                f"-> {resp_val}"
                            )
        logger.info(f"Sending Request to model '{model}':\n" + "\n".join(req_desc))
    except Exception as e:
        logger.debug(f"Failed to log request details: {e}")


def log_response_details(model: str, response) -> None:
    """Logs details of the incoming GenAI response for monitoring."""
    try:
        resp_desc = []
        if response and getattr(response, "candidates", None):
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if getattr(part, "text", None):
                            txt = part.text
                            if len(txt) > 200:
                                txt = txt[:197] + "..."
                            resp_desc.append(f"[model]: {txt}")
                        elif getattr(part, "function_call", None):
                            resp_desc.append(
                                f"[model Call]: {part.function_call.name}"
                                f"({part.function_call.args})"
                            )
        logger.info(f"Response from model '{model}':\n" + "\n".join(resp_desc))
    except Exception as e:
        logger.debug(f"Failed to log response details: {e}")


def patched_generate_content(self, model: str, contents, config=None, **kwargs):
    restore_thought_signatures(contents)
    models_to_try = get_fallback_models(model)
    last_err = None

    for target_model in models_to_try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log_request_details(target_model, contents)
                res = _orig_generate_content(
                    self,
                    model=target_model,
                    contents=contents,
                    config=config,
                    **kwargs,
                )
                log_response_details(target_model, res)
                cache_thought_signatures(res)
                return res
            except APIError as e:
                last_err = e
                if should_retry(e):
                    wait_time = (2**attempt) + 0.5
                    logger.warning(
                        f"GenAI SDK Patched: APIError {e.code} on model "
                        f"'{target_model}' (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    import time

                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"GenAI SDK Patched: Non-retryable error {e.code} on "
                        f"'{target_model}'. Advancing to next fallback..."
                    )
                    break
        else:
            # If the retry loop completed without breaking, it failed all retries
            logger.warning(
                f"GenAI SDK Patched: Model '{target_model}' failed all retries."
            )

    raise last_err


async def patched_async_generate_content(
    self, model: str, contents, config=None, **kwargs
):
    restore_thought_signatures(contents)
    models_to_try = get_fallback_models(model)
    last_err = None

    for target_model in models_to_try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log_request_details(target_model, contents)
                res = await _orig_async_generate_content(
                    self,
                    model=target_model,
                    contents=contents,
                    config=config,
                    **kwargs,
                )
                log_response_details(target_model, res)
                cache_thought_signatures(res)
                return res
            except APIError as e:
                last_err = e
                if should_retry(e):
                    wait_time = (2**attempt) + 0.5
                    logger.warning(
                        f"GenAI SDK Patched: APIError {e.code} on model "
                        f"'{target_model}' (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(
                        f"GenAI SDK Patched: Non-retryable error {e.code} on "
                        f"'{target_model}'. Advancing to next fallback..."
                    )
                    break
        else:
            logger.warning(
                f"GenAI SDK Patched: Model '{target_model}' failed all retries."
            )

    raise last_err


def patched_interactions_create(self, *args, **kwargs):
    # Extract model from kwargs or args
    model = kwargs.get("model")
    if not model and len(args) > 0:
        model = args[0]

    # Resolve actual model string if ADK wrapped object
    if not isinstance(model, str) and model is not None:
        if hasattr(model, "model"):
            model = model.model
        elif hasattr(model, "value"):
            model = model.value

    models_to_try = get_fallback_models(model)
    last_err = None

    for target_model in models_to_try:
        call_kwargs = kwargs.copy()
        call_kwargs["model"] = target_model

        max_retries = 3
        for attempt in range(max_retries):
            try:
                return _orig_interactions_create(self, *args, **call_kwargs)
            except APIError as e:
                last_err = e
                if should_retry(e):
                    wait_time = (2**attempt) + 0.5
                    logger.warning(
                        f"GenAI SDK Interactions Patched: APIError {e.code} on model "
                        f"'{target_model}' (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    import time

                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"GenAI SDK Interactions Patched: Non-retryable error "
                        f"{e.code} on '{target_model}'. Advancing to next fallback..."
                    )
                    break
        else:
            logger.warning(
                f"GenAI SDK Interactions Patched: Model '{target_model}' "
                "failed all retries."
            )

    raise last_err


async def patched_async_interactions_create(self, *args, **kwargs):
    # Extract model from kwargs or args
    model = kwargs.get("model")
    if not model and len(args) > 0:
        model = args[0]

    # Resolve actual model string if ADK wrapped object
    if not isinstance(model, str) and model is not None:
        if hasattr(model, "model"):
            model = model.model
        elif hasattr(model, "value"):
            model = model.value

    models_to_try = get_fallback_models(model)
    last_err = None

    for target_model in models_to_try:
        call_kwargs = kwargs.copy()
        call_kwargs["model"] = target_model

        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await _orig_async_interactions_create(self, *args, **call_kwargs)
            except APIError as e:
                last_err = e
                if should_retry(e):
                    wait_time = (2**attempt) + 0.5
                    logger.warning(
                        f"GenAI SDK Interactions Patched: APIError {e.code} on model "
                        f"'{target_model}' (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(
                        f"GenAI SDK Interactions Patched: Non-retryable error "
                        f"{e.code} on '{target_model}'. Advancing to next fallback..."
                    )
                    break
        else:
            logger.warning(
                f"GenAI SDK Interactions Patched: Model '{target_model}' "
                "failed all retries."
            )

    raise last_err


Models.generate_content = patched_generate_content
AsyncModels.generate_content = patched_async_generate_content
InteractionsResource.create = patched_interactions_create
AsyncInteractionsResource.create = patched_async_interactions_create

logger.info(
    "Successfully monkeypatched google-genai SDK Models and Interactions "
    "to handle, retry, and fall back on ServerError 500."
)

advisor_runner = None
comparative_report_workflow = None
stream_playbook_workflow = None

try:
    from google.adk.runners import InMemoryRunner

    from ag_kaggle_5day.advisor_agent.agent import app as advisor_app

    advisor_runner = InMemoryRunner(app=advisor_app)
except Exception as e:
    logger.error(f"Failed to initialize ADK advisor runner: {e}")
