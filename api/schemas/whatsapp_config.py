from typing import List, Optional

from pydantic import BaseModel, Field


class WhatsAppConfigurationRequest(BaseModel):
    """Org-level Meta WhatsApp (text-only LLM) configuration."""

    provider: str = Field(default="meta")
    waba_id: str = Field(..., description="WhatsApp Business Account ID (WABA ID)")
    phone_number_id: str = Field(..., description="Meta Phone Number ID")
    access_token: str = Field(..., description="Meta System User Access Token (permanent)")
    app_secret: str = Field(..., description="Meta App Secret (for X-Hub-Signature-256)")
    verify_token: str = Field(..., description="Webhook verify_token (hub.verify_token)")
    display_phone_number: Optional[str] = Field(None, description="Display phone number e.g. +15551234567")
    linked_workflow_id: Optional[int] = Field(None, description="Isolated text-only workflow to route inbound messages")
    from_numbers: List[str] = Field(default_factory=list, description="Optional allowlist mirror for telephony pattern")


class WhatsAppConfigurationResponse(BaseModel):
    """Response with masked sensitive fields."""

    provider: str = "meta"
    waba_id: str
    phone_number_id: str
    access_token: str  # masked
    app_secret: str  # masked
    verify_token: str  # masked
    display_phone_number: Optional[str] = None
    linked_workflow_id: Optional[int] = None
    from_numbers: List[str] = []
    configured: bool = True
