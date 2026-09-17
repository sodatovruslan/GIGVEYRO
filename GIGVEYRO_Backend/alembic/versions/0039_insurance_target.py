"""fixed per-user insurance target

Revision ID: 0039
Revises: 0038
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=20, scale=8)


def upgrade() -> None:
    # Additive only - migration 0037's insurance_reserve_basis column and
    # insurance_reserve_policies table are left in place as inert historical
    # data. Default 0 is behaviour-preserving: every existing wallet keeps
    # "deposit -> 100% available" until an Owner explicitly sets a target.
    op.add_column(
        "wallets",
        sa.Column("insurance_target", MONEY, nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_wallets_insurance_target_non_negative", "wallets", "insurance_target >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_wallets_insurance_target_non_negative", "wallets", type_="check")
    op.drop_column("wallets", "insurance_target")
