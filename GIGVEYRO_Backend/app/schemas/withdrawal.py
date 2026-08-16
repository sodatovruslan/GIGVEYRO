import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.wallet import Currency
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.schemas.common import Money


class MerchantWithdrawalCreate(BaseModel):
    amount: Money = Field(gt=0)
    destination_type: WithdrawalDestinationType
    destination: str = Field(min_length=3, max_length=255)
    comment: str | None = Field(default=None, max_length=500)


class OwnerWithdrawalAction(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class MerchantWithdrawalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    merchant_id: uuid.UUID
    merchant_wallet_id: uuid.UUID
    amount: Money
    currency: Currency
    destination_type: WithdrawalDestinationType
    destination: str
    status: WithdrawalStatus
    comment: str | None
    owner_comment: str | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    created_by_account_id: uuid.UUID
    actioned_by_account_id: uuid.UUID | None


class MerchantWithdrawalListResponse(BaseModel):
    items: list[MerchantWithdrawalRead]
    total: int
    limit: int
    offset: int
