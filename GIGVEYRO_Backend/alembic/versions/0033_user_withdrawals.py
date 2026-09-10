"""add user withdrawals

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    money = sa.Numeric(20, 8)

    op.create_table(
        "user_withdrawals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(16), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column(
            "currency",
            postgresql.ENUM("USDT", "TJS", "RUB", name="wallet_currency", create_type=False),
            nullable=False,
            server_default="USDT",
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
        sa.Column("destination", sa.String(255), nullable=False),
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
            server_default="pending",
        ),
        sa.Column("comment", sa.Text()),
        sa.Column("owner_comment", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actioned_by_account_id", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint("amount > 0", name="ck_user_withdrawals_amount_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["actioned_by_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_withdrawals_public_id", "user_withdrawals", ["public_id"], unique=True)
    op.create_index("ix_user_withdrawals_user_id", "user_withdrawals", ["user_id"])
    op.create_index("ix_user_withdrawals_wallet_id", "user_withdrawals", ["wallet_id"])
    op.create_index("ix_user_withdrawals_status", "user_withdrawals", ["status"])
    op.create_index("ix_user_withdrawals_created_at", "user_withdrawals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_withdrawals_created_at", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_status", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_wallet_id", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_user_id", table_name="user_withdrawals")
    op.drop_index("ix_user_withdrawals_public_id", table_name="user_withdrawals")
    op.drop_table("user_withdrawals")
