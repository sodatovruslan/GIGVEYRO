import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.models.wallet import MONEY


class LedgerEntry(Base):
    """Append-only financial audit trail for both UserWallets and MerchantWallets.
    Never updated or deleted by the application - a mistaken operation gets a compensating entry instead.

    For UserWallet entries: wallet_id is populated.
    For MerchantWallet entries: merchant_wallet_id is populated.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id", "idempotency_key", name="uq_ledger_entries_wallet_idempotency_key"
        ),
        UniqueConstraint(
            "merchant_wallet_id",
            "idempotency_key",
            name="uq_ledger_entries_merchant_idempotency_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=True, index=True
    )
    merchant_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchant_wallets.id"), nullable=True, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    type: Mapped[LedgerEntryType] = mapped_column(
        SAEnum(
            LedgerEntryType,
            values_callable=lambda enum: [member.value for member in enum],
            name="ledger_entry_type",
        ),
        nullable=False,
        index=True,
    )
    balance_bucket: Mapped[BalanceBucket] = mapped_column(
        SAEnum(
            BalanceBucket,
            values_callable=lambda enum: [member.value for member in enum],
            name="ledger_balance_bucket",
        ),
        nullable=False,
    )
    currency: Mapped[Currency] = mapped_column(
        SAEnum(
            Currency,
            values_callable=lambda enum: [member.value for member in enum],
            name="wallet_currency",
        ),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    available_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    available_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    insurance_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    insurance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    frozen_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    frozen_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))

    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        index=True,
    )
