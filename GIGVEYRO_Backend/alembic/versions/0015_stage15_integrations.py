"""stage15_integrations

Revision ID: 0015
Revises: stage13_notif
Create Date: 2025-02-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "stage13_notif"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    correlation_status_enum = postgresql.ENUM(
        "MATCHED", "AMBIGUOUS", "UNMATCHED", name="correlation_status"
    )
    correlation_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "unmatched_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tx_hash", sa.String(length=128), nullable=False),
        sa.Column("from_address", sa.String(length=128), nullable=False),
        sa.Column("to_address", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("asset_contract", sa.String(length=128), nullable=False),
        sa.Column(
            "correlation_status",
            postgresql.ENUM(
                "MATCHED", "AMBIGUOUS", "UNMATCHED", name="correlation_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_unmatched_transfers_created_at"),
        "unmatched_transfers",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_unmatched_transfers_tx_hash"), "unmatched_transfers", ["tx_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_unmatched_transfers_tx_hash"), table_name="unmatched_transfers")
    op.drop_index(op.f("ix_unmatched_transfers_created_at"), table_name="unmatched_transfers")
    op.drop_table("unmatched_transfers")

    correlation_status_enum = postgresql.ENUM(
        "MATCHED", "AMBIGUOUS", "UNMATCHED", name="correlation_status"
    )
    correlation_status_enum.drop(op.get_bind(), checkfirst=True)
