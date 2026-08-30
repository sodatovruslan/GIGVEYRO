"""live payout security allowlists

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "payout_intents",
        sa.Column("provider_name", sa.String(32), server_default="disabled", nullable=False),
    )
    op.execute(
        "UPDATE payout_intents SET provider_name = "
        "CASE WHEN provider_mode = 'simulated' THEN 'simulator' ELSE 'disabled' END"
    )
    op.create_table(
        "payout_networks",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_account_id", uuid, sa.ForeignKey("accounts.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("disabled_by_account_id", uuid, sa.ForeignKey("accounts.id")),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("asset", "network", name="uq_payout_network_asset_network"),
    )
    op.create_index("ix_payout_networks_enabled", "payout_networks", ["enabled"])
    op.create_table(
        "payout_destinations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("masked_address", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_account_id", uuid, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("disabled_by_account_id", uuid, sa.ForeignKey("accounts.id")),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payout_destinations_asset", "payout_destinations", ["asset"])
    op.create_index("ix_payout_destinations_network", "payout_destinations", ["network"])
    op.create_index("ix_payout_destinations_enabled", "payout_destinations", ["enabled"])
    op.create_index(
        "uq_payout_destination_enabled_fingerprint",
        "payout_destinations",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )
    op.execute(
        sa.text(
            "INSERT INTO payout_networks "
            "(id, asset, network, enabled) "
            "VALUES (CAST(:id AS uuid), 'USDT', 'TRC20', true)"
        ).bindparams(id="00000000-0000-0000-0000-000000002501")
    )


def downgrade() -> None:
    op.drop_index("uq_payout_destination_enabled_fingerprint", table_name="payout_destinations")
    op.drop_index("ix_payout_destinations_enabled", table_name="payout_destinations")
    op.drop_index("ix_payout_destinations_network", table_name="payout_destinations")
    op.drop_index("ix_payout_destinations_asset", table_name="payout_destinations")
    op.drop_table("payout_destinations")
    op.drop_index("ix_payout_networks_enabled", table_name="payout_networks")
    op.drop_table("payout_networks")
    op.drop_column("payout_intents", "provider_name")
