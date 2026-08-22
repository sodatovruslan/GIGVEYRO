"""two factor auth

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_two_factor",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="totp"),
        sa.Column("encrypted_secret", sa.String(length=255), nullable=False),
        sa.Column(
            "enabled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index(
        op.f("ix_account_two_factor_account_id"),
        "account_two_factor",
        ["account_id"],
        unique=True,
    )

    op.create_table(
        "two_factor_pending_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_secret", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index(
        op.f("ix_two_factor_pending_setups_account_id"),
        "two_factor_pending_setups",
        ["account_id"],
        unique=True,
    )

    op.create_table(
        "two_factor_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_two_factor_recovery_codes_account_id"),
        "two_factor_recovery_codes",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_two_factor_recovery_codes_code_hash"),
        "two_factor_recovery_codes",
        ["code_hash"],
        unique=False,
    )

    op.create_table(
        "two_factor_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_two_factor_challenges_account_id"),
        "two_factor_challenges",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_two_factor_challenges_consumed_at"),
        "two_factor_challenges",
        ["consumed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_two_factor_challenges_consumed_at"), table_name="two_factor_challenges")
    op.drop_index(op.f("ix_two_factor_challenges_account_id"), table_name="two_factor_challenges")
    op.drop_table("two_factor_challenges")

    op.drop_index(
        op.f("ix_two_factor_recovery_codes_code_hash"), table_name="two_factor_recovery_codes"
    )
    op.drop_index(
        op.f("ix_two_factor_recovery_codes_account_id"), table_name="two_factor_recovery_codes"
    )
    op.drop_table("two_factor_recovery_codes")

    op.drop_index(
        op.f("ix_two_factor_pending_setups_account_id"), table_name="two_factor_pending_setups"
    )
    op.drop_table("two_factor_pending_setups")

    op.drop_index(op.f("ix_account_two_factor_account_id"), table_name="account_two_factor")
    op.drop_table("account_two_factor")
