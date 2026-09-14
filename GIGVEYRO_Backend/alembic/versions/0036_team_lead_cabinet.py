"""add team lead cabinet

Revision ID: 0036
Revises: 0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=20, scale=8)


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'team_lead'")
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'team_lead_profit'")

    op.add_column(
        "accounts",
        sa.Column("team_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_accounts_team_lead_id", "accounts", "accounts", ["team_lead_id"], ["id"]
    )
    op.create_index(
        op.f("ix_accounts_team_lead_id"), "accounts", ["team_lead_id"], unique=False
    )

    op.add_column("deals", sa.Column("team_lead_profit_amount", MONEY, nullable=True))
    op.create_check_constraint(
        "ck_deals_team_lead_profit_amount_non_negative",
        "deals",
        "team_lead_profit_amount IS NULL OR team_lead_profit_amount >= 0",
    )

    op.create_table(
        "team_lead_withdrawals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("team_lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column(
            "currency",
            postgresql.ENUM("USDT", name="wallet_currency", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "destination_type",
            postgresql.ENUM(
                "usdt_trc20_address",
                "bybit_uid",
                name="withdrawal_destination_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("destination", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "approved",
                "paid",
                "rejected",
                "cancelled",
                name="withdrawal_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("owner_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actioned_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_team_lead_withdrawals_amount_positive"),
        sa.ForeignKeyConstraint(["actioned_by_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["team_lead_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_team_lead_withdrawals_created_at"),
        "team_lead_withdrawals",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_lead_withdrawals_team_lead_id"),
        "team_lead_withdrawals",
        ["team_lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_lead_withdrawals_wallet_id"),
        "team_lead_withdrawals",
        ["wallet_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_lead_withdrawals_public_id"),
        "team_lead_withdrawals",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_team_lead_withdrawals_status"),
        "team_lead_withdrawals",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_team_lead_withdrawals_status"), table_name="team_lead_withdrawals")
    op.drop_index(op.f("ix_team_lead_withdrawals_public_id"), table_name="team_lead_withdrawals")
    op.drop_index(op.f("ix_team_lead_withdrawals_wallet_id"), table_name="team_lead_withdrawals")
    op.drop_index(op.f("ix_team_lead_withdrawals_team_lead_id"), table_name="team_lead_withdrawals")
    op.drop_index(op.f("ix_team_lead_withdrawals_created_at"), table_name="team_lead_withdrawals")
    op.drop_table("team_lead_withdrawals")

    op.drop_constraint(
        "ck_deals_team_lead_profit_amount_non_negative", "deals", type_="check"
    )
    op.drop_column("deals", "team_lead_profit_amount")

    op.drop_index(op.f("ix_accounts_team_lead_id"), table_name="accounts")
    op.drop_constraint("fk_accounts_team_lead_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "team_lead_id")
    # user_role / ledger_entry_type enum value additions are not reversible in Postgres.
