import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.webhook import WebhookDeliveryStatus, WebhookStatus


class Webhook(Base):
    """A MERCHANT-configured HTTP callback for payment events (currently
    just invoice.paid). The signing secret is stored encrypted (not
    hashed, unlike ApiKey) because delivery needs to read it back on
    every attempt to compute the HMAC signature."""

    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    event_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    status: Mapped[WebhookStatus] = mapped_column(
        SAEnum(
            WebhookStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="webhook_status",
        ),
        nullable=False,
        index=True,
        default=WebhookStatus.ACTIVE,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WebhookDelivery(Base):
    """One delivery attempt record per outbound event, polled and retried
    by app/workers/jobs/webhook_delivery.py - same pending/attempts/
    max_attempts outbox shape as RealtimeOutbox."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index(
            "idx_webhook_deliveries_pending", "status", "next_attempt_at", "attempts"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        SAEnum(
            WebhookDeliveryStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="webhook_delivery_status",
        ),
        nullable=False,
        index=True,
        default=WebhookDeliveryStatus.PENDING,
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_response_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
