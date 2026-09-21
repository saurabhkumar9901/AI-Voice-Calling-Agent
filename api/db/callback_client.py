"""Database client for managing scheduled follow-up callbacks."""

from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger
from sqlalchemy import func, select

from api.db.base_client import BaseDBClient
from api.db.models import CallbackModel

UTC = timezone.utc


class CallbackClient(BaseDBClient):
    """Client for scheduled callbacks (call-me-later requests)."""

    async def create_callback(
        self,
        organization_id: int,
        workflow_id: int,
        phone_number: str,
        scheduled_for: datetime,
        user_id: Optional[int] = None,
        source_run_id: Optional[int] = None,
        timezone: Optional[str] = None,
        note: Optional[str] = None,
        parent_callback_id: Optional[int] = None,
        retry_count: int = 0,
    ) -> CallbackModel:
        async with self.async_session() as session:
            callback = CallbackModel(
                organization_id=organization_id,
                workflow_id=workflow_id,
                user_id=user_id,
                source_run_id=source_run_id,
                phone_number=phone_number,
                scheduled_for=scheduled_for,
                timezone=timezone,
                note=note,
                state="scheduled",
                retry_count=retry_count,
                parent_callback_id=parent_callback_id,
            )
            session.add(callback)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            await session.refresh(callback)
            logger.info(
                f"Created callback {callback.id} for {phone_number} "
                f"at {scheduled_for.isoformat()}"
            )
            return callback

    async def get_callback_by_id(self, callback_id: int) -> Optional[CallbackModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackModel).where(CallbackModel.id == callback_id)
            )
            return result.scalars().first()

    async def has_callback_for_run(self, source_run_id: int) -> bool:
        """Check whether a callback was already created from a workflow run."""
        return (
            await self.get_scheduled_callback_for_run(source_run_id) is not None
        )

    async def get_scheduled_callback_for_run(
        self, source_run_id: int
    ) -> Optional[CallbackModel]:
        """Return the still-scheduled callback created from a workflow run, if any.

        Only ``scheduled`` rows are returned: in-flight/completed/failed ones
        are left untouched so a new request creates a fresh callback instead.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackModel)
                .where(
                    CallbackModel.source_run_id == source_run_id,
                    CallbackModel.state == "scheduled",
                )
                .order_by(CallbackModel.created_at.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def claim_due_callbacks(self, limit: int = 25) -> List[int]:
        """Atomically claim due callbacks for processing (SKIP LOCKED).

        Returns callback ids transitioned to ``in_progress``. Ids (not ORM
        objects) are returned because the session is closed on return and
        attribute access on committed instances would raise
        DetachedInstanceError.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackModel)
                .where(
                    CallbackModel.state == "scheduled",
                    CallbackModel.scheduled_for <= datetime.now(UTC),
                )
                .order_by(CallbackModel.scheduled_for.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            callbacks = list(result.scalars().all())
            ids = [callback.id for callback in callbacks]
            for callback in callbacks:
                callback.state = "in_progress"
                callback.updated_at = datetime.now(UTC)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return ids

    async def update_callback(
        self,
        callback_id: int,
        state: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
        failure_reason: Optional[str] = None,
        workflow_run_id: Optional[int] = None,
        note: Optional[str] = None,
    ) -> Optional[CallbackModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackModel).where(CallbackModel.id == callback_id)
            )
            callback = result.scalars().first()
            if not callback:
                return None
            if state is not None:
                callback.state = state
            if scheduled_for is not None:
                callback.scheduled_for = scheduled_for
            if failure_reason is not None:
                callback.failure_reason = failure_reason
            if note is not None:
                callback.note = note
            callback.updated_at = datetime.now(UTC)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            await session.refresh(callback)
            return callback

    async def list_callbacks_for_organization(
        self, organization_id: int, limit: int = 100, offset: int = 0
    ) -> List[CallbackModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackModel)
                .where(CallbackModel.organization_id == organization_id)
                .order_by(CallbackModel.scheduled_for.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())

    async def count_callbacks_for_organization(
        self, organization_id: int, state: Optional[str] = None
    ) -> int:
        async with self.async_session() as session:
            query = select(func.count(CallbackModel.id)).where(
                CallbackModel.organization_id == organization_id
            )
            if state:
                query = query.where(CallbackModel.state == state)
            result = await session.execute(query)
            return int(result.scalar() or 0)
