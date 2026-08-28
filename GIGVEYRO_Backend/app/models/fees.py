import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.wallet import MONEY


class FeePolicy(Base):
    __tablename__ = "fee_policies"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','retired')", name="ck_fee_policy_status"),
        Index(
            "uq_fee_policy_single_active",
            "status",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    components: Mapped[list["FeePolicyComponent"]] = relationship(
        back_populates="policy", lazy="selectin", cascade="all, delete-orphan"
    )


class FeePolicyComponent(Base):
    __tablename__ = "fee_policy_components"
    __table_args__ = (
        UniqueConstraint("policy_id", "fee_type", name="uq_fee_component_policy_type"),
        CheckConstraint("percent_bps >= 0 AND percent_bps <= 5000", name="ck_fee_component_bps"),
        CheckConstraint("fixed_fee >= 0", name="ck_fee_component_fixed"),
        CheckConstraint("min_fee IS NULL OR min_fee >= 0", name="ck_fee_component_min"),
        CheckConstraint("max_fee IS NULL OR max_fee >= 0", name="ck_fee_component_max"),
        CheckConstraint(
            "min_fee IS NULL OR max_fee IS NULL OR min_fee <= max_fee",
            name="ck_fee_component_bounds",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fee_policies.id"), nullable=False, index=True
    )
    fee_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    percent_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    min_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    max_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    payer: Mapped[str | None] = mapped_column(String(16))
    policy: Mapped[FeePolicy] = relationship(back_populates="components")


class FeeSnapshot(Base):
    __tablename__ = "fee_snapshots"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "fee_type", name="uq_fee_snapshot_source"),
        CheckConstraint(
            "gross_amount >= 0 AND fee_amount >= 0 AND net_amount >= 0",
            name="ck_fee_snapshot_amounts",
        ),
        CheckConstraint("gross_amount = fee_amount + net_amount", name="ck_fee_snapshot_balanced"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fee_policies.id"), nullable=False
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    fee_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payer: Mapped[str | None] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    percent_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    percent_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fixed_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    effective_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp(), index=True
    )


class OwnerProfitEntry(Base):
    __tablename__ = "owner_profit_entries"
    __table_args__ = (
        UniqueConstraint("fee_snapshot_id", name="uq_profit_fee_snapshot"),
        UniqueConstraint("source_type", "source_id", "fee_type", name="uq_profit_source"),
        CheckConstraint("gross_amount > 0 AND fee_amount > 0", name="ck_profit_positive"),
        Index("ix_profit_source_lookup", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fee_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fee_snapshots.id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    fee_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp(), index=True
    )
