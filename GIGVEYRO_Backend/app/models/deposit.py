import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.models.wallet import MONEY


class Deposit(Base):
    """A USER's intent to deposit USDT/TRC20 to the platform's single
    shared address, plus the (mock, in Stage 8) on-chain transaction later
    matched to it by deposit_id. See the Stage 8 report for why a shared
    address needs this Deposit Intent correlation model instead of
    matching incoming transfers by amount alone.
    """

    __tablename__ = "deposits"
    __table_args__ = (
        CheckConstraint("expected_amount > 0", name="ck_deposits_expected_amount_positive"),
        CheckConstraint(
            "received_amount IS NULL OR received_amount > 0",
            name="ck_deposits_received_amount_positive",
        ),
        CheckConstraint(
            "credited_amount IS NULL OR credited_amount > 0",
            name="ck_deposits_credited_amount_positive",
        ),
        CheckConstraint("confirmations >= 0", name="ck_deposits_confirmations_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )

    network: Mapped[DepositNetwork] = mapped_column(
        SAEnum(
            DepositNetwork,
            values_callable=lambda enum: [member.value for member in enum],
            name="deposit_network",
        ),
        nullable=False,
    )
    asset: Mapped[DepositAsset] = mapped_column(
        SAEnum(
            DepositAsset,
            values_callable=lambda enum: [member.value for member in enum],
            name="deposit_asset",
        ),
        nullable=False,
    )

    expected_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    received_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    credited_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    # Snapshot of the address shown to the USER at intent creation time.
    deposit_address: Mapped[str] = mapped_column(String(128), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)

    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    required_confirmations: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[DepositStatus] = mapped_column(
        SAEnum(
            DepositStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="deposit_status",
        ),
        nullable=False,
        index=True,
        default=DepositStatus.WAITING,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
