"""treasury risk policies and snapshots

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id")
        ),
        sa.Column(
            "reserve_coverage_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "minimum_reserve_ratio_bps", sa.Integer(), server_default="10000", nullable=False
        ),
        sa.Column(
            "warning_reserve_ratio_bps", sa.Integer(), server_default="11000", nullable=False
        ),
        sa.Column(
            "max_treasury_data_age_seconds", sa.Integer(), server_default="300", nullable=False
        ),
        sa.Column("single_deal_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("max_single_deal_usdt", sa.Numeric(20, 8)),
        sa.Column("user_exposure_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("max_user_exposure_usdt", sa.Numeric(20, 8)),
        sa.Column(
            "pending_withdrawals_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_pending_withdrawals_usdt", sa.Numeric(20, 8)),
        sa.Column(
            "total_open_deals_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_total_open_deals_usdt", sa.Numeric(20, 8)),
        sa.Column(
            "minimum_external_reserve_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("minimum_external_usdt_reserve", sa.Numeric(20, 8)),
        sa.CheckConstraint(
            "minimum_reserve_ratio_bps BETWEEN 0 AND 50000", name="ck_risk_min_ratio"
        ),
        sa.CheckConstraint(
            "warning_reserve_ratio_bps BETWEEN minimum_reserve_ratio_bps AND 50000",
            name="ck_risk_warning_ratio",
        ),
        sa.CheckConstraint(
            "max_treasury_data_age_seconds BETWEEN 30 AND 86400", name="ck_risk_freshness"
        ),
    )
    op.create_index("ix_risk_policies_status", "risk_policies", ["status"])
    op.create_index(
        "uq_risk_policy_active",
        "risk_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    money = sa.Numeric(20, 8)
    op.create_table(
        "treasury_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("external_observed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_status", sa.String(32), nullable=False),
        sa.Column("external_bybit_usdt", money, nullable=False),
        sa.Column("external_bybit_usdc", money, nullable=False),
        sa.Column("internal_user_liability_usdt", money, nullable=False),
        sa.Column("merchant_liability_usdt", money, nullable=False),
        sa.Column("frozen_usdt", money, nullable=False),
        sa.Column("pending_withdrawal_usdt", money, nullable=False),
        sa.Column("open_deal_exposure_usdt", money, nullable=False),
        sa.Column("owner_profit_usdt", money, nullable=False),
        sa.Column("required_reserve_usdt", money, nullable=False),
        sa.Column("reserve_surplus_usdt", money, nullable=False),
        sa.Column("reserve_deficit_usdt", money, nullable=False),
        sa.Column("coverage_ratio_bps", sa.Integer()),
        sa.Column("risk_status", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "external_bybit_usdt >= 0 AND external_bybit_usdc >= 0",
            name="ck_treasury_external_nonnegative",
        ),
    )
    op.create_index("ix_treasury_snapshots_generated", "treasury_snapshots", ["generated_at"])
    op.create_index(
        "ix_treasury_snapshots_status_generated",
        "treasury_snapshots",
        ["risk_status", "generated_at"],
    )
    op.execute(
        "INSERT INTO risk_policies "
        "(id, version, status, effective_from, activated_at) "
        "VALUES (gen_random_uuid(), 1, 'active', now(), now())"
    )


def downgrade() -> None:
    op.drop_table("treasury_snapshots")
    op.drop_index("uq_risk_policy_active", table_name="risk_policies")
    op.drop_index("ix_risk_policies_status", table_name="risk_policies")
    op.drop_table("risk_policies")
