"""add stable TronGrid provider event identity

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("deposits") as batch:
        batch.add_column(sa.Column("provider_event_id", sa.String(192), nullable=True))
        batch.drop_constraint("deposits_tx_hash_key", type_="unique")
    op.execute(
        sa.text(
            "UPDATE deposits SET provider_event_id = :prefix || tx_hash || :suffix "
            "WHERE tx_hash IS NOT NULL"
        ).bindparams(prefix="legacy:", suffix=":0")
    )
    op.create_index("ix_deposits_tx_hash", "deposits", ["tx_hash"], unique=False)
    op.create_index(
        "ix_deposits_provider_event_id",
        "deposits",
        ["provider_event_id"],
        unique=True,
    )

    op.add_column(
        "unmatched_transfers",
        sa.Column("provider_event_id", sa.String(192), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE unmatched_transfers "
            "SET provider_event_id = :prefix || tx_hash || :suffix"
        ).bindparams(prefix="legacy:", suffix=":0")
    )
    op.alter_column("unmatched_transfers", "provider_event_id", nullable=False)
    op.drop_index("ix_unmatched_transfers_tx_hash", table_name="unmatched_transfers")
    op.create_index(
        "ix_unmatched_transfers_tx_hash",
        "unmatched_transfers",
        ["tx_hash"],
        unique=False,
    )
    op.create_index(
        "ix_unmatched_transfers_provider_event_id",
        "unmatched_transfers",
        ["provider_event_id"],
        unique=True,
    )


def downgrade() -> None:
    # Downgrade cannot represent multiple events from one transaction in the legacy schema.
    connection = op.get_bind()
    duplicate_deposits = connection.execute(
        sa.text(
            "SELECT 1 FROM deposits WHERE tx_hash IS NOT NULL "
            "GROUP BY tx_hash HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    duplicate_unmatched = connection.execute(
        sa.text(
            "SELECT 1 FROM unmatched_transfers GROUP BY tx_hash HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_deposits or duplicate_unmatched:
        raise RuntimeError("0027 downgrade would lose multi-event transaction identity")

    op.drop_index(
        "ix_unmatched_transfers_provider_event_id", table_name="unmatched_transfers"
    )
    op.drop_index("ix_unmatched_transfers_tx_hash", table_name="unmatched_transfers")
    op.create_index(
        "ix_unmatched_transfers_tx_hash",
        "unmatched_transfers",
        ["tx_hash"],
        unique=True,
    )
    op.drop_column("unmatched_transfers", "provider_event_id")

    op.drop_index("ix_deposits_provider_event_id", table_name="deposits")
    op.drop_index("ix_deposits_tx_hash", table_name="deposits")
    with op.batch_alter_table("deposits") as batch:
        batch.create_unique_constraint("deposits_tx_hash_key", ["tx_hash"])
        batch.drop_column("provider_event_id")
