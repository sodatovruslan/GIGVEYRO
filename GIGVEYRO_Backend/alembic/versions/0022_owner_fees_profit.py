"""versioned owner fees and immutable profit ledger

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-28 00:00:00.000000
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

money = sa.Numeric(20, 8, asdecimal=True)
policy_id = uuid.UUID("00000000-0000-0000-0000-000000000022")


def upgrade() -> None:
    op.create_table(
        "fee_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('draft','active','retired')", name="ck_fee_policy_status"),
    )
    op.create_index("ix_fee_policies_status", "fee_policies", ["status"])
    op.create_index(
        "uq_fee_policy_single_active",
        "fee_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "fee_policy_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fee_policies.id"),
            nullable=False,
        ),
        sa.Column("fee_type", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("percent_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fixed_fee", money, nullable=False, server_default="0"),
        sa.Column("min_fee", money),
        sa.Column("max_fee", money),
        sa.Column("payer", sa.String(16)),
        sa.UniqueConstraint("policy_id", "fee_type", name="uq_fee_component_policy_type"),
        sa.CheckConstraint("percent_bps >= 0 AND percent_bps <= 5000", name="ck_fee_component_bps"),
        sa.CheckConstraint("fixed_fee >= 0", name="ck_fee_component_fixed"),
        sa.CheckConstraint("min_fee IS NULL OR min_fee >= 0", name="ck_fee_component_min"),
        sa.CheckConstraint("max_fee IS NULL OR max_fee >= 0", name="ck_fee_component_max"),
        sa.CheckConstraint(
            "min_fee IS NULL OR max_fee IS NULL OR min_fee <= max_fee",
            name="ck_fee_component_bounds",
        ),
    )
    op.create_index("ix_fee_policy_components_policy_id", "fee_policy_components", ["policy_id"])
    op.create_index("ix_fee_policy_components_fee_type", "fee_policy_components", ["fee_type"])

    op.create_table(
        "fee_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fee_policies.id"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fee_type", sa.String(40), nullable=False),
        sa.Column("payer", sa.String(16)),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("gross_amount", money, nullable=False),
        sa.Column("percent_bps", sa.Integer(), nullable=False),
        sa.Column("percent_fee", money, nullable=False),
        sa.Column("fixed_fee", money, nullable=False),
        sa.Column("fee_amount", money, nullable=False),
        sa.Column("net_amount", money, nullable=False),
        sa.Column("reference_rate", money),
        sa.Column("effective_rate", money),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.UniqueConstraint("source_type", "source_id", "fee_type", name="uq_fee_snapshot_source"),
        sa.CheckConstraint(
            "gross_amount >= 0 AND fee_amount >= 0 AND net_amount >= 0",
            name="ck_fee_snapshot_amounts",
        ),
        sa.CheckConstraint(
            "gross_amount = fee_amount + net_amount", name="ck_fee_snapshot_balanced"
        ),
    )
    for name, columns in (
        ("ix_fee_snapshots_policy_version", ["policy_version"]),
        ("ix_fee_snapshots_source_type", ["source_type"]),
        ("ix_fee_snapshots_source_id", ["source_id"]),
        ("ix_fee_snapshots_fee_type", ["fee_type"]),
        ("ix_fee_snapshots_currency", ["currency"]),
        ("ix_fee_snapshots_created_at", ["created_at"]),
    ):
        op.create_index(name, "fee_snapshots", columns)

    op.create_table(
        "owner_profit_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "fee_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fee_snapshots.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fee_type", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("gross_amount", money, nullable=False),
        sa.Column("fee_amount", money, nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.UniqueConstraint("fee_snapshot_id", name="uq_profit_fee_snapshot"),
        sa.UniqueConstraint("source_type", "source_id", "fee_type", name="uq_profit_source"),
        sa.CheckConstraint("gross_amount > 0 AND fee_amount > 0", name="ck_profit_positive"),
    )
    for name, columns in (
        ("ix_owner_profit_entries_source_type", ["source_type"]),
        ("ix_owner_profit_entries_source_id", ["source_id"]),
        ("ix_owner_profit_entries_fee_type", ["fee_type"]),
        ("ix_owner_profit_entries_currency", ["currency"]),
        ("ix_owner_profit_entries_policy_version", ["policy_version"]),
        ("ix_owner_profit_entries_created_at", ["created_at"]),
        ("ix_profit_source_lookup", ["source_type", "source_id"]),
    ):
        op.create_index(name, "owner_profit_entries", columns)

    for _, column in (
        ("reference_rate", sa.Column("reference_rate", money)),
        ("effective_rate", sa.Column("effective_rate", money)),
        ("gross_destination_amount", sa.Column("gross_destination_amount", money)),
        ("fee_amount", sa.Column("fee_amount", money, nullable=False, server_default="0")),
        (
            "fee_policy_version",
            sa.Column("fee_policy_version", sa.Integer(), nullable=False, server_default="0"),
        ),
    ):
        op.add_column("fiat_conversions", column)
    op.execute(
        "UPDATE fiat_conversions SET reference_rate = exchange_rate, "
        "effective_rate = exchange_rate, gross_destination_amount = destination_amount"
    )
    op.alter_column("fiat_conversions", "reference_rate", nullable=False)
    op.alter_column("fiat_conversions", "effective_rate", nullable=False)
    op.alter_column("fiat_conversions", "gross_destination_amount", nullable=False)

    now = datetime(2026, 8, 28, tzinfo=UTC)
    policies = sa.table(
        "fee_policies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("activated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        policies,
        [
            {
                "id": policy_id,
                "version": 1,
                "status": "active",
                "effective_from": now,
                "created_at": now,
                "activated_at": now,
            }
        ],
    )
    components = sa.table(
        "fee_policy_components",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("policy_id", postgresql.UUID(as_uuid=True)),
        sa.column("fee_type", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("percent_bps", sa.Integer()),
        sa.column("fixed_fee", money),
        sa.column("payer", sa.String()),
    )
    op.bulk_insert(
        components,
        [
            {
                "id": uuid.UUID(f"00000000-0000-0000-0001-00000000000{index}"),
                "policy_id": policy_id,
                "fee_type": fee_type,
                "enabled": False,
                "percent_bps": 0,
                "fixed_fee": 0,
                "payer": payer,
            }
            for index, (fee_type, payer) in enumerate(
                (
                    ("deal_fee", None),
                    ("fiat_conversion_spread", "USER"),
                    ("withdrawal_fee", None),
                    ("merchant_fee", None),
                ),
                start=1,
            )
        ],
    )


def downgrade() -> None:
    for column in (
        "fee_policy_version",
        "fee_amount",
        "gross_destination_amount",
        "effective_rate",
        "reference_rate",
    ):
        op.drop_column("fiat_conversions", column)
    op.drop_table("owner_profit_entries")
    op.drop_table("fee_snapshots")
    op.drop_table("fee_policy_components")
    op.drop_table("fee_policies")
