"""Meta WhatsApp (Text-only LLM) provider - Graph API v20+."""

import hashlib
import hmac
from typing import Optional

import httpx
from loguru import logger


GRAPH_BASE = "https://graph.facebook.com/v20.0"


def verify_signature(raw_body: bytes, signature_header: Optional[str], app_secret: str) -> bool:
    """Verify X-Hub-Signature-256: sha256=<hex hmac> using app_secret."""
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


async def send_text_message(
    *,
    phone_number_id: str,
    access_token: str,
    to: str,
    text: str,
) -> dict:
    """Send text via POST /{phone_number_id}/messages. Returns Graph response JSON."""
    url = f"{GRAPH_BASE}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
        if resp.status_code >= 400:
            logger.warning(f"WhatsApp send failed {resp.status_code}: {data}")
        else:
            logger.info(f"WhatsApp send ok to {to}: {data}")
        data["_status_code"] = resp.status_code
        return data


async def mark_read(
    *,
    phone_number_id: str,
    access_token: str,
    message_id: str,
) -> dict:
    url = f"{GRAPH_BASE}/{phone_number_id}/messages"
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload, headers=headers)
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "_status_code": resp.status_code}


def parse_inbound_messages(payload: dict) -> list[dict]:
    """Extract normalized inbound messages from Meta webhook payload."""
    out: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # Only whatsapp messages, ignore statuses
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")
            display_phone = metadata.get("display_phone_number")
            for m in messages:
                msg_type = m.get("type")
                if msg_type != "text":
                    continue  # text-only MVP
                out.append(
                    {
                        "phone_number_id": phone_number_id,
                        "display_phone_number": display_phone,
                        "wa_id": m.get("from"),  # sender
                        "message_id": m.get("id"),
                        "timestamp": m.get("timestamp"),
                        "text": (m.get("text") or {}).get("body", ""),
                        "contact_name": contacts[0].get("profile", {}).get("name") if contacts else None,
                        "raw": m,
                    }
                )
    return out
