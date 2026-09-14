"""add deal profit distribution

Revision ID: 0035
Revises: 0034
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=20, scale=8)


def upgrade() -> None:
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'deal_user_profit'")

    op.add_column("deals", sa.Column("merchant_settlement_amount", MONEY, nullable=True))
    op.add_column("deals", sa.Column("user_profit_amount", MONEY, nullable=True))
    op.add_column("deals", sa.Column("owner_profit_amount", MONEY, nullable=True))
    op.create_check_constraint(
        "ck_deals_merchant_settlement_amount_positive",
        "deals",
        "merchant_settlement_amount IS NULL OR merchant_settlement_amount > 0",
    )
    op.create_check_constraint(
        "ck_deals_user_profit_amount_non_negative",
        "deals",
        "user_profit_amount IS NULL OR user_profit_amount >= 0",
    )
    op.create_check_constraint(
        "ck_deals_owner_profit_amount_non_negative",
        "deals",
        "owner_profit_amount IS NULL OR owner_profit_amount >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_owner_profit_amount_non_negative", "deals", type_="check")
    op.drop_constraint("ck_deals_user_profit_amount_non_negative", "deals", type_="check")
    op.drop_constraint("ck_deals_merchant_settlement_amount_positive", "deals", type_="check")
    op.drop_column("deals", "owner_profit_amount")
    op.drop_column("deals", "user_profit_amount")
    op.drop_column("deals", "merchant_settlement_amount")
    # ledger_entry_type enum value additions are not reversible in Postgres.
