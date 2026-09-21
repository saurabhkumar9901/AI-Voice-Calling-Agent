"""Follow-up callback listing for operational visibility.

Lets users see scheduled/placed/terminal callbacks (what, when, to whom,
and what happened) without database access.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/callbacks", tags=["callbacks"])


class CallbackResponse(BaseModel):
    id: int
    phone_number: str
    scheduled_for: datetime
    timezone: Optional[str] = None
    state: str
    retry_count: int
    failure_reason: Optional[str] = None
    note: Optional[str] = None
    source_run_id: Optional[int] = None
    workflow_id: int
    parent_callback_id: Optional[int] = None
    created_at: datetime


class CallbackListResponse(BaseModel):
    callbacks: List[CallbackResponse]
    total_count: int


@router.get("", response_model=CallbackListResponse)
async def list_callbacks(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(
        None, description="Filter by state: scheduled, in_progress, completed, failed, cancelled"
    ),
    user: UserModel = Depends(get_user),
):
    """List scheduled follow-up callbacks for the user's organization."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    callbacks = await db_client.list_callbacks_for_organization(
        user.selected_organization_id, limit=limit, offset=offset
    )
    if state:
        callbacks = [c for c in callbacks if c.state == state]
    total_count = await db_client.count_callbacks_for_organization(
        user.selected_organization_id, state=state
    )

    return CallbackListResponse(
        callbacks=[
            CallbackResponse(
                id=c.id,
                phone_number=c.phone_number,
                scheduled_for=c.scheduled_for,
                timezone=c.timezone,
                state=c.state,
                retry_count=c.retry_count or 0,
                failure_reason=c.failure_reason,
                note=c.note,
                source_run_id=c.source_run_id,
                workflow_id=c.workflow_id,
                parent_callback_id=c.parent_callback_id,
                created_at=c.created_at,
            )
            for c in callbacks
        ],
        total_count=total_count,
    )
