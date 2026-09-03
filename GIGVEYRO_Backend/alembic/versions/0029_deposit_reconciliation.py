"""add owner unmatched deposit reconciliation

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "unmatched_transfers",
        sa.Column("provider", sa.String(32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "unmatched_transfers",
        sa.Column("network", sa.String(16), nullable=False, server_default="TRC20"),
    )
    op.add_column(
        "unmatched_transfers",
        sa.Column("confirmations", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "unmatched_transfers",
        sa.Column("is_finalized", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("unmatched_transfers", sa.Column("block_number", sa.Integer()))
    op.add_column("unmatched_transfers", sa.Column("block_timestamp", sa.DateTime(timezone=True)))
    op.add_column(
        "unmatched_transfers",
        sa.Column(
            "reconciliation_status",
            sa.String(32),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "unmatched_transfers",
        sa.Column("linked_deposit_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "unmatched_transfers",
        sa.Column("resolved_by_account_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("unmatched_transfers", sa.Column("resolution_reason", sa.Text()))
    op.add_column("unmatched_transfers", sa.Column("last_result_code", sa.String(64)))
    op.add_column("unmatched_transfers", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column(
        "unmatched_transfers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_unmatched_transfers_linked_deposit",
        "unmatched_transfers",
        "deposits",
        ["linked_deposit_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_unmatched_transfers_resolved_by",
        "unmatched_transfers",
        "accounts",
        ["resolved_by_account_id"],
        ["id"],
    )
    op.create_index(
        "ix_unmatched_transfers_reconciliation_status",
        "unmatched_transfers",
        ["reconciliation_status"],
    )
    op.create_index(
        "ix_unmatched_transfers_linked_deposit_id",
        "unmatched_transfers",
        ["linked_deposit_id"],
    )

    op.create_table(
        "deposit_reconciliation_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("deposit_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_code", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["deposit_id"], ["deposits.id"]),
        sa.ForeignKeyConstraint(["transfer_id"], ["unmatched_transfers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_account_id",
            "idempotency_key",
            name="uq_deposit_reconciliation_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_deposit_reconciliation_actions_transfer_id",
        "deposit_reconciliation_actions",
        ["transfer_id"],
    )
    op.create_index(
        "ix_deposit_reconciliation_actions_actor_account_id",
        "deposit_reconciliation_actions",
        ["actor_account_id"],
    )


def downgrade() -> None:
    op.drop_table("deposit_reconciliation_actions")
    op.drop_index("ix_unmatched_transfers_linked_deposit_id", table_name="unmatched_transfers")
    op.drop_index("ix_unmatched_transfers_reconciliation_status", table_name="unmatched_transfers")
    op.drop_constraint(
        "fk_unmatched_transfers_resolved_by", "unmatched_transfers", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_unmatched_transfers_linked_deposit", "unmatched_transfers", type_="foreignkey"
    )
    for column in (
        "updated_at",
        "resolved_at",
        "last_result_code",
        "resolution_reason",
        "resolved_by_account_id",
        "linked_deposit_id",
        "reconciliation_status",
        "block_timestamp",
        "block_number",
        "is_finalized",
        "confirmations",
        "network",
        "provider",
    ):
        op.drop_column("unmatched_transfers", column)
