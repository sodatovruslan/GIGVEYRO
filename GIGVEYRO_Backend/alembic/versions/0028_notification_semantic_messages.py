"""add semantic notification message contract

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("message_key", sa.String(100), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("message_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_notifications_message_key", "notifications", ["message_key"])


def downgrade() -> None:
    op.drop_index("ix_notifications_message_key", table_name="notifications")
    op.drop_column("notifications", "message_params")
    op.drop_column("notifications", "message_key")
