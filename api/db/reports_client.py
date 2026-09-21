from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import String, and_, func, select

from api.db.base_client import BaseDBClient
from api.db.models import WorkflowModel, WorkflowRunModel


class ReportsClient(BaseDBClient):
    async def get_workflow_runs_for_daily_report(
        self,
        organization_id: int,
        start_utc: datetime,
        end_utc: datetime,
        workflow_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Optimized method for daily reports - fetches only required JSON fields.
        Uses PostgreSQL JSON operators to extract only needed fields from JSON columns.

        Args:
            organization_id: The organization ID to filter by
            start_utc: Start datetime in UTC
            end_utc: End datetime in UTC
            workflow_id: Optional workflow ID to filter by

        Returns:
            List of dictionaries with report-specific fields
        """
        async with self.async_session() as session:
            # Select only the specific JSON fields needed for daily reports
            # Using PostgreSQL's JSON operators to extract specific fields
            query = (
                select(
                    WorkflowRunModel.id,
                    WorkflowRunModel.workflow_id,
                    WorkflowRunModel.created_at,
                    WorkflowRunModel.call_type,
                    WorkflowRunModel.call_summary,
                    WorkflowRunModel.recording_url,
                    WorkflowRunModel.transcript_url,
                    WorkflowRunModel.action_items,
                    WorkflowRunModel.sentiment,
                    # Provider callbacks (e.g. Vobiz ring/hangup) for the unified
                    # export — hangup event carries UUID, times, billable
                    # seconds, hangup cause and cost.
                    WorkflowRunModel.logs["telephony_status_callbacks"].label(
                        "provider_callbacks"
                    ),
                    # Live log events as transcript fallback when no stored
                    # transcript file exists.
                    WorkflowRunModel.logs["realtime_feedback_events"].label(
                        "transcript_events"
                    ),
                    # Extract only specific fields from JSON columns
                    # Use TRIM and REPLACE to remove any quotes from JSON values
                    func.coalesce(
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.gathered_context[
                                        "mapped_call_disposition"
                                    ],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        "UNKNOWN",
                    ).label("disposition"),
                    func.coalesce(
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.gathered_context[
                                        "customer_phone_number"
                                    ],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.initial_context["phone_number"],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        # Inbound calls store caller/called numbers instead.
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.initial_context["caller_number"],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.initial_context["called_number"],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        "",
                    ).label("phone_number"),
                    func.coalesce(
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.usage_info[
                                        "call_duration_seconds"
                                    ],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        func.replace(
                            func.replace(
                                func.cast(
                                    WorkflowRunModel.cost_info[
                                        "call_duration_seconds"
                                    ],
                                    String,
                                ),
                                '"',
                                "",
                            ),
                            "'",
                            "",
                        ),
                        "0",
                    ).label("call_duration_seconds"),
                    WorkflowModel.name.label("workflow_name"),
                )
                .select_from(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    and_(
                        WorkflowModel.organization_id == organization_id,
                        WorkflowRunModel.created_at >= start_utc,
                        WorkflowRunModel.created_at <= end_utc,
                    )
                )
            )

            if workflow_id is not None:
                query = query.where(WorkflowRunModel.workflow_id == workflow_id)

            result = await session.execute(query)
            rows = result.all()

            return [
                {
                    "id": row.id,
                    "workflow_id": row.workflow_id,
                    "workflow_name": row.workflow_name,
                    "created_at": row.created_at,
                    "call_type": row.call_type,
                    "call_summary": row.call_summary,
                    "recording_url": row.recording_url,
                    "transcript_url": row.transcript_url,
                    "action_items": row.action_items,
                    "sentiment": row.sentiment,
                    "provider_callbacks": row.provider_callbacks or [],
                    "transcript_events": row.transcript_events or [],
                    "gathered_context": {
                        "mapped_call_disposition": row.disposition,
                        "customer_phone_number": row.phone_number,  # Also provide it here for compatibility
                    },
                    "usage_info": {"call_duration_seconds": row.call_duration_seconds},
                    "initial_context": {"phone_number": row.phone_number},
                }
                for row in rows
            ]

    async def get_workflows_for_organization(
        self, organization_id: int
    ) -> List[WorkflowModel]:
        """
        Get all workflows for an organization.

        Args:
            organization_id: The organization ID
        """
        async with self.async_session() as session:
            query = (
                select(WorkflowModel)
                .where(WorkflowModel.organization_id == organization_id)
                .order_by(WorkflowModel.name)
            )

            result = await session.execute(query)
            return result.scalars().all()
