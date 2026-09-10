"""add merchant invoices and link deposits to invoices

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    money = sa.Numeric(20, 8)

    op.execute(
        "CREATE TYPE invoice_status AS ENUM "
        "('pending_payment', 'paid', 'expired', 'cancelled')"
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(20), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("external_reference", sa.String(255)),
        sa.Column("deposit_address", sa.String(128), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending_payment",
                "paid",
                "expired",
                "cancelled",
                name="invoice_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending_payment",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("amount > 0", name="ck_invoices_amount_positive"),
        sa.ForeignKeyConstraint(["merchant_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_public_id", "invoices", ["public_id"], unique=True)
    op.create_index("ix_invoices_merchant_id", "invoices", ["merchant_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_index("ix_invoices_expires_at", "invoices", ["expires_at"])
    op.create_index("ix_invoices_created_at", "invoices", ["created_at"])

    op.add_column(
        "deposits", sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_deposits_invoice_id", "deposits", "invoices", ["invoice_id"], ["id"]
    )
    op.create_index("ix_deposits_invoice_id", "deposits", ["invoice_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_deposits_invoice_id", table_name="deposits")
    op.drop_constraint("fk_deposits_invoice_id", "deposits", type_="foreignkey")
    op.drop_column("deposits", "invoice_id")

    op.drop_index("ix_invoices_created_at", table_name="invoices")
    op.drop_index("ix_invoices_expires_at", table_name="invoices")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_merchant_id", table_name="invoices")
    op.drop_index("ix_invoices_public_id", table_name="invoices")
    op.drop_table("invoices")

    op.execute("DROP TYPE invoice_status")
