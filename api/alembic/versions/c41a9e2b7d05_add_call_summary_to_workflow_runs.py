"""add call summary columns to workflow runs

Revision ID: c41a9e2b7d05
Revises: 9f8a1b2c3d4e
Create Date: 2026-09-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41a9e2b7d05"
down_revision: Union[str, None] = "9f8a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs", sa.Column("call_summary", sa.Text(), nullable=True)
    )
    op.add_column(
        "workflow_runs",
        sa.Column("call_summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "call_summary_generated_at")
    op.drop_column("workflow_runs", "call_summary")
