import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.wallet import Currency
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.wallet import MONEY


class UserWithdrawal(Base):
    """A USER's direct USDT withdrawal request - same status/approval shape
    as MerchantWithdrawal (kept as a separate table/service rather than
    generalizing MerchantWithdrawal, since the merchant payout path is
    wired into the controlled multi-approval payout state machine and
    isn't safe to reshape for a second caller)."""

    __tablename__ = "user_withdrawals"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_user_withdrawals_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False, index=True
    )

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SAEnum(
            Currency,
            values_callable=lambda enum: [member.value for member in enum],
            name="wallet_currency",
        ),
        nullable=False,
        default=Currency.USDT,
    )

    destination_type: Mapped[WithdrawalDestinationType] = mapped_column(
        SAEnum(
            WithdrawalDestinationType,
            values_callable=lambda enum: [member.value for member in enum],
            name="withdrawal_destination_type",
        ),
        nullable=False,
    )
    destination: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[WithdrawalStatus] = mapped_column(
        SAEnum(
            WithdrawalStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="withdrawal_status",
        ),
        nullable=False,
        index=True,
        default=WithdrawalStatus.PENDING,
    )

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    actioned_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
