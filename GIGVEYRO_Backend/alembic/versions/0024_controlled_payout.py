"""controlled payout state machine

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(20, 8)
    op.create_table(
        "payout_policies",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payouts_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("auto_approval_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("default_required_approvals", sa.Integer(), server_default="1", nullable=False),
        sa.Column("dual_approval_threshold_usdt", money),
        sa.Column(
            "high_value_required_approvals", sa.Integer(), server_default="2", nullable=False
        ),
        sa.Column(
            "max_single_payout_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_single_payout_usdt", money),
        sa.Column(
            "max_daily_payout_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_daily_payout_usdt", money),
        sa.Column(
            "max_hourly_payout_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_hourly_payout_usdt", money),
        sa.Column(
            "max_pending_payout_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_pending_payout_usdt", money),
        sa.Column(
            "max_asset_exposure_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("max_asset_exposure_usdt", money),
        sa.Column("created_by_account_id", uuid, sa.ForeignKey("accounts.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "default_required_approvals BETWEEN 1 AND 2", name="ck_payout_default_approvals"
        ),
        sa.CheckConstraint(
            "high_value_required_approvals BETWEEN 1 AND 2", name="ck_payout_high_approvals"
        ),
    )
    op.create_index("ix_payout_policies_status", "payout_policies", ["status"])
    op.create_index(
        "uq_payout_policy_active",
        "payout_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "payout_intents",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "withdrawal_id",
            uuid,
            sa.ForeignKey("merchant_withdrawals.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requester_account_id", uuid, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("beneficiary_account_id", uuid, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("masked_destination", sa.String(255), nullable=False),
        sa.Column("fee_amount", money, server_default="0", nullable=False),
        sa.Column("risk_policy_version", sa.Integer(), nullable=False),
        sa.Column("risk_decision", sa.String(16), nullable=False),
        sa.Column("risk_reason", sa.String(64)),
        sa.Column("treasury_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_policy_version", sa.Integer(), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("provider_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("simulation_outcome", sa.String(16)),
        sa.Column("external_reference", sa.String(128), unique=True),
        sa.Column("failure_kind", sa.String(32)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("execution_started_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_payout_intent_amount_positive"),
    )
    op.create_index("ix_payout_intents_status", "payout_intents", ["status"])
    op.create_index("ix_payout_intents_beneficiary", "payout_intents", ["beneficiary_account_id"])
    op.create_index("ix_payout_intents_created", "payout_intents", ["created_at"])
    op.create_table(
        "payout_approvals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("payout_intent_id", uuid, sa.ForeignKey("payout_intents.id"), nullable=False),
        sa.Column("approver_account_id", uuid, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "payout_intent_id", "approver_account_id", name="uq_payout_approval_approver"
        ),
    )
    op.create_index("ix_payout_approvals_intent", "payout_approvals", ["payout_intent_id"])
    op.create_table(
        "payout_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("payout_intent_id", uuid, sa.ForeignKey("payout_intents.id"), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("actor_account_id", uuid, sa.ForeignKey("accounts.id")),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payout_events_intent", "payout_events", ["payout_intent_id"])
    op.create_index("ix_payout_events_event", "payout_events", ["event"])
    op.execute(
        "INSERT INTO payout_policies (id, version, status, activated_at) "
        "VALUES (gen_random_uuid(), 1, 'active', now())"
    )


def downgrade() -> None:
    op.drop_table("payout_events")
    op.drop_table("payout_approvals")
    op.drop_table("payout_intents")
    op.drop_index("uq_payout_policy_active", table_name="payout_policies")
    op.drop_index("ix_payout_policies_status", table_name="payout_policies")
    op.drop_table("payout_policies")
