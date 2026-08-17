"""add_merchant_withdrawals

Revision ID: e74a19d2c8f1
Revises: d83e29f1b2c4
Create Date: 2025-05-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e74a19d2c8f1"
down_revision: str | None = "d83e29f1b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Extend balance_bucket ENUM and ledger_entry_type ENUM
    op.execute("ALTER TYPE ledger_balance_bucket ADD VALUE IF NOT EXISTS 'held'")
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'withdrawal_hold'")
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'withdrawal_release'")
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'withdrawal_paid'")

    # 2. Add held_balance to merchant_wallets
    op.add_column(
        "merchant_wallets",
        sa.Column(
            "held_balance", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_merchant_wallets_held_non_negative", "merchant_wallets", "held_balance >= 0"
    )

    # 3. Add held columns to ledger_entries
    op.add_column(
        "ledger_entries",
        sa.Column(
            "held_before", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "ledger_entries",
        sa.Column(
            "held_after", sa.Numeric(precision=20, scale=8), server_default="0", nullable=False
        ),
    )

    # 4. Create ENUMs for withdrawals
    op.execute(
        "CREATE TYPE withdrawal_status AS ENUM "
        "('pending', 'approved', 'paid', 'rejected', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE withdrawal_destination_type AS ENUM ('usdt_trc20_address', 'bybit_uid')"
    )

    # 5. Create merchant_withdrawals table
    op.create_table(
        "merchant_withdrawals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actioned_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_merchant_withdrawals_amount_positive"),
        sa.ForeignKeyConstraint(
            ["actioned_by_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["merchant_wallet_id"],
            ["merchant_wallets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_merchant_withdrawals_created_at"),
        "merchant_withdrawals",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchant_withdrawals_merchant_id"),
        "merchant_withdrawals",
        ["merchant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchant_withdrawals_merchant_wallet_id"),
        "merchant_withdrawals",
        ["merchant_wallet_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchant_withdrawals_public_id"),
        "merchant_withdrawals",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_merchant_withdrawals_status"), "merchant_withdrawals", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_merchant_withdrawals_status"), table_name="merchant_withdrawals")
    op.drop_index(op.f("ix_merchant_withdrawals_public_id"), table_name="merchant_withdrawals")
    op.drop_index(
        op.f("ix_merchant_withdrawals_merchant_wallet_id"), table_name="merchant_withdrawals"
    )
    op.drop_index(op.f("ix_merchant_withdrawals_merchant_id"), table_name="merchant_withdrawals")
    op.drop_index(op.f("ix_merchant_withdrawals_created_at"), table_name="merchant_withdrawals")
    op.drop_table("merchant_withdrawals")

    op.execute("DROP TYPE withdrawal_status")
    op.execute("DROP TYPE withdrawal_destination_type")

    op.drop_column("ledger_entries", "held_after")
    op.drop_column("ledger_entries", "held_before")

    op.drop_constraint("ck_merchant_wallets_held_non_negative", "merchant_wallets", type_="check")
    op.drop_column("merchant_wallets", "held_balance")
