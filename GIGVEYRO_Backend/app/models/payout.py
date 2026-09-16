import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.db.base import Base
from app.models.wallet import MONEY


class PayoutPolicy(Base):
    __tablename__ = "payout_policies"
    __table_args__ = (
        CheckConstraint(
            "default_required_approvals BETWEEN 1 AND 2", name="ck_payout_default_approvals"
        ),
        CheckConstraint(
            "high_value_required_approvals BETWEEN 1 AND 2", name="ck_payout_high_approvals"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_approval_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_required_approvals: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dual_approval_threshold_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    high_value_required_approvals: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_single_payout_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_single_payout_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    max_daily_payout_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_daily_payout_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    max_hourly_payout_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_hourly_payout_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    max_pending_payout_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_pending_payout_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    max_asset_exposure_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_asset_exposure_usdt: Mapped[Decimal | None] = mapped_column(MONEY)
    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PayoutIntent(Base):
    __tablename__ = "payout_intents"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payout_intent_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    withdrawal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchant_withdrawals.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    requester_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    beneficiary_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_destination: Mapped[str] = mapped_column(String(255), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    risk_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_reason: Mapped[str | None] = mapped_column(String(64))
    treasury_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(32), default="disabled", nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_outcome: Mapped[str | None] = mapped_column(String(16))
    external_reference: Mapped[str | None] = mapped_column(String(128), unique=True)
    failure_kind: Mapped[str | None] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PayoutApproval(Base):
    __tablename__ = "payout_approvals"
    __table_args__ = (
        UniqueConstraint(
            "payout_intent_id", "approver_account_id", name="uq_payout_approval_approver"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payout_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payout_intents.id"), nullable=False, index=True
    )
    approver_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PayoutEvent(Base):
    __tablename__ = "payout_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payout_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payout_intents.id"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id")
    )
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PayoutDestination(Base):
    """Immutable approved destination, scoped to the specific beneficiary
    account it was registered for. Disable and recreate instead of editing.
    A destination is unique per (beneficiary, fingerprint) - not globally -
    since each USER supplies their own TRC20 address independently."""

    __tablename__ = "payout_destinations"
    __table_args__ = (
        Index(
            "uq_payout_destination_enabled_fingerprint",
            "beneficiary_account_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("enabled"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    asset: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    network: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_address: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    beneficiary_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    created_by_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disabled_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PayoutNetwork(Base):
    __tablename__ = "payout_networks"
    __table_args__ = (UniqueConstraint("asset", "network", name="uq_payout_network_asset_network"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disabled_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
