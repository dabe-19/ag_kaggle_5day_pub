import inspect
import json
import logging
import os
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from google.adk.runners import InMemoryRunner

from ag_kaggle_5day.models import PlaybookRequest, RecommendRequest
from ag_kaggle_5day.security import (
    check_rate_limit,
    get_client_key,
    get_effective_key,
    playbook_limiter,
    recommend_limiter,
)

logger = logging.getLogger("streamer_advisor.routes.recommend")
router = APIRouter()

from ag_kaggle_5day.workflow_init import stream_playbook_workflow  # noqa: E402


def is_final_response_dict(event: dict) -> bool:
    """Helper to detect if a serialized remote event dict represents a final
    agent response.
    """
    actions = event.get("actions", {})
    skip_sum = False
    if hasattr(actions, "skip_summarization"):
        skip_sum = getattr(actions, "skip_summarization", False)
    elif isinstance(actions, dict):
        skip_sum = actions.get("skip_summarization", False)

    long_running = event.get("long_running_tool_ids")
    if skip_sum or long_running:
        return True

    content = event.get("content")
    if content:
        parts = content.get("parts", [])
        for p in parts:
            if (
                p.get("function_call")
                or p.get("function_call_config")
                or p.get("function_response")
            ):
                return False
            if p.get("code_execution_result"):
                return False

    partial = event.get("partial", False)
    if partial:
        return False

    return True


def extract_chat_response_and_trace(events: list) -> tuple[str, str]:
    """Processes a list of events (either remote dicts or local Event objects)
    and separates the final user-facing response from the intermediate reasoning trace.
    """
    final_texts = []
    reasoning_lines = []

    for event in events:
        is_dict = isinstance(event, dict)
        author = event.get("author", "") if is_dict else getattr(event, "author", "")
        if author == "user":
            continue

        is_final = False
        if is_dict:
            is_final = is_final_response_dict(event)
        else:
            try:
                is_final = event.is_final_response()
            except Exception:
                is_final = True

        content = event.get("content") if is_dict else getattr(event, "content", None)
        parts = []
        if content:
            if is_dict:
                parts = content.get("parts", [])
            else:
                parts = content.parts or []

        for p in parts:
            part_text = p.get("text") if is_dict else getattr(p, "text", None)
            func_call = (
                p.get("function_call") if is_dict else getattr(p, "function_call", None)
            )
            func_resp = (
                p.get("function_response")
                if is_dict
                else getattr(p, "function_response", None)
            )

            if part_text:
                if is_final:
                    final_texts.append(part_text)
                else:
                    reasoning_lines.append(f"Thought: {part_text.strip()}")
            elif func_call:
                call_dict = (
                    func_call
                    if is_dict
                    else func_call.model_dump()
                    if hasattr(func_call, "model_dump")
                    else str(func_call)
                )
                if isinstance(call_dict, dict):
                    name = call_dict.get("name", "unknown")
                    args = call_dict.get("args", {})
                    reasoning_lines.append(
                        f"🛠️ Tool Call: `{name}` with arguments `{args}`"
                    )
                else:
                    reasoning_lines.append(f"🛠️ Tool Call: {call_dict}")
            elif func_resp:
                resp_dict = (
                    func_resp
                    if is_dict
                    else func_resp.model_dump()
                    if hasattr(func_resp, "model_dump")
                    else str(func_resp)
                )
                if isinstance(resp_dict, dict):
                    name = resp_dict.get("name", "unknown")
                    resp = resp_dict.get("response", {})
                    reasoning_lines.append(
                        f"📋 Tool Result: `{name}` returned `{resp}`"
                    )
                else:
                    reasoning_lines.append(f"📋 Tool Result: {resp_dict}")

    recommendation = "".join(final_texts).strip()
    reasoning_trace = "\n".join(reasoning_lines).strip()

    if not recommendation:
        last_agent_parts = []
        for event in reversed(events):
            is_d = isinstance(event, dict)
            auth = event.get("author", "") if is_d else getattr(event, "author", "")
            if auth != "user":
                cont = event.get("content") if is_d else getattr(event, "content", None)
                if cont:
                    pts = cont.get("parts", []) if is_d else cont.parts or []
                    for pt in pts:
                        t = pt.get("text") if is_d else getattr(pt, "text", None)
                        if t:
                            last_agent_parts.append(t)
                if last_agent_parts:
                    break
        if last_agent_parts:
            recommendation = "".join(reversed(last_agent_parts)).strip()

    return recommendation, reasoning_trace


async def query_remote_agent(
    message: str,
    user_id: str,
    session_id: str,
    api_key: str,
    force_local: bool = False,
    model: str | None = None,
) -> tuple[str, str]:
    """Queries the remote Vertex AI Reasoning Engine using the execution client,
    collects the stream events, and returns the (recommendation, reasoning_trace) tuple.
    Falls back to local InMemoryRunner if remote execution fails.
    """
    engine_id = os.environ.get(
        "VERTEX_REASONING_ENGINE_PATH",
        os.environ.get("VERTEX_REASONING_ENGINE_ID", ""),
    )
    if not engine_id or force_local:
        if force_local:
            logger.info(
                "Client key is active (BYOK). "
                "Forcing local runner to protect user quota."
            )
        else:
            logger.info(
                "VERTEX_REASONING_ENGINE_PATH not configured. "
                "Failing fast to local runner."
            )
        from ag_kaggle_5day.app import advisor_runner

        if not advisor_runner:
            raise ValueError("Local advisor runner is not initialized.")

        # Execute locally
        orig_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = api_key

        # Override agent models to use the user's selected model (from header)
        if model:
            try:
                from google.adk.models import Gemini

                from ag_kaggle_5day.advisor_agent.agent import (
                    constellation_analyst,
                    expose_selector_agent,
                    expose_writer_agent,
                    root_agent,
                    saturation_scout,
                    strategy_planner,
                    streamer_research_agent,
                )

                resolved_model = (
                    Gemini(model=model) if "gemma-4" in model.lower() else model
                )
                for agent in [
                    saturation_scout,
                    streamer_research_agent,
                    expose_selector_agent,
                    expose_writer_agent,
                    constellation_analyst,
                    strategy_planner,
                    root_agent,
                ]:
                    agent.model = resolved_model
            except Exception as e:
                logger.warning(f"Failed to override agent models to {model}: {e}")

        try:
            events = await advisor_runner.run_debug(
                message,
                user_id=user_id,
                session_id=session_id,
                quiet=True,
            )
            return extract_chat_response_and_trace(events)
        finally:
            if orig_key is not None:
                os.environ["GEMINI_API_KEY"] = orig_key
            else:
                os.environ.pop("GEMINI_API_KEY", None)

    logger.info("Attempting remote Vertex AI Reasoning Engine query...")
    try:
        import anyio
        from google.cloud.aiplatform_v1beta1 import types as aip_types
        from vertexai.preview import reasoning_engines
        from vertexai.reasoning_engines import _utils

        re = reasoning_engines.ReasoningEngine(engine_id)

        # Call remote reasoning engine using the stream client in a thread pool
        def do_stream_call():
            response = re.execution_api_client.stream_query_reasoning_engine(
                request=aip_types.StreamQueryReasoningEngineRequest(
                    name=re.resource_name,
                    input={
                        "message": message,
                        "user_id": user_id,
                        "session_id": session_id,
                    },
                    class_method="stream_query",
                )
            )
            events_list = []
            for chunk in response:
                for parsed_json in _utils.yield_parsed_json(chunk):
                    if parsed_json is not None:
                        events_list.append(parsed_json)
            return extract_chat_response_and_trace(events_list)

        rec, reasoning = await anyio.to_thread.run_sync(do_stream_call)
        if rec or reasoning:
            logger.info("Successfully received recommendation from remote agent.")
            return rec, reasoning
        raise ValueError("Remote agent returned empty response.")

    except Exception as remote_exc:
        logger.warning(
            f"Remote agent query failed (falling back to local): {remote_exc}"
        )
        from ag_kaggle_5day.app import advisor_runner

        if not advisor_runner:
            raise remote_exc

        # Execute locally
        orig_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = api_key
        try:
            events = await advisor_runner.run_debug(
                message,
                user_id=user_id,
                session_id=session_id,
                quiet=True,
            )
            return extract_chat_response_and_trace(events)
        finally:
            if orig_key is not None:
                os.environ["GEMINI_API_KEY"] = orig_key
            else:
                os.environ.pop("GEMINI_API_KEY", None)


def sanitize_agent_response(text: str) -> str:
    """Removes agent internal thinking, planning, and tool details from response.
    Filters out blocks inside <thought>...</thought> and <planning>...</planning> tags,
    as well as common reasoning/thought headers.
    """
    if not text:
        return ""
    # 1. Remove XML/HTML-like tags: <thought>...</thought>, <planning>...</planning>
    text = re.sub(
        r"<(thought|planning|thinking|reasoning)>.*?</\1>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 2. Clean up dangling/unclosed tags just in case
    text = re.sub(
        r"<(thought|planning|thinking|reasoning)>.*",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 3. Clean up lines starting with Thought:, Thinking:, Thinking Process:
    lines = text.split("\n")
    cleaned_lines = []
    in_thought_block = False
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith(
            (
                "thought:",
                "thinking:",
                "thinking process:",
                "thought process:",
                "planning:",
            )
        ):
            in_thought_block = True
            continue
        if in_thought_block:
            if line.startswith(("#", "**", "###", "1.", "-")) or not line.strip():
                in_thought_block = False
            else:
                continue
        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines)
    # 4. Remove leftover tag markers if any
    cleaned_text = cleaned_text.replace("<thought>", "").replace("</thought>", "")
    cleaned_text = cleaned_text.replace("<planning>", "").replace("</planning>", "")
    return cleaned_text.strip()


def safe_get_recommendation(query: str, api_key: str, model: str = None) -> str:
    try:
        from ag_kaggle_5day.agents.advisor import get_recommendation

        sig = inspect.signature(get_recommendation)
        kwargs = {}
        if "api_key" in sig.parameters:
            kwargs["api_key"] = api_key
        if "model" in sig.parameters:
            kwargs["model"] = model
        return get_recommendation(query, **kwargs)
    except Exception as e:
        return f"Error executing recommendation: {e}"


def safe_generate_stream_playbook(
    vibe: str,
    scale: str,
    duration: float,
    stream_goal: str = "growth",
    api_key: str = None,
    model: str = None,
    game: str = None,
    custom_context: str = None,
) -> dict:
    try:
        from ag_kaggle_5day.agents.advisor import generate_stream_playbook

        sig = inspect.signature(generate_stream_playbook)
        kwargs = {
            "vibe": vibe,
            "scale": scale,
            "duration": duration,
            "stream_goal": stream_goal,
            "api_key": api_key,
            "model": model,
            "game": game,
        }
        if "custom_context" in sig.parameters:
            kwargs["custom_context"] = custom_context
        return generate_stream_playbook(**kwargs)
    except Exception as e:
        logger.error(f"Error executing generate_stream_playbook: {e}", exc_info=True)
        return {"vibe": vibe, "scale": scale, "duration": duration, "playbooks": []}


@router.post(
    "/api/recommend",
    dependencies=[Depends(check_rate_limit(recommend_limiter))],
)
async def api_recommend(
    req: RecommendRequest,
    client_key: str | None = Depends(get_client_key),
    x_gemini_chat_model: str = Header(None),
):
    try:
        # Require client key if server key is configured
        has_server_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        if not client_key:
            if has_server_key:
                return {
                    "recommendation": (
                        "🔑 **API Key Required**\n\n"
                        "To chat with the Streamer Advisor and generate "
                        "custom recommendations, please enter your "
                        "Gemini API key in the **Settings** menu "
                        "(click Connect Personal Key in the top right)."
                    ),
                    "refresh_dashboard": False,
                }
            else:
                return {
                    "recommendation": (
                        "⚠️ [Environment Configuration Warning: "
                        "GEMINI_API_KEY is not set.]\n\n"
                        "Here is some advisor advice based on cached metrics:\n"
                        "We recommend targeting middle-tier viewership games "
                        "(like VALORANT or Elden Ring) depending on your "
                        "target stream duration. "
                        "To stand out, look at newer rogue-likes or indie "
                        "titles (such as Hades II) which offer highly engaged "
                        "audiences but lower competition."
                    ),
                    "refresh_dashboard": False,
                }

        key = get_effective_key(client_key)

        # 1. Get current custom games from cache before agent runs
        from ag_kaggle_5day.agents.scraper import CACHE_FILE

        def get_custom_titles():
            if os.path.exists(CACHE_FILE):
                try:
                    with open(CACHE_FILE, "r") as f:
                        games = json.load(f)
                    return sorted(
                        [
                            g["title"].lower()
                            for g in games
                            if g.get("custom") or g.get("tier") == "custom"
                        ]
                    )
                except Exception:
                    pass
            return []

        old_customs = get_custom_titles()

        # Execute chatbot query via remote Reasoning Engine
        # (falls back to local InMemoryRunner)
        from ag_kaggle_5day.app import query_remote_agent

        # Frontend user requests are strictly forced to run locally using the BYOK key
        force_local = True

        rec, reasoning = await query_remote_agent(
            req.query,
            user_id="default_user",
            session_id="default_session",
            api_key=key,
            force_local=force_local,
            model=x_gemini_chat_model,
        )
        if not rec:
            rec = "No response generated by the advisor agent."
            reasoning = ""
        else:
            rec = sanitize_agent_response(rec)

        # 2. Check if custom games changed after agent runs
        new_customs = get_custom_titles()
        refresh_dashboard = old_customs != new_customs

        return {
            "recommendation": rec,
            "reasoning": reasoning,
            "refresh_dashboard": refresh_dashboard,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/playbook",
    dependencies=[Depends(check_rate_limit(playbook_limiter))],
)
async def api_playbook(
    req: PlaybookRequest,
    client_key: str | None = Depends(get_client_key),
    x_gemini_chat_model: str = Header(None),
):
    try:
        if req.game == "Stream Gear & Setup":
            from ag_kaggle_5day.agents.advisor import get_affiliate_playbook

            is_key_valid = client_key and client_key.strip()
            key = get_effective_key(client_key) if is_key_valid else None
            aff_playbook = get_affiliate_playbook(
                vibe=req.vibe,
                scale=req.scale,
                stream_goal=req.stream_goal,
                api_key=key,
                previous_playbooks=req.previous_playbooks,
            )
            return {"playbooks": [aff_playbook]}

        # If no client-side key, fallback to local/mock generator (api_key=None)
        # to avoid using the server key.
        if not client_key or not client_key.strip():
            return safe_generate_stream_playbook(
                vibe=req.vibe,
                scale=req.scale,
                duration=req.duration,
                stream_goal=req.stream_goal,
                api_key=None,
                model=x_gemini_chat_model,
                game=req.game,
                custom_context=req.custom_context,
            )

        key = get_effective_key(client_key)

        if stream_playbook_workflow:
            runner = InMemoryRunner(node=stream_playbook_workflow)
            orig_key = os.environ.get("GEMINI_API_KEY")
            os.environ["GEMINI_API_KEY"] = key
            try:
                input_data = {
                    "vibe": req.vibe,
                    "scale": req.scale,
                    "duration": req.duration,
                    "stream_goal": req.stream_goal,
                    "game": req.game,
                    "custom_context": req.custom_context,
                }
                events = await runner.run_debug(
                    json.dumps(input_data),
                    user_id="api_user",
                    session_id=f"api_playbook_{int(time.time())}",
                    quiet=True,
                )
                playbook = events[-1].output if events else {}
            finally:
                if orig_key is not None:
                    os.environ["GEMINI_API_KEY"] = orig_key
                else:
                    os.environ.pop("GEMINI_API_KEY", None)
        else:
            playbook = safe_generate_stream_playbook(
                vibe=req.vibe,
                scale=req.scale,
                duration=req.duration,
                stream_goal=req.stream_goal,
                api_key=key,
                model=x_gemini_chat_model,
                game=req.game,
                custom_context=req.custom_context,
            )
        return playbook
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
