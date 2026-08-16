"""add_deal_appeals

Revision ID: f92b38c4d1e2
Revises: e74a19d2c8f1
Create Date: 2025-05-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f92b38c4d1e2'
down_revision: Union[str, None] = 'e74a19d2c8f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ENUMs for appeals
    op.execute("CREATE TYPE appeal_status AS ENUM ('open', 'under_review', 'resolved', 'cancelled')")
    op.execute("CREATE TYPE appeal_reason AS ENUM ('payment_not_received', 'wrong_amount', 'payment_proof_issue', 'timeout_dispute', 'other')")
    op.execute("CREATE TYPE appeal_resolution AS ENUM ('settle_to_merchant', 'release_to_user')")

    # 2. Create deal_appeals table
    op.create_table(
        'deal_appeals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('public_id', sa.String(length=16), nullable=False),
        sa.Column('deal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('opened_by_account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('opened_by_role', postgresql.ENUM('owner', 'user', 'merchant', name='user_role', create_type=False), nullable=False),
        sa.Column('reason_code', postgresql.ENUM('payment_not_received', 'wrong_amount', 'payment_proof_issue', 'timeout_dispute', 'other', name='appeal_reason', create_type=False), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', postgresql.ENUM('open', 'under_review', 'resolved', 'cancelled', name='appeal_status', create_type=False), nullable=False),
        sa.Column('resolution', postgresql.ENUM('settle_to_merchant', 'release_to_user', name='appeal_resolution', create_type=False), nullable=True),
        sa.Column('owner_note', sa.Text(), nullable=True),
        sa.Column('previous_deal_status', postgresql.ENUM('created', 'available', 'accepted', 'payment_pending', 'completed', 'cancelled', 'expired', 'disputed', name='deal_status', create_type=False), nullable=False),
        sa.Column('resolved_by_account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
        sa.ForeignKeyConstraint(['opened_by_account_id'], ['accounts.id'], ),
        sa.ForeignKeyConstraint(['resolved_by_account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deal_appeals_created_at'), 'deal_appeals', ['created_at'], unique=False)
    op.create_index(op.f('ix_deal_appeals_deal_id'), 'deal_appeals', ['deal_id'], unique=False)
    op.create_index(op.f('ix_deal_appeals_opened_by_account_id'), 'deal_appeals', ['opened_by_account_id'], unique=False)
    op.create_index(op.f('ix_deal_appeals_public_id'), 'deal_appeals', ['public_id'], unique=True)
    op.create_index(op.f('ix_deal_appeals_reason_code'), 'deal_appeals', ['reason_code'], unique=False)
    op.create_index(op.f('ix_deal_appeals_status'), 'deal_appeals', ['status'], unique=False)

    op.create_index(
        'uq_deal_appeals_active_deal',
        'deal_appeals',
        ['deal_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'under_review')")
    )


def downgrade() -> None:
    op.drop_index('uq_deal_appeals_active_deal', table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_status'), table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_reason_code'), table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_public_id'), table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_opened_by_account_id'), table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_deal_id'), table_name='deal_appeals')
    op.drop_index(op.f('ix_deal_appeals_created_at'), table_name='deal_appeals')
    op.drop_table('deal_appeals')

    op.execute("DROP TYPE appeal_resolution")
    op.execute("DROP TYPE appeal_reason")
    op.execute("DROP TYPE appeal_status")
