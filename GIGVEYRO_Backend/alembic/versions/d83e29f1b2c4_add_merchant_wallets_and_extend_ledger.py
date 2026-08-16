"""add_merchant_wallets_and_extend_ledger

Revision ID: d83e29f1b2c4
Revises: cdd659866190
Create Date: 2025-05-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd83e29f1b2c4'
down_revision: Union[str, None] = 'cdd659866190'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update ledger_entry_type ENUM
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'deal_release'")
    op.execute("ALTER TYPE ledger_entry_type ADD VALUE IF NOT EXISTS 'deal_settlement_credit'")

    # 2. Create merchant_wallets table
    op.create_table(
        'merchant_wallets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('currency', sa.Enum('USDT', name='wallet_currency'), nullable=False),
        sa.Column('available_balance', sa.Numeric(precision=20, scale=8), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('available_balance >= 0', name='ck_merchant_wallets_available_non_negative'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_merchant_wallets_account_id'), 'merchant_wallets', ['account_id'], unique=True)

    # 3. Alter ledger_entries table
    op.alter_column('ledger_entries', 'wallet_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column('ledger_entries', sa.Column('merchant_wallet_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_ledger_entries_merchant_wallet_id'), 'ledger_entries', ['merchant_wallet_id'], unique=False)
    op.create_foreign_key('fk_ledger_entries_merchant_wallet_id', 'ledger_entries', 'merchant_wallets', ['merchant_wallet_id'], ['id'])
    op.create_unique_constraint('uq_ledger_entries_merchant_idempotency_key', 'ledger_entries', ['merchant_wallet_id', 'idempotency_key'])


def downgrade() -> None:
    op.drop_constraint('uq_ledger_entries_merchant_idempotency_key', 'ledger_entries', type_='unique')
    op.drop_constraint('fk_ledger_entries_merchant_wallet_id', 'ledger_entries', type_='foreignkey')
    op.drop_index(op.f('ix_ledger_entries_merchant_wallet_id'), table_name='ledger_entries')
    op.drop_column('ledger_entries', 'merchant_wallet_id')
    op.alter_column('ledger_entries', 'wallet_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_index(op.f('ix_merchant_wallets_account_id'), table_name='merchant_wallets')
    op.drop_table('merchant_wallets')
