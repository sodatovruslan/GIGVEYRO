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
    """Append-only financial audit trail. Never updated or deleted by the
    application - a mistaken operation gets a compensating entry instead.

    Every row stores a full 3-bucket snapshot of the wallet (available/
    insurance/frozen before and after), not just the bucket that changed,
    so any single entry can be read as a complete point-in-time statement
    of the wallet without replaying history. `balance_bucket` says which
    bucket `amount` was applied to; `amount` is the signed delta for that
    bucket (positive = credit, negative = debit).
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        # Plain UNIQUE is sufficient for idempotency: Postgres never treats
        # two NULLs as equal, so any number of entries with no idempotency
        # key are still allowed - only a real duplicate key is rejected.
        UniqueConstraint(
            "wallet_id", "idempotency_key", name="uq_ledger_entries_wallet_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False, index=True
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
    insurance_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    insurance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    frozen_before: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    frozen_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    # clock_timestamp() (actual wall-clock time per statement), not now()
    # (frozen at transaction start) - a transaction that appends several
    # entries must not have them collide on the same timestamp.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        index=True,
    )
