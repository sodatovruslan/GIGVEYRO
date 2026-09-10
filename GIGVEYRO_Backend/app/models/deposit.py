import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositNetwork,
    DepositStatus,
    ReconciliationActionType,
    ReconciliationStatus,
)
from app.models.wallet import MONEY


class Deposit(Base):
    """A USER's (or, when invoice_id is set, a MERCHANT invoice's) intent
    to deposit USDT/TRC20 to the platform's single shared address, plus
    the on-chain transaction later matched to it.
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
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id"), unique=True, nullable=True, index=True
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

    deposit_address: Mapped[str] = mapped_column(String(128), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(
        String(192), unique=True, nullable=True, index=True
    )

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


class UnmatchedTransfer(Base):
    """Stores incoming transfers that could not be safely correlated to a deposit intent."""

    __tablename__ = "unmatched_transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_event_id: Mapped[str] = mapped_column(
        String(192), unique=True, nullable=False, index=True
    )
    from_address: Mapped[str] = mapped_column(String(128), nullable=False)
    to_address: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    asset_contract: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    network: Mapped[DepositNetwork] = mapped_column(
        SAEnum(
            DepositNetwork,
            values_callable=lambda enum: [member.value for member in enum],
            native_enum=False,
            length=16,
        ),
        nullable=False,
        default=DepositNetwork.TRC20,
    )
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correlation_status: Mapped[CorrelationStatus] = mapped_column(
        SAEnum(
            CorrelationStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="correlation_status",
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        SAEnum(ReconciliationStatus, native_enum=False, length=32),
        nullable=False,
        default=ReconciliationStatus.PENDING,
        index=True,
    )
    linked_deposit_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deposits.id"), nullable=True, index=True
    )
    resolved_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_result_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DepositReconciliationAction(Base):
    __tablename__ = "deposit_reconciliation_actions"
    __table_args__ = (
        UniqueConstraint(
            "actor_account_id",
            "idempotency_key",
            name="uq_deposit_reconciliation_actor_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("unmatched_transfers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    action: Mapped[ReconciliationActionType] = mapped_column(
        SAEnum(ReconciliationActionType, native_enum=False, length=24), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deposit_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deposits.id"), nullable=True
    )
    result_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
