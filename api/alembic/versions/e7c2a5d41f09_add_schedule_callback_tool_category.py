"""add schedule_callback tool category

Revision ID: e7c2a5d41f09
Revises: d58f3c1a9042
Create Date: 2026-09-18

"""

from typing import Sequence, Union

from alembic import op
from alembic_postgresql_enum import TableReference

# revision identifiers, used by Alembic.
revision: str = "e7c2a5d41f09"
down_revision: Union[str, None] = "d58f3c1a9042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.sync_enum_values(
        enum_schema="public",
        enum_name="tool_category",
        new_values=[
            "http_api",
            "end_call",
            "transfer_call",
            "schedule_callback",
            "native",
            "integration",
        ],
        affected_columns=[
            TableReference(
                table_schema="public", table_name="tools", column_name="category"
            )
        ],
        enum_values_to_rename=[],
    )


def downgrade() -> None:
    op.sync_enum_values(
        enum_schema="public",
        enum_name="tool_category",
        new_values=["http_api", "end_call", "transfer_call", "native", "integration"],
        affected_columns=[
            TableReference(
                table_schema="public", table_name="tools", column_name="category"
            )
        ],
        enum_values_to_rename=[],
    )
