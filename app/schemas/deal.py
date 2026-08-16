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


class MerchantMarkPaidRequest(BaseModel):
    payment_reference: str | None = Field(default=None, max_length=100)
    payment_note: str | None = Field(default=None, max_length=1000)


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    merchant_id: uuid.UUID
    user_id: uuid.UUID | None
    amount_tjs: Money
    amount_usdt: Money | None
    exchange_rate: Money | None
    payment_requisite_id: uuid.UUID | None
    requisite_type: PaymentRequisiteType | None
    requisite_bank_name: str | None
    requisite_holder_name: str | None
    requisite_masked_card_number: str | None
    status: DealStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None

    merchant_marked_paid_at: datetime | None
    user_confirmed_received_at: datetime | None
    user_rejected_payment_at: datetime | None
    payment_reference: str | None
    payment_note: str | None


class DealListResponse(BaseModel):
    items: list[DealRead]
    total: int
    limit: int
    offset: int
