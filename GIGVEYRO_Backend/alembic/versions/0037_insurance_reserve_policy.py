"""insurance reserve policy and per-wallet high-water-mark basis

Revision ID: 0037
Revises: 0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=20, scale=8)


def upgrade() -> None:
    op.add_column(
        "wallets",
        sa.Column(
            "insurance_reserve_basis", MONEY, nullable=False, server_default="0"
        ),
    )
    op.create_check_constraint(
        "ck_wallets_insurance_reserve_basis_non_negative",
        "wallets",
        "insurance_reserve_basis >= 0",
    )
    # Existing wallets must not silently lose reserve protection the moment
    # the policy is enabled: their current insurance_balance is the only
    # historical high-water-mark we actually know, so it becomes the initial
    # basis. Wallets with zero insurance correctly start at a zero basis.
    op.execute("UPDATE wallets SET insurance_reserve_basis = insurance_balance")

    op.create_table(
        "insurance_reserve_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "minimum_reserve_percentage", sa.Numeric(5, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "created_by_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "minimum_reserve_percentage BETWEEN 0 AND 100",
            name="ck_insurance_reserve_percentage",
        ),
    )
    op.create_index(
        "ix_insurance_reserve_policies_status", "insurance_reserve_policies", ["status"]
    )
    op.create_index(
        "uq_insurance_reserve_policy_active",
        "insurance_reserve_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    # Seeded disabled: this is a brand-new business rule, so it must never
    # change existing production behaviour the moment this migration lands -
    # an Owner must explicitly enable it (see validate_controlled_payout /
    # risk_policies seeding for the same established convention).
    op.execute(
        "INSERT INTO insurance_reserve_policies "
        "(id, version, status, enabled, minimum_reserve_percentage, activated_at) "
        "VALUES (gen_random_uuid(), 1, 'active', false, 0, now())"
    )


def downgrade() -> None:
    op.drop_index("uq_insurance_reserve_policy_active", table_name="insurance_reserve_policies")
    op.drop_index("ix_insurance_reserve_policies_status", table_name="insurance_reserve_policies")
    op.drop_table("insurance_reserve_policies")
    op.drop_constraint(
        "ck_wallets_insurance_reserve_basis_non_negative", "wallets", type_="check"
    )
    op.drop_column("wallets", "insurance_reserve_basis")
