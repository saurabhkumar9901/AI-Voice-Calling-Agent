"""Scheduled follow-up callback tasks (ARQ).

``check_due_callbacks`` runs every minute via ARQ cron: it claims due
callbacks and places each call. ``place_callback_call`` performs a single
placement and is also enqueued directly (manual/API triggers).

Retry policy: on busy/failed outcomes (handled in
``telephony._process_status_update``) a single retry is scheduled +5 minutes
(or next 08:00 caller-local time during quiet hours 22:00–08:00). No-answer,
voicemail, and connected calls are terminal.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from api.db import db_client
from api.enums import CallType, WorkflowRunState
from api.services.callbacks import (
    CALLBACK_RETRY_DELAY_SECONDS,
    get_user_timezone,
    is_quiet_hours,
    roll_forward_quiet_hours,
)
from api.services.quota_service import check_dograh_quota_by_user_id
from api.services.telephony.factory import get_telephony_provider
from api.utils.common import get_backend_endpoints
from pipecat.utils.run_context import set_current_run_id

UTC = timezone.utc

#: Outcomes that consume the single retry (never connected).
RETRYABLE_TERMINAL = {"busy", "failed", "canceled", "error"}


async def check_due_callbacks(_ctx) -> int:
    """ARQ cron: place all due scheduled callbacks. Returns placed count."""
    callback_ids = await db_client.claim_due_callbacks(limit=25)
    logger.info(f"Callback scheduler tick: {len(callback_ids)} due")
    if not callback_ids:
        return 0
    logger.info(f"Claimed {len(callback_ids)} due callbacks")
    placed = 0
    for callback_id in callback_ids:
        try:
            await place_callback_call(_ctx, callback_id)
            placed += 1
        except Exception as e:
            logger.error(f"Failed to place callback {callback_id}: {e}")
            # Release back to scheduled so a later tick retries placement.
            try:
                await db_client.update_callback(callback_id, state="scheduled")
            except Exception:
                pass
    return placed


async def place_callback_call(_ctx, callback_id: int) -> Optional[int]:
    """Place a single scheduled callback call. Returns workflow_run_id."""
    callback = await db_client.get_callback_by_id(callback_id)
    if callback is None:
        logger.warning(f"Callback {callback_id} not found")
        return None
    if callback.state not in ("in_progress", "scheduled"):
        logger.info(
            f"Callback {callback.id} in state {callback.state}, skipping placement"
        )
        return None

    set_current_run_id(f"callback-{callback_id}")
    user_tz = callback.timezone or await get_user_timezone(callback.user_id)

    # Quiet hours: roll to next 08:00 caller-local, keep scheduled.
    now_utc = datetime.now(UTC)
    if is_quiet_hours(now_utc, user_tz):
        wake = roll_forward_quiet_hours(now_utc, user_tz)
        await db_client.update_callback(callback_id, state="scheduled", scheduled_for=wake)
        logger.info(
            f"Callback {callback_id} in quiet hours, moved to {wake.isoformat()}"
        )
        return None

    workflow = await db_client.get_workflow_by_id(callback.workflow_id)
    if workflow is None:
        await db_client.update_callback(
            callback_id, state="failed", failure_reason="workflow_not_found"
        )
        return None

    owner_user_id = callback.user_id or workflow.user_id

    # Quota guard: postpone 60 minutes on exhaustion (time-bound by nature).
    try:
        quota = await check_dograh_quota_by_user_id(owner_user_id)
        if not quota.has_quota:
            wake = now_utc + timedelta(minutes=60)
            await db_client.update_callback(
                callback_id,
                state="scheduled",
                scheduled_for=wake,
                failure_reason="quota_exceeded",
            )
            logger.warning(f"Callback {callback_id} postponed (quota exceeded)")
            return None
    except Exception as e:
        logger.warning(f"Callback {callback_id} quota check failed: {e}")

    try:
        provider = await get_telephony_provider(callback.organization_id)
    except Exception as e:
        await db_client.update_callback(
            callback_id, state="failed", failure_reason=f"no_provider: {e}"
        )
        return None
    if not provider.validate_config():
        await db_client.update_callback(
            callback_id, state="failed", failure_reason="provider_not_configured"
        )
        return None

    from_numbers = getattr(provider, "from_numbers", []) or []
    if not from_numbers:
        await db_client.update_callback(
            callback_id, state="failed", failure_reason="no_from_number"
        )
        return None

    workflow_run = await db_client.create_workflow_run(
        name=f"WR-CALLBACK-{callback.id}",
        workflow_id=callback.workflow_id,
        mode=provider.PROVIDER_NAME,
        user_id=owner_user_id,
        call_type=CallType.OUTBOUND,
        initial_context={
            "phone_number": callback.phone_number,
            "provider": provider.PROVIDER_NAME,
            "callback_id": callback.id,
            "is_callback": True,
            "callback_attempt": callback.retry_count + 1,
            "callback_note": callback.note or "",
        },
    )

    backend_endpoint, _ = await get_backend_endpoints()
    webhook_url = (
        f"{backend_endpoint}/api/v1/telephony/{provider.WEBHOOK_ENDPOINT}"
        f"?workflow_id={callback.workflow_id}"
        f"&user_id={owner_user_id}"
        f"&workflow_run_id={workflow_run.id}"
        f"&organization_id={callback.organization_id}"
    )

    try:
        result = await provider.initiate_call(
            to_number=callback.phone_number,
            webhook_url=webhook_url,
            workflow_run_id=workflow_run.id,
            from_number=from_numbers[0],
            workflow_id=callback.workflow_id,
            user_id=owner_user_id,
        )
        await db_client.update_workflow_run(
            run_id=workflow_run.id,
            gathered_context={
                "provider": provider.PROVIDER_NAME,
                "callback_id": callback.id,
                **(result.provider_metadata or {}),
            },
        )
        logger.info(
            f"Callback {callback_id} placed as workflow run {workflow_run.id} "
            f"(call {result.call_id})"
        )
        return workflow_run.id
    except Exception as e:
        logger.error(f"Callback {callback_id} initiation failed: {e}")
        await db_client.update_workflow_run(
            run_id=workflow_run.id,
            is_completed=True,
            state=WorkflowRunState.COMPLETED.value,
            gathered_context={"callback_id": callback.id, "error": str(e)},
        )
        # Treat provider errors like a failed attempt (consumes the retry).
        await handle_callback_attempt_outcome(callback.id, "failed", str(e))
        return workflow_run.id


async def handle_callback_attempt_outcome(
    callback_id: int, status: str, reason: str = ""
) -> None:
    """Record a callback attempt outcome; schedule the single retry if eligible.

    Eligible: status in busy/failed/canceled/error AND parent retry_count == 0.
    Everything else (completed, no-answer, voicemail) is terminal.
    """
    callback = await db_client.get_callback_by_id(callback_id)
    if callback is None:
        return

    if status == "completed":
        await db_client.update_callback(callback_id, state="completed")
        logger.info(f"Callback {callback_id} completed")
        return

    if status in RETRYABLE_TERMINAL and (callback.retry_count or 0) == 0:
        user_tz = callback.timezone or await get_user_timezone(callback.user_id)
        when = roll_forward_quiet_hours(
            datetime.now(UTC) + timedelta(seconds=CALLBACK_RETRY_DELAY_SECONDS),
            user_tz,
        )
        child = await db_client.create_callback(
            organization_id=callback.organization_id,
            workflow_id=callback.workflow_id,
            phone_number=callback.phone_number,
            scheduled_for=when,
            user_id=callback.user_id,
            source_run_id=callback.source_run_id,
            timezone=user_tz,
            note=callback.note,
            parent_callback_id=callback.id,
            retry_count=1,
        )
        await db_client.update_callback(
            callback_id, state="failed", failure_reason=reason or status
        )
        logger.info(
            f"Callback {callback_id} {status}: single retry {child.id} "
            f"at {when.isoformat()}"
        )
        return

    # Terminal: no-answer, voicemail, exhausted retry, or unknown status.
    await db_client.update_callback(
        callback_id, state="failed", failure_reason=reason or status
    )
    logger.info(f"Callback {callback_id} terminal ({status}), no retry")
