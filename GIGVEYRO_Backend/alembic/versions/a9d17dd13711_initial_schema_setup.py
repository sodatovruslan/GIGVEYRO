"""initial schema setup

Revision ID: a9d17dd13711
Revises: 
Create Date: 2026-08-15 12:22:38.889726

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'a9d17dd13711'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
