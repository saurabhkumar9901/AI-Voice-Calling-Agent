"""add callbacks table and action_items/sentiment columns

Revision ID: d58f3c1a9042
Revises: c41a9e2b7d05
Create Date: 2026-09-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d58f3c1a9042"
down_revision: Union[str, None] = "c41a9e2b7d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "callbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="scheduled"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_callback_id", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["workflow_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_callback_id"], ["callbacks.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_callbacks_due", "callbacks", ["state", "scheduled_for"]
    )
    op.create_index(
        "ix_callbacks_organization_id", "callbacks", ["organization_id"]
    )

    op.add_column(
        "workflow_runs",
        sa.Column("action_items", sa.JSON(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("sentiment", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "sentiment")
    op.drop_column("workflow_runs", "action_items")
    op.drop_index("ix_callbacks_organization_id", table_name="callbacks")
    op.drop_index("ix_callbacks_due", table_name="callbacks")
    op.drop_table("callbacks")
