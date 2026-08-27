"""managed fiat wallets and owner conversions

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

wallet_currency = postgresql.ENUM("USDT", "TJS", "RUB", name="wallet_currency", create_type=False)
fiat_entry_type = postgresql.ENUM(
    "owner_allocation",
    "conversion_debit",
    "conversion_credit",
    name="fiat_ledger_entry_type",
    create_type=False,
)
money = sa.Numeric(20, 8, asdecimal=True)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE wallet_currency ADD VALUE IF NOT EXISTS 'TJS'")
        op.execute("ALTER TYPE wallet_currency ADD VALUE IF NOT EXISTS 'RUB'")

    fiat_entry_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "fiat_wallet_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("currency", wallet_currency, nullable=False),
        sa.Column("available", money, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "account_id", "currency", name="uq_fiat_balance_account_currency"
        ),
        sa.CheckConstraint(
            "available >= 0", name="ck_fiat_balance_available_non_negative"
        ),
        sa.CheckConstraint(
            "currency::text IN ('TJS', 'RUB')", name="ck_fiat_balance_managed_currency"
        ),
    )
    op.create_index(
        "ix_fiat_wallet_balances_account_id", "fiat_wallet_balances", ["account_id"]
    )

    op.create_table(
        "fiat_conversions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "initiated_by_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("from_currency", wallet_currency, nullable=False),
        sa.Column("to_currency", wallet_currency, nullable=False),
        sa.Column("source_amount", money, nullable=False),
        sa.Column("destination_amount", money, nullable=False),
        sa.Column("exchange_rate", money, nullable=False),
        sa.Column("source_balance_before", money, nullable=False),
        sa.Column("source_balance_after", money, nullable=False),
        sa.Column("destination_balance_before", money, nullable=False),
        sa.Column("destination_balance_after", money, nullable=False),
        sa.Column("rate_provider", sa.String(64), nullable=False),
        sa.Column("rate_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate_policy_version", sa.String(64), nullable=False),
        sa.Column("rate_mode", sa.String(24), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.UniqueConstraint(
            "initiated_by_account_id",
            "idempotency_key",
            name="uq_fiat_conversion_actor_idempotency",
        ),
        sa.CheckConstraint("source_amount > 0", name="ck_fiat_conversion_source_positive"),
        sa.CheckConstraint(
            "destination_amount > 0", name="ck_fiat_conversion_dest_positive"
        ),
        sa.CheckConstraint("exchange_rate > 0", name="ck_fiat_conversion_rate_positive"),
        sa.CheckConstraint("from_currency <> to_currency", name="ck_fiat_conversion_distinct"),
    )
    op.create_index("ix_fiat_conversions_account_id", "fiat_conversions", ["account_id"])
    op.create_index(
        "ix_fiat_conversions_initiated_by_account_id",
        "fiat_conversions",
        ["initiated_by_account_id"],
    )
    op.create_index("ix_fiat_conversions_created_at", "fiat_conversions", ["created_at"])

    op.create_table(
        "fiat_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "balance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fiat_wallet_balances.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("currency", wallet_currency, nullable=False),
        sa.Column("type", fiat_entry_type, nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("balance_before", money, nullable=False),
        sa.Column("balance_after", money, nullable=False),
        sa.Column("reference_type", sa.String(40), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "created_by_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.UniqueConstraint(
            "balance_id", "idempotency_key", name="uq_fiat_ledger_balance_idempotency"
        ),
        sa.UniqueConstraint(
            "created_by_account_id",
            "idempotency_key",
            name="uq_fiat_ledger_actor_idempotency",
        ),
        sa.UniqueConstraint(
            "reference_id", "type", name="uq_fiat_ledger_reference_type"
        ),
    )
    op.create_index("ix_fiat_ledger_entries_balance_id", "fiat_ledger_entries", ["balance_id"])
    op.create_index("ix_fiat_ledger_entries_account_id", "fiat_ledger_entries", ["account_id"])
    op.create_index("ix_fiat_ledger_entries_type", "fiat_ledger_entries", ["type"])
    op.create_index("ix_fiat_ledger_entries_created_at", "fiat_ledger_entries", ["created_at"])


def downgrade() -> None:
    op.drop_table("fiat_ledger_entries")
    op.drop_table("fiat_conversions")
    op.drop_table("fiat_wallet_balances")
    fiat_entry_type.drop(op.get_bind(), checkfirst=True)

    # PostgreSQL cannot remove enum labels. Recreate the shared USDT-only type
    # after the managed-fiat tables have been removed.
    op.execute("ALTER TABLE wallets ALTER COLUMN currency TYPE text USING currency::text")
    op.execute(
        "ALTER TABLE merchant_wallets ALTER COLUMN currency TYPE text USING currency::text"
    )
    op.execute("ALTER TABLE ledger_entries ALTER COLUMN currency TYPE text USING currency::text")
    op.execute(
        "ALTER TABLE merchant_withdrawals ALTER COLUMN currency TYPE text USING currency::text"
    )
    op.execute("DROP TYPE wallet_currency")
    op.execute("CREATE TYPE wallet_currency AS ENUM ('USDT')")
    op.execute(
        "ALTER TABLE wallets ALTER COLUMN currency TYPE wallet_currency "
        "USING currency::wallet_currency"
    )
    op.execute(
        "ALTER TABLE merchant_wallets ALTER COLUMN currency TYPE wallet_currency "
        "USING currency::wallet_currency"
    )
    op.execute(
        "ALTER TABLE ledger_entries ALTER COLUMN currency TYPE wallet_currency "
        "USING currency::wallet_currency"
    )
    op.execute(
        "ALTER TABLE merchant_withdrawals ALTER COLUMN currency TYPE wallet_currency "
        "USING currency::wallet_currency"
    )
