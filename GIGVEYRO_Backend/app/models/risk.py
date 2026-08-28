import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.db.base import Base
from app.models.wallet import MONEY


class RiskPolicy(Base):
    __tablename__ = "risk_policies"
    __table_args__ = (
        CheckConstraint("minimum_reserve_ratio_bps BETWEEN 0 AND 50000", name="ck_risk_min_ratio"),
        CheckConstraint(
            "warning_reserve_ratio_bps BETWEEN minimum_reserve_ratio_bps AND 50000",
            name="ck_risk_warning_ratio",
        ),
        CheckConstraint(
            "max_treasury_data_age_seconds BETWEEN 30 AND 86400", name="ck_risk_freshness"
        ),
        Index(
            "uq_risk_policy_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id")
    )

    reserve_coverage_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    minimum_reserve_ratio_bps: Mapped[int] = mapped_column(
        Integer, default=10000, server_default="10000", nullable=False
    )
    warning_reserve_ratio_bps: Mapped[int] = mapped_column(
        Integer, default=11000, server_default="11000", nullable=False
    )
    max_treasury_data_age_seconds: Mapped[int] = mapped_column(
        Integer, default=300, server_default="300", nullable=False
    )
    single_deal_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    max_single_deal_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    user_exposure_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    max_user_exposure_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    pending_withdrawals_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    max_pending_withdrawals_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    total_open_deals_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    max_total_open_deals_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    minimum_external_reserve_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    minimum_external_usdt_reserve: Mapped[Decimal | None] = mapped_column(MONEY)


class TreasurySnapshotRecord(Base):
    __tablename__ = "treasury_snapshots"
    __table_args__ = (
        CheckConstraint(
            "external_bybit_usdt >= 0 AND external_bybit_usdc >= 0",
            name="ck_treasury_external_nonnegative",
        ),
        Index("ix_treasury_snapshots_generated", "generated_at"),
        Index("ix_treasury_snapshots_status_generated", "risk_status", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    external_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False)
    external_bybit_usdt: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0"), nullable=False
    )
    external_bybit_usdc: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0"), nullable=False
    )
    internal_user_liability_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    merchant_liability_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    frozen_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    pending_withdrawal_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    open_deal_exposure_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    owner_profit_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    required_reserve_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserve_surplus_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserve_deficit_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    coverage_ratio_bps: Mapped[int | None] = mapped_column(Integer)
    risk_status: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
