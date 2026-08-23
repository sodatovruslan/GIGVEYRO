"""deal rate snapshot metadata

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("rate_source", sa.String(length=64), nullable=True))
    op.add_column(
        "deals", sa.Column("rate_timestamp", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "deals", sa.Column("rate_policy_version", sa.String(length=64), nullable=True)
    )
    op.add_column("deals", sa.Column("rate_mode", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "rate_mode")
    op.drop_column("deals", "rate_policy_version")
    op.drop_column("deals", "rate_timestamp")
    op.drop_column("deals", "rate_source")
