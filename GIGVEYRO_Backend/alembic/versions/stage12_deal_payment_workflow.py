"""stage12_deal_payment_workflow

Revision ID: stage12_deal_payment_workflow
Revises: f92b38c4d1e2
Create Date: 2026-03-31 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage12_deal_payment_workflow"
down_revision: str | None = "f92b38c4d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("merchant_marked_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("user_confirmed_received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("user_rejected_payment_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("payment_reference", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("payment_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deals", "payment_note")
    op.drop_column("deals", "payment_reference")
    op.drop_column("deals", "user_rejected_payment_at")
    op.drop_column("deals", "user_confirmed_received_at")
    op.drop_column("deals", "merchant_marked_paid_at")
