import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.schemas.common import Money


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: LedgerEntryType
    balance_bucket: BalanceBucket
    currency: Currency
    amount: Money
    available_before: Money
    available_after: Money
    insurance_before: Money
    insurance_after: Money
    frozen_before: Money
    frozen_after: Money
    reference_type: str | None
    reference_id: uuid.UUID | None
    description: str | None
    created_by_account_id: uuid.UUID | None
    created_at: datetime


class LedgerListResponse(BaseModel):
    items: list[LedgerEntryRead]
    total: int
    limit: int
    offset: int
