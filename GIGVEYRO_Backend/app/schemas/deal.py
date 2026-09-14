import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.deal import DealStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.schemas.common import Money


class DealCreate(BaseModel):
    amount_tjs: Money = Field(gt=0)


class DealAccept(BaseModel):
    payment_requisite_id: uuid.UUID


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    merchant_id: uuid.UUID
    user_id: uuid.UUID | None
    payment_requisite_id: uuid.UUID | None
    status: DealStatus
    amount_tjs: Money
    exchange_rate: Money | None
    amount_usdt: Money | None
    rate_source: str | None
    rate_timestamp: datetime | None
    rate_policy_version: str | None
    rate_mode: str | None
    requisite_type: PaymentRequisiteType | None
    requisite_bank_name: str | None
    requisite_holder_name: str | None
    requisite_masked_card_number: str | None
    expires_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    merchant_settlement_amount: Money | None
    user_profit_amount: Money | None


class DealListResponse(BaseModel):
    items: list[DealRead]
    total: int
    limit: int
    offset: int


class OwnerDealRead(DealRead):
    """Adds the platform's own retained margin - not shown to USER/MERCHANT."""

    owner_profit_amount: Money | None


class OwnerDealListResponse(BaseModel):
    items: list[OwnerDealRead]
    total: int
    limit: int
    offset: int
