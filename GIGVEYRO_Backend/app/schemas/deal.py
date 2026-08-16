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


class DealListResponse(BaseModel):
    items: list[DealRead]
    total: int
    limit: int
    offset: int
