import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.wallet import Currency

# NUMERIC(20, 8): enough headroom for large allocations while keeping 8
# fractional digits, matching typical USDT/crypto precision. Decimal only -
# money is never represented as float anywhere in this codebase.
MONEY = Numeric(20, 8, asdecimal=True)


class UserWallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("available_balance >= 0", name="ck_wallets_available_non_negative"),
        CheckConstraint("insurance_balance >= 0", name="ck_wallets_insurance_non_negative"),
        CheckConstraint("frozen_balance >= 0", name="ck_wallets_frozen_non_negative"),
        CheckConstraint(
            "insurance_reserve_basis >= 0", name="ck_wallets_insurance_reserve_basis_non_negative"
        ),
        CheckConstraint("insurance_target >= 0", name="ck_wallets_insurance_target_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    currency: Mapped[Currency] = mapped_column(
        SAEnum(
            Currency,
            values_callable=lambda enum: [member.value for member in enum],
            name="wallet_currency",
        ),
        nullable=False,
        default=Currency.USDT,
    )
    available_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    insurance_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    frozen_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    # Historical: high-water mark from the retired percentage-based reserve
    # model (migration 0037). No longer read or written by any code path -
    # kept in the schema only so existing data isn't destroyed. The live
    # enforcement mechanism is insurance_target below.
    insurance_reserve_basis: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    # Fixed, absolute, Owner-set floor for this USER's insurance_balance
    # (migration 0039) - not a percentage, not balance-derived. Deposits fill
    # the gap between insurance_balance and this target before anything goes
    # to available_balance (WalletService.credit_deposit); insurance_balance
    # can never be decreased below it (WalletService._apply_bucket_change).
    # Changing this value never moves money by itself.
    insurance_target: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
