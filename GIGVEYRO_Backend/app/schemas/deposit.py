import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositNetwork,
    DepositStatus,
    ReconciliationActionType,
    ReconciliationStatus,
)
from app.schemas.common import Money


class DepositCreate(BaseModel):
    amount: Money = Field(gt=0)


class DepositRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    account_id: uuid.UUID
    network: DepositNetwork
    asset: DepositAsset
    expected_amount: Money
    received_amount: Money | None
    credited_amount: Money | None
    deposit_address: str
    tx_hash: str | None
    confirmations: int
    required_confirmations: int
    status: DepositStatus
    expires_at: datetime
    detected_at: datetime | None
    confirmed_at: datetime | None
    credited_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DepositListResponse(BaseModel):
    items: list[DepositRead]
    total: int
    limit: int
    offset: int


class UnmatchedTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tx_hash: str
    provider_event_id: str
    provider: str
    from_address: str
    to_address: str
    amount: Money
    asset_contract: str
    network: DepositNetwork
    confirmations: int
    is_finalized: bool
    block_number: int | None
    block_timestamp: datetime | None
    correlation_status: CorrelationStatus
    reconciliation_status: ReconciliationStatus
    reason: str
    linked_deposit_id: uuid.UUID | None
    resolution_reason: str | None
    last_result_code: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("from_address")
    def mask_sender(self, value: str) -> str:
        if len(value) <= 12:
            return "***"
        return f"{value[:6]}…{value[-6:]}"


class DepositCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    account_id: uuid.UUID
    expected_amount: Money
    network: DepositNetwork
    asset: DepositAsset
    status: DepositStatus
    expires_at: datetime
    amount_matches: bool
    amount_difference: Money


class DepositReconciliationActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: ReconciliationActionType
    deposit_id: uuid.UUID | None
    result_code: str
    created_at: datetime


class UnmatchedTransferDetail(UnmatchedTransferRead):
    candidates: list[DepositCandidateRead]
    history: list[DepositReconciliationActionRead]


class DepositReconciliationLink(BaseModel):
    deposit_id: uuid.UUID
    idempotency_key: str = Field(min_length=8, max_length=128)


class DepositReconciliationCommand(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class DepositReconciliationIgnore(DepositReconciliationCommand):
    reason: str = Field(min_length=5, max_length=500)


class DepositReconciliationResultRead(BaseModel):
    result_code: str
    replayed: bool
    transfer: UnmatchedTransferRead
    deposit: DepositRead | None


class UnmatchedTransferListResponse(BaseModel):
    items: list[UnmatchedTransferRead]
    total: int
    limit: int
    offset: int


class DepositSimulateTransaction(BaseModel):
    """DEV-only: represents what a (mock, in Stage 8) blockchain listener
    observed - never accepted from an untrusted client in production."""

    tx_hash: str = Field(min_length=1, max_length=128)
    amount: Money = Field(gt=0)
    confirmations: int = Field(ge=0)
    network: DepositNetwork = DepositNetwork.TRC20
    asset: DepositAsset = DepositAsset.USDT
    destination_address: str = Field(min_length=1, max_length=128)
