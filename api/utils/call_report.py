"""Helpers to normalize per-call report fields for CSV export."""

import os
import re
import tempfile

from typing import Any

from api.constants import BACKEND_API_ENDPOINT

# Matches transcript speaker labels in both formats:
#   diarized files: "[00:01] User: ..." / "[00:01] Agent: ..."
#   live transcripts: "[2026-09-18T...] user: ..." / "... assistant: ..."
_SPEAKER_LINE_RE = re.compile(
    r"^\s*\[.*?\]\s*(user|assistant|agent)\s*:\s*(.*)$", re.IGNORECASE
)


def backend_base_url() -> str:
    """Public base URL of this API (no trailing slash)."""
    return (BACKEND_API_ENDPOINT or "http://localhost:8000").rstrip("/")


def public_artifact_url(artifact_type: str, token: str) -> str:
    """Absolute, no-auth public download URL for a run artifact.

    Unlike storage presigned/MinIO URLs (which browsers cannot resolve when
    MinIO is internal, e.g. `http://minio/...` on Azure), these stay on the
    API's own origin and stream bytes server-side.
    """
    return f"{backend_base_url()}/api/v1/public/download/workflow/{token}/{artifact_type}"


async def download_artifact_to_temp(
    storage_key: str, storage_backend: str | None, suffix: str
) -> str | None:
    """Download a stored artifact to a temp file. Returns path or None.

    Caller owns cleanup of the returned path.
    """
    from api.services.storage import get_storage_for_backend, storage_fs

    storage = storage_fs
    if storage_backend:
        try:
            storage = get_storage_for_backend(storage_backend)
        except ValueError:
            pass
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        if await storage.adownload_file(storage_key, tmp_path):
            return tmp_path
    except Exception:
        pass
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return None


def extract_phone_number(initial_context: dict | None) -> str:
    """Best-effort phone number from a workflow run's initial context.

    Outbound calls store ``phone_number``; inbound store
    ``caller_number``/``called_number``.
    """
    ctx = initial_context or {}
    for key in ("phone_number", "caller_number", "called_number", "to_number", "from_number"):
        value = ctx.get(key)
        if value:
            return str(value)
    return ""


def extract_duration_seconds(
    cost_info: dict | None, gathered_context: dict | None = None
) -> int | None:
    """Best-effort call duration in seconds."""
    for source in (cost_info, gathered_context):
        if not source:
            continue
        for key in ("call_duration_seconds", "duration", "billsec", "CallDuration"):
            value = source.get(key)
            if value is None:
                continue
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                continue
    return None


def coerce_summary(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def extract_user_says(transcript_text: str | None) -> str:
    """Verbatim caller turns from a transcript, joined for CSV display.

    Handles both diarized files (``[MM:SS] User: ...``) and live transcripts
    (``[timestamp] user: ...``). Assistant/agent lines are dropped.
    """
    if not transcript_text:
        return ""
    lines = []
    for raw_line in transcript_text.splitlines():
        match = _SPEAKER_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        speaker, text = match.group(1).lower(), match.group(2).strip()
        if speaker == "user" and text:
            lines.append(text)
    return " | ".join(lines)


def _first_present(*values: Any) -> str:
    """First non-empty value stringified, else empty string."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def extract_provider_call_info(callbacks: list | None) -> dict:
    """Normalize provider (e.g. Vobiz) call detail from stored status callbacks.

    Prefers the Hangup event (carries Duration/BillDuration/HangupCause/
    TotalCost), else falls back to the last callback. Keys are mapped across
    providers (Vobiz/Plivo-style PascalCase plus generic snake_case), so
    non-Vobiz runs fill whatever their callbacks provide and blank the rest.

    Returns dict with: provider_call_uuid, answer_time, end_time,
    billable_seconds, hangup_cause, provider_cost.
    """
    events = [e for e in (callbacks or []) if isinstance(e, dict)]
    if not events:
        return {
            "provider_call_uuid": "",
            "answer_time": "",
            "end_time": "",
            "billable_seconds": "",
            "hangup_cause": "",
            "provider_cost": "",
        }

    hangup = next(
        (
            e
            for e in events
            if str(e.get("event_type", "")).lower() == "hangup"
            or "HangupCause" in (e.get("raw_data") or {})
            or "hangup" in str(e.get("status", "")).lower()
        ),
        events[-1],
    )
    # Flatten: top-level parsed fields plus provider raw payload.
    raw = hangup.get("raw_data") if isinstance(hangup.get("raw_data"), dict) else {}
    merged = {**raw, **{k: v for k, v in hangup.items() if k != "raw_data"}}

    def pick(*keys: str) -> str:
        return _first_present(*(merged.get(k) for k in keys))

    return {
        "provider_call_uuid": pick(
            "CallUUID", "call_uuid", "call_id", "CallSid", "uuid"
        ),
        "answer_time": pick("AnswerTime", "answer_time", "answered_at"),
        "end_time": pick("EndTime", "end_time", "ended_at"),
        "billable_seconds": pick(
            "BillDuration", "bill_duration", "billed_duration", "billsec"
        ),
        "hangup_cause": pick(
            "HangupCause",
            "hangup_cause",
            "HangupCauseName",
            "cause_txt",
            "disposition",
        ),
        "provider_cost": pick("TotalCost", "total_cost", "cost", "price"),
    }
