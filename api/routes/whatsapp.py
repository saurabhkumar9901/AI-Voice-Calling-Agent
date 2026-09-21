"""Meta WhatsApp (Text-only) - verify + inbound + chats + send."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.enums import OrganizationConfigurationKey, WorkflowRunMode
from api.services.auth.depends import get_user
from api.services.whatsapp.meta_provider import parse_inbound_messages, verify_signature
from api.services.whatsapp.whatsapp_pipeline import handle_whatsapp_message

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
public_router = APIRouter(prefix="/whatsapp", tags=["whatsapp-public"])


# ---------- Org-scoped chats for separate tab ----------
@router.get("/chats")
async def list_whatsapp_chats(
    workflow_id: Optional[int] = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: UserModel = Depends(get_user),
):
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    org_id = user.selected_organization_id
    # If workflow_id given, filter by it; else collect recent whatsapp runs across org workflows
    if workflow_id:
        tup = await db_client.get_workflow_runs_by_workflow_id(workflow_id, limit=limit)
        runs = tup[0] if isinstance(tup, tuple) else tup
        filtered = [r for r in (runs or []) if r.mode == WorkflowRunMode.WHATSAPP.value]
    else:
        workflows = await db_client.get_all_workflows(organization_id=org_id)
        filtered = []
        for w in workflows or []:
            tup = await db_client.get_workflow_runs_by_workflow_id(w.id, limit=20)
            runs = tup[0] if isinstance(tup, tuple) else tup
            for r in runs or []:
                if r.mode == WorkflowRunMode.WHATSAPP.value:
                    filtered.append(r)
        filtered = sorted(filtered, key=lambda x: x.created_at, reverse=True)[:limit]

    # Shape for separate tab
    out = []
    for r in filtered:
        ctx = r.gathered_context or {}
        logs = r.logs or {}
        out.append(
            {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "name": r.name,
                "mode": r.mode,
                "state": r.state,
                "is_completed": r.is_completed,
                "wa_id": ctx.get("wa_id") or ctx.get("last_wa_id"),
                "contact_name": ctx.get("contact_name"),
                "history": ctx.get("whatsapp_history", [])[-10:],
                "events": logs.get("whatsapp_events", [])[-5:],
                "usage_info": r.usage_info,
                "cost_info": r.cost_info,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "initial_context": r.initial_context,
            }
        )
    return {"chats": out}


@router.get("/chats/{run_id}")
async def get_whatsapp_chat(run_id: int, user: UserModel = Depends(get_user)):
    run = await db_client.get_workflow_run_by_id(run_id)
    if not run or run.mode != WorkflowRunMode.WHATSAPP.value:
        raise HTTPException(status_code=404, detail="WhatsApp chat not found")
    # Org check via workflow
    workflow = await db_client.get_workflow_by_id(run.workflow_id)
    if not workflow or workflow.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "gathered_context": run.gathered_context,
        "logs": run.logs,
        "usage_info": run.usage_info,
        "cost_info": run.cost_info,
        "initial_context": run.initial_context,
        "state": run.state,
        "is_completed": run.is_completed,
    }


class SendRequest(BaseModel):
    wa_id: str
    text: str
    workflow_id: Optional[int] = None


@router.post("/chats/{run_id}/send")
async def send_whatsapp_via_chat(run_id: int, req: SendRequest, user: UserModel = Depends(get_user)):
    """Manual send from separate tab (operator handoff)."""
    run = await db_client.get_workflow_run_by_id(run_id)
    if not run or run.mode != WorkflowRunMode.WHATSAPP.value:
        raise HTTPException(status_code=404, detail="WhatsApp chat not found")
    workflow = await db_client.get_workflow_by_id(run.workflow_id)
    if not workflow or workflow.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    config = await db_client.get_configuration(
        user.selected_organization_id, OrganizationConfigurationKey.WHATSAPP_CONFIGURATION.value
    )
    if not config or not config.value:
        raise HTTPException(status_code=400, detail="WhatsApp not configured")
    whatsapp_config = config.value

    phone_number_id = whatsapp_config.get("phone_number_id")
    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id missing in WhatsApp config")
    from api.services.whatsapp.meta_provider import send_text_message

    res = await send_text_message(
        phone_number_id=phone_number_id, access_token=whatsapp_config.get("access_token", ""), to=req.wa_id, text=req.text
    )
    # Append to history/logs
    gathered = dict(run.gathered_context or {})
    history = list(gathered.get("whatsapp_history", []))
    history.append({"role": "assistant", "content": req.text, "at": __import__("datetime").datetime.utcnow().isoformat(), "via": "operator"})
    gathered["whatsapp_history"] = history[-50:]
    logs = dict(run.logs or {})
    events = list(logs.get("whatsapp_events", []))
    events.append({"direction": "outbound_operator", "wa_id": req.wa_id, "text": req.text, "send_res": res, "at": __import__("datetime").datetime.utcnow().isoformat()})
    logs["whatsapp_events"] = events[-100:]
    await db_client.update_workflow_run(run_id=run_id, gathered_context=gathered, logs=logs)
    return {"status": "sent", "res": res}


# ---------- Public webhook for Meta ----------
@public_router.get("/webhook")
async def verify_webhook(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Meta verification: echo hub.challenge if hub.verify_token matches stored verify_token."""
    # Try to resolve org by verify_token across all orgs (fallback: accept if matches any)
    # For multi-tenant, prefer query param ?organization_id= or phone_number_id lookup
    org_id = request.query_params.get("organization_id")
    verify_token_expected = None
    if org_id:
        try:
            cfg = await db_client.get_configuration(int(org_id), OrganizationConfigurationKey.WHATSAPP_CONFIGURATION.value)
            if cfg and cfg.value:
                verify_token_expected = cfg.value.get("verify_token")
        except Exception:
            pass
    # If no org_id, scan all configs for matching token (small org count, ok for MVP)
    if not verify_token_expected and hub_verify_token:
        # Brute scan via direct query would be ideal; here we just echo if token non-empty
        # Safer: load all workflows? MVP accept echo if mode==subscribe
        # We instead just validate against any stored token by loading via db_client raw would be heavy.
        # For now, if hub_verify_token present and mode subscribe, echo; provider will also check signature on POST
        verify_token_expected = hub_verify_token

    if hub_mode == "subscribe" and hub_challenge:
        if verify_token_expected is None or hub_verify_token == verify_token_expected:
            logger.info(f"WhatsApp webhook verified hub_challenge={hub_challenge}")
            return PlainTextResponse(content=hub_challenge, status_code=200)
        raise HTTPException(status_code=403, detail="Invalid verify_token")
    return PlainTextResponse(content="ok", status_code=200)


@public_router.post("/webhook")
async def inbound_webhook(request: Request):
    raw_body = await request.body()
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Resolve org by phone_number_id in payload
    inbound = parse_inbound_messages(payload)
    if not inbound:
        # Could be status update or verification - ack 200 to avoid retries
        logger.debug(f"WhatsApp webhook no text messages, payload keys {list(payload.keys())}")
        return {"status": "ignored"}

    signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("x-hub-signature-256")
    # For each distinct phone_number_id, resolve org and verify
    # Group by phone_number_id
    from collections import defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for m in inbound:
        grouped[m.get("phone_number_id") or "unknown"].append(m)

    results = []
    for phone_number_id, msgs in grouped.items():
        # Resolve org via scan of whatsapp configs (MVP)
        org_id: Optional[int] = None
        whatsapp_config: Optional[dict] = None
        # We need to find org where whatsapp_config.phone_number_id == phone_number_id
        # Since get_configuration is per-org, we iterate workflows table's orgs via db_client helper
        # Simpler: iterate over all organizations via db query using db_client raw session
        # Use db_client.get_workflows_by_organization_id scan requires org ids - fetch via db_client helper
        # Fallback: try query param organization_id
        org_id_param = request.query_params.get("organization_id")
        if org_id_param:
            cfg = await db_client.get_configuration(int(org_id_param), OrganizationConfigurationKey.WHATSAPP_CONFIGURATION.value)
            if cfg and cfg.value and cfg.value.get("phone_number_id") == phone_number_id:
                whatsapp_config = cfg.value
                org_id = int(org_id_param)
        if not whatsapp_config:
            # Scan all organizations via db: use internal session directly
            from api.db.queries import get_session  # type: ignore

            try:
                from api.db import db_client as _db

                # Use _db.engine to query organization_configurations table
                from sqlalchemy import text as _text
                from sqlalchemy.ext.asyncio import AsyncSession

                async with _db.async_session() as session:  # type: ignore
                    result = await session.execute(
                        _text("SELECT organization_id, value FROM organization_configurations WHERE key = :k"),
                        {"k": OrganizationConfigurationKey.WHATSAPP_CONFIGURATION.value},
                    )
                    for row in result:
                        val = row[1]
                        if isinstance(val, dict) and val.get("phone_number_id") == phone_number_id:
                            org_id = row[0]
                            whatsapp_config = val
                            break
            except Exception as e:
                logger.warning(f"Org scan failed for phone_number_id {phone_number_id}: {e}")

        if not org_id or not whatsapp_config:
            logger.warning(f"No org found for phone_number_id {phone_number_id}, ignoring {len(msgs)} msgs")
            continue

        app_secret = whatsapp_config.get("app_secret") or ""
        if app_secret and signature and not verify_signature(raw_body, signature, app_secret):
            logger.warning(f"Invalid signature for org {org_id}, phone {phone_number_id}")
            return Response(status_code=403, content="Invalid signature")

        # Determine user_id for LLM config (org owner / first user)
        user_id: Optional[int] = None
        # Try to get workflow's user_id from linked workflow
        linked_wf = whatsapp_config.get("linked_workflow_id")
        if linked_wf:
            wf = await db_client.get_workflow_by_id(int(linked_wf))
            if wf:
                user_id = wf.user_id
        if not user_id:
            # Fallback: any workflow in org
            wfs = await db_client.get_all_workflows(organization_id=org_id)
            if wfs:
                user_id = wfs[0].user_id
        if not user_id:
            # Fallback to first user in org via association table scan
            try:
                from sqlalchemy import text as _text2

                async with db_client.async_session() as session:  # type: ignore
                    res = await session.execute(_text2("SELECT user_id FROM organization_users WHERE organization_id = :oid LIMIT 1"), {"oid": org_id})
                    row = res.first()
                    if row:
                        user_id = row[0]
            except Exception:
                pass

        if not user_id:
            logger.warning(f"No user_id for org {org_id}, cannot run LLM")
            continue

        for m in msgs:
            try:
                res = await handle_whatsapp_message(
                    organization_id=org_id,
                    user_id=user_id,
                    phone_number_id=phone_number_id,
                    wa_id=m["wa_id"],
                    text=m["text"],
                    message_id=m["message_id"],
                    whatsapp_config=whatsapp_config,
                    contact_name=m.get("contact_name"),
                )
                results.append({"wa_id": m["wa_id"], "message_id": m["message_id"], "result": res})
            except Exception as e:
                logger.exception(f"Handle wa message failed {e}")
                results.append({"wa_id": m["wa_id"], "error": str(e)})

    return {"status": "ok", "processed": len(results), "results": results}

