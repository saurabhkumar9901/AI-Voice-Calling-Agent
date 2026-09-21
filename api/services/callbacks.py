"""Shared helpers for scheduled follow-up callbacks.

A callback is created live by the ``schedule_callback`` agent tool or post-call
by transcript extraction, then placed by the ARQ scheduler (see
``api.tasks.callback_tasks``). All times are stored in UTC; the caller's
timezone is used for quiet-hours checks and display.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from api.db import db_client

UTC = timezone.utc

# No auto-calls during these local hours; roll forward to QUIET_END_HOUR.
QUIET_START_HOUR = 22
QUIET_END_HOUR = 8
# Ignore callback requests further out than this.
MAX_SCHEDULE_DAYS = 60
# Single retry delay for busy/failed callback attempts.
CALLBACK_RETRY_DELAY_SECONDS = 120 * 60


def resolve_timezone(tz_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


async def get_user_timezone(user_id: Optional[int]) -> str:
    """User-configured timezone name, defaulting to UTC."""
    if not user_id:
        return "UTC"
    try:
        user_config = await db_client.get_user_configurations(user_id)
        tz = getattr(user_config, "timezone", None)
        if tz:
            ZoneInfo(tz)  # validate
            return tz
    except Exception as e:
        logger.debug(f"Could not resolve user timezone: {e}")
    return "UTC"


def is_quiet_hours(moment_utc: datetime, tz_name: Optional[str]) -> bool:
    """True when local time is in [22:00, 08:00)."""
    tz = resolve_timezone(tz_name)
    local = moment_utc.astimezone(tz)
    return local.hour >= QUIET_START_HOUR or local.hour < QUIET_END_HOUR


def roll_forward_quiet_hours(
    moment_utc: datetime, tz_name: Optional[str]
) -> datetime:
    """Push a UTC datetime to next 08:00 local if it falls in quiet hours."""
    tz = resolve_timezone(tz_name)
    local = moment_utc.astimezone(tz)
    if local.hour >= QUIET_START_HOUR or local.hour < QUIET_END_HOUR:
        if local.hour >= QUIET_START_HOUR:
            target = local.replace(
                hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
        else:
            target = local.replace(
                hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0
            )
        return target.astimezone(UTC)
    return moment_utc


def normalize_scheduled_time(
    requested_utc: datetime, tz_name: Optional[str]
) -> Optional[datetime]:
    """Apply quiet-hours roll-forward and horizon cap. None = drop request."""
    if requested_utc.tzinfo is None:
        requested_utc = requested_utc.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if requested_utc <= now:
        logger.info("Callback time is in the past, ignoring")
        return None
    if requested_utc > now + timedelta(days=MAX_SCHEDULE_DAYS):
        logger.info("Callback time beyond max horizon, ignoring")
        return None
    return roll_forward_quiet_hours(requested_utc, tz_name)


def parse_iso_to_utc(raw: str, tz_name: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime to aware UTC.

    Naive datetimes are interpreted in the given timezone. Returns None when
    unparseable.
    """
    try:
        parsed = datetime.fromisoformat((raw or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_timezone(tz_name))
    return parsed.astimezone(UTC)


def resolve_callback_phone(initial_context: Optional[dict]) -> str:
    """Best-effort callback number: outbound number, else inbound caller."""
    ctx = initial_context or {}
    for key in ("phone_number", "caller_number", "called_number"):
        value = ctx.get(key)
        if value:
            return str(value)
    return ""


async def schedule_callback_for_run(
    workflow_run,
    scheduled_for_utc: datetime,
    note: Optional[str] = None,
) -> Optional[int]:
    """Create a scheduled callback from a completed workflow run.

    If the run already has a still-scheduled callback (e.g. the caller changed
    the time mid-call), its time/note is updated in place so the agent's
    "rescheduled" promise holds. Returns the callback id, or None when
    skipped (no phone, past time).
    """
    workflow = getattr(workflow_run, "workflow", None)
    if workflow is None:
        logger.warning(f"[run {workflow_run.id}] No workflow, skipping callback")
        return None

    phone = resolve_callback_phone(getattr(workflow_run, "initial_context", None))
    if not phone:
        logger.warning(f"[run {workflow_run.id}] No phone number, skipping callback")
        return None

    user_id = getattr(workflow, "user_id", None)
    organization_id = getattr(workflow, "organization_id", None)
    if not organization_id:
        user = getattr(workflow, "user", None)
        organization_id = getattr(user, "selected_organization_id", None)
    if not organization_id:
        logger.warning(f"[run {workflow_run.id}] No organization, skipping callback")
        return None

    user_tz = await get_user_timezone(user_id)
    scheduled_for = normalize_scheduled_time(scheduled_for_utc, user_tz)
    if scheduled_for is None:
        return None

    existing = await db_client.get_scheduled_callback_for_run(workflow_run.id)
    if existing is not None:
        await db_client.update_callback(
            existing.id, scheduled_for=scheduled_for, note=note
        )
        logger.info(
            f"[run {workflow_run.id}] Rescheduled callback {existing.id} "
            f"to {scheduled_for.isoformat()}"
        )
        return existing.id

    callback = await db_client.create_callback(
        organization_id=organization_id,
        workflow_id=workflow.id,
        phone_number=phone,
        scheduled_for=scheduled_for,
        user_id=user_id,
        source_run_id=workflow_run.id,
        timezone=user_tz,
        note=note,
    )
    return callback.id
