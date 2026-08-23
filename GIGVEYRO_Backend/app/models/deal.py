import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.deal import DealStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.models.wallet import MONEY


class Deal(Base):
    """A MERCHANT-created TJS payment request that an eligible USER accepts.
    `requisite_*` columns are an immutable snapshot of the PaymentRequisite
    used, captured at accept time - the live PaymentRequisite can later be
    edited/deactivated/archived without altering deal history.
    """

    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("amount_tjs > 0", name="ck_deals_amount_tjs_positive"),
        CheckConstraint(
            "amount_usdt IS NULL OR amount_usdt > 0", name="ck_deals_amount_usdt_positive"
        ),
        CheckConstraint(
            "exchange_rate IS NULL OR exchange_rate > 0", name="ck_deals_exchange_rate_positive"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True, index=True
    )
    payment_requisite_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payment_requisites.id"), nullable=True
    )

    amount_tjs: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    exchange_rate: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    amount_usdt: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    rate_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rate_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rate_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)

    status: Mapped[DealStatus] = mapped_column(
        SAEnum(
            DealStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="deal_status",
        ),
        nullable=False,
        index=True,
        default=DealStatus.CREATED,
    )

    # Immutable requisite snapshot, filled in at accept time. Reuses the
    # Stage 6 payment_requisite_type ENUM - never masked_card_number's
    # source card_number, only its already-masked public form.
    requisite_type: Mapped[PaymentRequisiteType | None] = mapped_column(
        SAEnum(
            PaymentRequisiteType,
            values_callable=lambda enum: [member.value for member in enum],
            name="payment_requisite_type",
        ),
        nullable=True,
    )
    requisite_bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requisite_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requisite_masked_card_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
