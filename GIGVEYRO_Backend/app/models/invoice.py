import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.invoice import InvoiceStatus
from app.models.wallet import MONEY


class Invoice(Base):
    """A MERCHANT's request for a customer to pay a fixed USDT amount.

    Settled through the same TRC20 deposit pipeline USER deposits use -
    see Deposit.invoice_id for the linked deposit intent that the
    blockchain scanner matches and credits.
    """

    __tablename__ = "invoices"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_invoices_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    deposit_address: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(
            InvoiceStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="invoice_status",
        ),
        nullable=False,
        index=True,
        default=InvoiceStatus.PENDING_PAYMENT,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
