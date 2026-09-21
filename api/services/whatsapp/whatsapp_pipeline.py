"""Isolated text-only WhatsApp LLM pipeline.

Isolated workflow template: no STT/TTS, just LLM (via create_llm_service).
Stores chats in WorkflowRun gathered_context + logs for separate tab.
"""

from typing import Optional

from loguru import logger

from api.db import db_client
from api.enums import WorkflowRunMode, WorkflowRunState
from api.services.configuration.registry import ServiceProviders
from api.services.pipecat.service_factory import create_llm_service
from api.services.pricing.cost_calculator import cost_calculator
from api.services.whatsapp.meta_provider import send_text_message


async def _compose_reply_text(
    *,
    workflow_id: int,
    organization_id: int,
    user_id: int,
    incoming_text: str,
    wa_id: str,
    history: list[dict],
) -> tuple[str, dict]:
    """Run isolated text LLM via workflow's linked workflow or org default.

    Returns (reply_text, token_usage_dict).
    """
    workflow = await db_client.get_workflow_by_id(workflow_id)
    user_config = await db_client.get_user_configurations(user_id)
    # Build minimal messages from workflow_definition fallback or direct LLM call
    # For isolated template, we use PipecatEngine-style system prompt if workflow exists,
    # else fallback to user_config LLM raw completion.

    # Try to extract system prompt from workflow_definition isolated template
    system_prompt = None
    if workflow and workflow.workflow_definition_with_fallback:
        try:
            nodes = workflow.workflow_definition_with_fallback.get("nodes", [])
            for n in nodes:
                data = n.get("data") or {}
                if data.get("prompt"):
                    system_prompt = data["prompt"]
                    break
                if n.get("type") in ("agent", "start", "whatsapp"):
                    system_prompt = data.get("prompt") or data.get("greeting")
                    if system_prompt:
                        break
        except Exception:
            pass

    # Fallback system prompt for text-only
    if not system_prompt:
        system_prompt = "You are a helpful WhatsApp assistant. Be concise. Detect language of user and reply in same language/accent."

    # Build messages: system + history tail (last 10) + incoming
    messages = [{"role": "system", "content": system_prompt}]
    # history is list of {role, content} from gathered_context whatsapp_history
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": incoming_text})

    # Instantiate LLM service via user_config (org-level)
    # Use create_llm_service which reads user_config.llm.provider/model/api_key
    try:
        llm_service = create_llm_service(user_config)
    except Exception as e:
        logger.warning(f"Failed to create LLM service, falling back to OpenAI adapter: {e}")
        # Fallback: try to create from provider directly if config missing
        from api.services.pipecat.service_factory import create_llm_service_from_provider

        llm_service = create_llm_service_from_provider(
            provider=ServiceProviders.OPENAI.value, model="gpt-4.1-mini", api_key=""
        )

    # Pipecat LLM services expose _settings.model and process - we call LLM directly via openai/google client
    # Simplest: use litellm-style via provider's underlying client is encapsulated; we call a thin wrapper:
    # Instead, use llm_service's internal client if available, else fallback to direct OpenAI call via settings.
    # For MVP we invoke via OpenAILLMService / GoogleLLMService's underlying completion if available.
    # Here we use a generic HTTP fallback: if llm_service has .settings.model, we dispatch accordingly.

    reply_text = ""
    usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # Attempt pipecat adapter completion
    # Most pipecat LLM services have .completion or .chat_completion; we try both
    try:
        # Try google/openai style: some have `completion` coroutine
        if hasattr(llm_service, "completion"):
            # Not all have, fallback
            pass
        # Generic: use openai client if provider is openai/groq/openrouter
        provider = getattr(getattr(user_config, "llm", None), "provider", "openai")
        model = getattr(getattr(user_config, "llm", None), "model", "gpt-4.1-mini")
        api_key = getattr(getattr(user_config, "llm", None), "api_key", None)
        if isinstance(api_key, list) and api_key:
            api_key = api_key[0]

        # Dispatch based on provider
        if provider in (ServiceProviders.OPENAI.value, ServiceProviders.GROQ.value, ServiceProviders.OPENROUTER.value):
            import openai

            base_url = None
            if provider == ServiceProviders.GROQ.value:
                base_url = "https://api.groq.com/openai/v1"
            elif provider == ServiceProviders.OPENROUTER.value:
                base_url = getattr(getattr(user_config, "llm", None), "base_url", "https://openrouter.ai/api/v1")

            client = openai.OpenAI(api_key=api_key, base_url=base_url) if base_url else openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=500)
            reply_text = resp.choices[0].message.content or ""
            if getattr(resp, "usage", None):
                usage = {
                    "prompt_tokens": resp.usage.prompt_tokens or 0,
                    "completion_tokens": resp.usage.completion_tokens or 0,
                    "total_tokens": resp.usage.total_tokens or 0,
                }
        elif provider == ServiceProviders.GOOGLE.value:
            # Google Gemini via google-generativeai or openai-compat
            try:
                import google.generativeai as genai  # type: ignore

                genai.configure(api_key=api_key)
                g_model = genai.GenerativeModel(model)
                # Convert messages to Gemini prompt: system + history
                prompt_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
                g_resp = g_model.generate_content(prompt_text)
                reply_text = getattr(g_resp, "text", "") or ""
                # Usage if available
                if getattr(g_resp, "usage_metadata", None):
                    usage = {
                        "prompt_tokens": getattr(g_resp.usage_metadata, "prompt_token_count", 0) or 0,
                        "completion_tokens": getattr(g_resp.usage_metadata, "candidates_token_count", 0) or 0,
                        "total_tokens": getattr(g_resp.usage_metadata, "total_token_count", 0) or 0,
                    }
            except Exception as ge:
                logger.warning(f"Google genai fallback failed {ge}, trying OpenAI compat")
                import openai

                client = openai.OpenAI(api_key=api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
                resp = client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=500)
                reply_text = resp.choices[0].message.content or ""
                if getattr(resp, "usage", None):
                    usage = {
                        "prompt_tokens": resp.usage.prompt_tokens or 0,
                        "completion_tokens": resp.usage.completion_tokens or 0,
                        "total_tokens": resp.usage.total_tokens or 0,
                    }
        else:
            # Generic fallback via OpenAI compat on configured model
            import openai

            client = openai.OpenAI(api_key=api_key or "sk-test")
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=500)
            reply_text = resp.choices[0].message.content or ""
    except Exception as e:
        logger.exception(f"WhatsApp LLM compose failed: {e}")
        reply_text = "Sorry, I am temporarily unavailable. Please try again."

    if not reply_text:
        reply_text = "Thanks for your message!"

    return reply_text, usage


async def handle_whatsapp_message(
    *,
    organization_id: int,
    user_id: int,
    phone_number_id: str,
    wa_id: str,
    text: str,
    message_id: str,
    whatsapp_config: dict,
    contact_name: Optional[str] = None,
) -> dict:
    """Orchestrate: find/create WorkflowRun, run isolated LLM, send reply, persist.

    Storage confirmed: gathered_context.whatsapp_history + logs.whatsapp_events
    """
    workflow_id = whatsapp_config.get("linked_workflow_id")
    if not workflow_id:
        # Fallback: pick first active workflow in org
        workflows = await db_client.get_all_workflows(organization_id=organization_id, status="active")
        # Filter active if available
        active = workflows if workflows else await db_client.get_all_workflows(organization_id=organization_id)
        workflow_id = active[0].id if active else None

    if not workflow_id:
        logger.warning(f"No workflow for org {organization_id} - sending fallback")
        # Still try to send fallback via LLM without workflow history
        reply_text, usage = await _compose_reply_text(
            workflow_id=0, organization_id=organization_id, user_id=user_id, incoming_text=text, wa_id=wa_id, history=[]
        )
        await send_text_message(
            phone_number_id=phone_number_id,
            access_token=whatsapp_config.get("access_token", ""),
            to=wa_id,
            text=reply_text,
        )
        return {"reply": reply_text, "usage": usage, "workflow_run_id": None}

    # Find or create per-contact WhatsApp WorkflowRun (mode=whatsapp, is_completed=False)
    # Use latest run for this contact within this workflow+org; else create new
    existing_tuple = await db_client.get_workflow_runs_by_workflow_id(workflow_id, limit=50)
    existing_runs = existing_tuple[0] if isinstance(existing_tuple, tuple) else existing_tuple
    # Filter whatsapp mode and wa_id in gathered_context
    target_run = None
    for r in existing_runs or []:
        if getattr(r, "mode", "") == WorkflowRunMode.WHATSAPP.value:
            ctx = getattr(r, "gathered_context", {}) or {}
            if ctx.get("wa_id") == wa_id and not r.is_completed:
                target_run = r
                break

    history: list[dict] = []
    if target_run:
        history = (target_run.gathered_context or {}).get("whatsapp_history", [])
        workflow_run_id = target_run.id
    else:
        # Create new run - isolated text-only template
        run = await db_client.create_workflow_run(
            name=f"WR-WA-{wa_id[-6:]}",
            workflow_id=workflow_id,
            mode=WorkflowRunMode.WHATSAPP.value,
            user_id=user_id,
            call_type="inbound",
            initial_context={"wa_id": wa_id, "phone_number_id": phone_number_id, "contact_name": contact_name},
            gathered_context={"wa_id": wa_id, "whatsapp_history": [], "contact_name": contact_name},
        )
        # Initialize logs/history after creation (create doesn't accept logs)
        await db_client.update_workflow_run(run_id=run.id, logs={"whatsapp_events": []})
        workflow_run_id = run.id
        history = []

    reply_text, usage = await _compose_reply_text(
        workflow_id=workflow_id,
        organization_id=organization_id,
        user_id=user_id,
        incoming_text=text,
        wa_id=wa_id,
        history=history,
    )

    # Send via Graph API
    send_res = await send_text_message(
        phone_number_id=phone_number_id,
        access_token=whatsapp_config.get("access_token", ""),
        to=wa_id,
        text=reply_text,
    )

    # Append to history: user + assistant
    new_history = history + [
        {"role": "user", "content": text, "wa_message_id": message_id, "at": __import__("datetime").datetime.utcnow().isoformat()},
        {"role": "assistant", "content": reply_text, "at": __import__("datetime").datetime.utcnow().isoformat()},
    ]
    # Trim to last 50 turns to bound JSON
    if len(new_history) > 50:
        new_history = new_history[-50:]

    # Update gathered_context + logs + usage_info (for separate tab)
    run_to_update = await db_client.get_workflow_run_by_id(workflow_run_id)
    gathered = dict(run_to_update.gathered_context or {})
    gathered["whatsapp_history"] = new_history
    gathered["last_wa_id"] = wa_id
    gathered["contact_name"] = contact_name or gathered.get("contact_name")
    # keep wa_id stable

    logs = dict(run_to_update.logs or {})
    events = list(logs.get("whatsapp_events", []))
    events.append(
        {
            "direction": "inbound",
            "wa_id": wa_id,
            "text": text,
            "message_id": message_id,
            "reply": reply_text,
            "send_res": send_res,
            "at": __import__("datetime").datetime.utcnow().isoformat(),
        }
    )
    if len(events) > 100:
        events = events[-100:]
    logs["whatsapp_events"] = events

    # Token usage for pricing (llm bucket) - merge with existing usage_info
    usage_info = dict(run_to_update.usage_info or {})
    llm_bucket = dict(usage_info.get("llm", {}))
    # Key processor|||model for cost_calculator inference (gemini-3.5-flash-lite or default)
    llm_key = f"WhatsAppLLM|||{whatsapp_config.get('model', 'gemini-3.5-flash-lite')}"
    existing = llm_bucket.get(llm_key, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    merged = {
        "prompt_tokens": (existing.get("prompt_tokens", 0) or 0) + usage.get("prompt_tokens", 0),
        "completion_tokens": (existing.get("completion_tokens", 0) or 0) + usage.get("completion_tokens", 0),
        "total_tokens": (existing.get("total_tokens", 0) or 0) + usage.get("total_tokens", 0),
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    llm_bucket[llm_key] = merged
    usage_info["llm"] = llm_bucket
    # Call duration for org quota display
    usage_info["call_duration_seconds"] = usage_info.get("call_duration_seconds", 0)

    # Cost breakdown (optional, for observability)
    try:
        cost_breakdown = cost_calculator.calculate_total_cost(usage_info)
    except Exception:
        cost_breakdown = {}

    await db_client.update_workflow_run(
        run_id=workflow_run_id,
        gathered_context=gathered,
        logs=logs,
        usage_info=usage_info,
        cost_info={**(run_to_update.cost_info or {}), "cost_breakdown": cost_breakdown, "last_send_res": send_res},
    )

    logger.info(f"WhatsApp handled org {organization_id} wa_id {wa_id} run {workflow_run_id} cost {cost_breakdown}")
    return {"workflow_run_id": workflow_run_id, "reply": reply_text, "usage": usage, "cost_breakdown": cost_breakdown}
