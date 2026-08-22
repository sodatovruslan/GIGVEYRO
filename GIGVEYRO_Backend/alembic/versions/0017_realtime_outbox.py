"""realtime outbox

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "realtime_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_account_ids", postgresql.JSONB(), nullable=False),
        sa.Column("recipient_roles", postgresql.JSONB(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_realtime_outbox_pending",
        "realtime_outbox",
        ["processed_at", "attempts", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_realtime_outbox_entity_id"),
        "realtime_outbox",
        ["entity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_realtime_outbox_entity_id"), table_name="realtime_outbox")
    op.drop_index("idx_realtime_outbox_pending", table_name="realtime_outbox")
    op.drop_table("realtime_outbox")
