"""scope payout destinations to a beneficiary account

Revision ID: 0038
Revises: 0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    # payout_destinations has always been empty in every environment observed
    # so far (Owner never registered one) - safe to add NOT NULL directly,
    # no backfill needed. If a future environment somehow has rows, this
    # migration fails loudly rather than silently guessing a beneficiary.
    op.add_column(
        "payout_destinations",
        sa.Column("beneficiary_account_id", uuid, sa.ForeignKey("accounts.id"), nullable=False),
    )
    op.create_index(
        "ix_payout_destinations_beneficiary", "payout_destinations", ["beneficiary_account_id"]
    )
    # A destination is now unique per (beneficiary, address) rather than
    # globally - two different users are each allowed to withdraw to
    # whatever address they supplied, even if (in the rare case) it were
    # the same one.
    op.drop_index("uq_payout_destination_enabled_fingerprint", table_name="payout_destinations")
    op.create_index(
        "uq_payout_destination_enabled_fingerprint",
        "payout_destinations",
        ["beneficiary_account_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index("uq_payout_destination_enabled_fingerprint", table_name="payout_destinations")
    op.create_index(
        "uq_payout_destination_enabled_fingerprint",
        "payout_destinations",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )
    op.drop_index("ix_payout_destinations_beneficiary", table_name="payout_destinations")
    op.drop_column("payout_destinations", "beneficiary_account_id")
