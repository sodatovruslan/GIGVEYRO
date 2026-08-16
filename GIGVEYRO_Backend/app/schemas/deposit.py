import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
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


class DepositSimulateTransaction(BaseModel):
    """DEV-only: represents what a (mock, in Stage 8) blockchain listener
    observed - never accepted from an untrusted client in production."""

    tx_hash: str = Field(min_length=1, max_length=128)
    amount: Money = Field(gt=0)
    confirmations: int = Field(ge=0)
    network: DepositNetwork = DepositNetwork.TRC20
    asset: DepositAsset = DepositAsset.USDT
    destination_address: str = Field(min_length=1, max_length=128)
