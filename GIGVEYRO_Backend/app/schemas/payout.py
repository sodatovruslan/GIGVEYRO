import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.enums.payout import PayoutSimulationOutcome


def _decimal_only(value):
    if isinstance(value, float):
        raise ValueError("binary float is not accepted")
    return value


PayoutMoney = Annotated[Decimal, BeforeValidator(_decimal_only)]


class PayoutPolicyInput(BaseModel):
    payouts_enabled: bool = False
    auto_approval_enabled: bool = False
    default_required_approvals: int = Field(default=1, ge=1, le=2)
    dual_approval_threshold_usdt: PayoutMoney | None = Field(default=None, ge=0)
    high_value_required_approvals: int = Field(default=2, ge=1, le=2)
    max_single_payout_enabled: bool = False
    max_single_payout_usdt: PayoutMoney | None = Field(default=None, ge=0)
    max_daily_payout_enabled: bool = False
    max_daily_payout_usdt: PayoutMoney | None = Field(default=None, ge=0)
    max_hourly_payout_enabled: bool = False
    max_hourly_payout_usdt: PayoutMoney | None = Field(default=None, ge=0)
    max_pending_payout_enabled: bool = False
    max_pending_payout_usdt: PayoutMoney | None = Field(default=None, ge=0)
    max_asset_exposure_enabled: bool = False
    max_asset_exposure_usdt: PayoutMoney | None = Field(default=None, ge=0)


class PayoutPolicyOut(PayoutPolicyInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    status: str
    created_at: datetime
    activated_at: datetime | None


class PayoutApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    approver_account_id: uuid.UUID
    decision: str
    intent_hash: str
    comment: str | None
    created_at: datetime


class PayoutEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event: str
    actor_account_id: uuid.UUID | None
    event_metadata: dict
    created_at: datetime


class PayoutIntentOut(BaseModel):
    id: uuid.UUID
    withdrawal_id: uuid.UUID
    beneficiary_account_id: uuid.UUID
    asset: str
    amount: Decimal
    network: str
    masked_destination: str
    fee_amount: Decimal
    risk_policy_version: int
    risk_decision: str
    risk_reason: str | None
    treasury_generated_at: datetime
    approval_policy_version: int
    required_approvals: int
    approval_count: int = 0
    provider_name: str
    provider_mode: str
    status: str
    external_reference_masked: str | None = None
    failure_kind: str | None
    failure_code: str | None
    created_at: datetime
    approved_at: datetime | None
    queued_at: datetime | None
    execution_started_at: datetime | None
    executed_at: datetime | None
    reconciled_at: datetime | None
    approvals: list[PayoutApprovalOut] = Field(default_factory=list)
    events: list[PayoutEventOut] = Field(default_factory=list)


class PayoutListOut(BaseModel):
    items: list[PayoutIntentOut]
    total: int
    limit: int
    offset: int


class PayoutCommentCommand(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class PayoutQueueCommand(BaseModel):
    outcome: PayoutSimulationOutcome = PayoutSimulationOutcome.SUCCEEDED


class PayoutReconcileCommand(BaseModel):
    outcome: PayoutSimulationOutcome | None = None


class PayoutManualCompleteCommand(BaseModel):
    external_reference: str = Field(min_length=1, max_length=128)
    evidence: str = Field(min_length=1, max_length=1000)


class PayoutDestinationInput(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    asset: str = Field(default="USDT", min_length=1, max_length=16)
    network: str = Field(default="TRC20", min_length=1, max_length=32)
    address: str = Field(min_length=1, max_length=255)


class PayoutDestinationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    asset: str
    network: str
    masked_address: str
    fingerprint: str
    enabled: bool
    created_at: datetime
    disabled_at: datetime | None


class PayoutNetworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    asset: str
    network: str
    enabled: bool
    created_at: datetime
    disabled_at: datetime | None


class LivePayoutReadinessOut(BaseModel):
    ready: bool
    capabilities: list[str]
    blocking_reasons: list[str]
    checks: dict[str, bool]
