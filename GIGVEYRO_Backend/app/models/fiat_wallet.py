import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.wallet import Currency, FiatLedgerEntryType
from app.models.wallet import MONEY


def _currency_enum() -> SAEnum:
    return SAEnum(
        Currency,
        values_callable=lambda enum: [member.value for member in enum],
        name="wallet_currency",
        create_type=False,
    )


class FiatWalletBalance(Base):
    __tablename__ = "fiat_wallet_balances"
    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_fiat_balance_account_currency"),
        CheckConstraint("available >= 0", name="ck_fiat_balance_available_non_negative"),
        CheckConstraint(
            "currency::text IN ('TJS', 'RUB')", name="ck_fiat_balance_managed_currency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    currency: Mapped[Currency] = mapped_column(_currency_enum(), nullable=False)
    available: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class FiatConversion(Base):
    __tablename__ = "fiat_conversions"
    __table_args__ = (
        UniqueConstraint(
            "initiated_by_account_id",
            "idempotency_key",
            name="uq_fiat_conversion_actor_idempotency",
        ),
        CheckConstraint("source_amount > 0", name="ck_fiat_conversion_source_positive"),
        CheckConstraint("destination_amount > 0", name="ck_fiat_conversion_dest_positive"),
        CheckConstraint("exchange_rate > 0", name="ck_fiat_conversion_rate_positive"),
        CheckConstraint("from_currency <> to_currency", name="ck_fiat_conversion_distinct"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    initiated_by_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    from_currency: Mapped[Currency] = mapped_column(_currency_enum(), nullable=False)
    to_currency: Mapped[Currency] = mapped_column(_currency_enum(), nullable=False)
    source_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    destination_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    effective_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    gross_destination_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    fee_policy_version: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    source_balance_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    source_balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    destination_balance_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    destination_balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rate_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp(), index=True
    )


class FiatLedgerEntry(Base):
    __tablename__ = "fiat_ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "balance_id", "idempotency_key", name="uq_fiat_ledger_balance_idempotency"
        ),
        UniqueConstraint(
            "created_by_account_id",
            "idempotency_key",
            name="uq_fiat_ledger_actor_idempotency",
        ),
        UniqueConstraint("reference_id", "type", name="uq_fiat_ledger_reference_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    balance_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fiat_wallet_balances.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    currency: Mapped[Currency] = mapped_column(_currency_enum(), nullable=False)
    type: Mapped[FiatLedgerEntryType] = mapped_column(
        SAEnum(
            FiatLedgerEntryType,
            values_callable=lambda enum: [member.value for member in enum],
            name="fiat_ledger_entry_type",
        ),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp(), index=True
    )
