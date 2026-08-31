"""secure telegram linking and delivery

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_telegram_link_tokens_account_id", "telegram_link_tokens", ["account_id"])
    op.create_index("ix_telegram_link_tokens_token_hash", "telegram_link_tokens", ["token_hash"])
    op.create_index("ix_telegram_link_tokens_expires_at", "telegram_link_tokens", ["expires_at"])

    with op.batch_alter_table("telegram_account_links") as batch:
        batch.drop_constraint(
            "telegram_account_links_telegram_user_id_key", type_="unique"
        )
        batch.drop_constraint("telegram_account_links_chat_id_key", type_="unique")
        batch.add_column(sa.Column("telegram_username", sa.String(64)))
        batch.add_column(sa.Column("telegram_first_name", sa.String(128)))
        batch.add_column(sa.Column("language", sa.String(2), server_default="ru", nullable=False))
        batch.add_column(
            sa.Column("delivery_enabled", sa.Boolean(), server_default="true", nullable=False)
        )
        batch.add_column(sa.Column("linked_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_delivery_success_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_error_category", sa.String(32)))
        batch.drop_column("verification_code_hash")
        batch.drop_column("verification_expires_at")
    op.create_index(
        "uq_telegram_link_active_user",
        "telegram_account_links",
        ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text("is_linked IS TRUE"),
    )
    op.create_index(
        "uq_telegram_link_active_chat",
        "telegram_account_links",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("is_linked IS TRUE"),
    )

    with op.batch_alter_table("notifications") as batch:
        batch.add_column(
            sa.Column("in_app_visible", sa.Boolean(), server_default="true", nullable=False)
        )

    with op.batch_alter_table("notification_deliveries") as batch:
        batch.add_column(sa.Column("last_error_code", sa.String(32)))
        batch.add_column(sa.Column("telegram_connection_id", postgresql.UUID(as_uuid=True)))
        batch.create_foreign_key(
            "fk_notification_delivery_telegram_connection",
            "telegram_account_links",
            ["telegram_connection_id"],
            ["id"],
        )
        batch.create_index(
            "ix_notification_deliveries_telegram_connection_id", ["telegram_connection_id"]
        )

    with op.batch_alter_table("notification_outbox") as batch:
        batch.add_column(sa.Column("notification_id", postgresql.UUID(as_uuid=True)))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_notification_outbox_notification",
            "notifications",
            ["notification_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_notification_outbox_notification_id", ["notification_id"])
    op.create_index(
        "uq_notification_outbox_notification",
        "notification_outbox",
        ["notification_id"],
        unique=True,
        postgresql_where=sa.text("notification_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notification_outbox_notification", table_name="notification_outbox")
    with op.batch_alter_table("notification_outbox") as batch:
        batch.drop_index("ix_notification_outbox_notification_id")
        batch.drop_constraint("fk_notification_outbox_notification", type_="foreignkey")
        batch.drop_column("next_attempt_at")
        batch.drop_column("notification_id")

    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_index("ix_notification_deliveries_telegram_connection_id")
        batch.drop_constraint("fk_notification_delivery_telegram_connection", type_="foreignkey")
        batch.drop_column("telegram_connection_id")
        batch.drop_column("last_error_code")

    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("in_app_visible")

    op.drop_index("uq_telegram_link_active_chat", table_name="telegram_account_links")
    op.drop_index("uq_telegram_link_active_user", table_name="telegram_account_links")
    op.execute(
        sa.text(
            "UPDATE telegram_account_links SET telegram_user_id = NULL, chat_id = NULL "
            "WHERE is_linked IS NOT TRUE"
        )
    )
    with op.batch_alter_table("telegram_account_links") as batch:
        batch.add_column(sa.Column("verification_code_hash", sa.String(64)))
        batch.add_column(sa.Column("verification_expires_at", sa.DateTime(timezone=True)))
        batch.drop_column("last_error_category")
        batch.drop_column("last_delivery_success_at")
        batch.drop_column("disabled_at")
        batch.drop_column("last_seen_at")
        batch.drop_column("linked_at")
        batch.drop_column("delivery_enabled")
        batch.drop_column("language")
        batch.drop_column("telegram_first_name")
        batch.drop_column("telegram_username")
        batch.create_unique_constraint(
            "telegram_account_links_telegram_user_id_key", ["telegram_user_id"]
        )
        batch.create_unique_constraint(
            "telegram_account_links_chat_id_key", ["chat_id"]
        )

    op.drop_table("telegram_link_tokens")
