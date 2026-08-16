import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.deal import DealStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.models.wallet import MONEY


class Deal(Base):
    __tablename__ = "deals"

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

    amount_tjs: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount_usdt: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    payment_requisite_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payment_requisites.id"), nullable=True
    )
    requisite_type: Mapped[PaymentRequisiteType | None] = mapped_column(
        SAEnum(
            PaymentRequisiteType,
            values_callable=lambda enum: [member.value for member in enum],
            name="payment_requisite_type",
        ),
        nullable=True,
    )
    requisite_bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requisite_holder_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requisite_masked_card_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # -- Stage 12: Payment Workflow fields --
    merchant_marked_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_confirmed_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_rejected_payment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
