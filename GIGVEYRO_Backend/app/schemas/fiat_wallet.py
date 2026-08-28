import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.wallet import Currency, FiatLedgerEntryType
from app.schemas.common import Money


class FiatBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: Currency
    available: Money
    updated_at: datetime


class FiatBalanceListOut(BaseModel):
    items: list[FiatBalanceOut]


class OwnerFiatAllocationRequest(BaseModel):
    currency: Currency
    amount: Money = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)


class OwnerFiatAllocationOut(BaseModel):
    operation_id: uuid.UUID
    account_id: uuid.UUID
    currency: Currency
    amount: Money
    balance_before: Money
    balance_after: Money
    created_at: datetime


class FiatConversionPreviewRequest(BaseModel):
    from_currency: Currency
    to_currency: Currency
    source_amount: Money = Field(gt=0)


class FiatConversionPreviewOut(BaseModel):
    from_currency: Currency
    to_currency: Currency
    source_amount: Money
    destination_amount: Money
    gross_destination_amount: Money
    fee_amount: Money
    exchange_rate: Money
    reference_rate: Money
    effective_rate: Money
    fee_policy_version: int
    provider: str
    published_at: datetime
    received_at: datetime
    provider_nominal: Money
    provider_rate: Money
    policy_version: str
    mode: str
    is_stale: bool


class OwnerFiatConversionRequest(FiatConversionPreviewRequest):
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)


class FiatConversionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    initiated_by_account_id: uuid.UUID
    from_currency: Currency
    to_currency: Currency
    source_amount: Money
    destination_amount: Money
    gross_destination_amount: Money
    fee_amount: Money
    exchange_rate: Money
    reference_rate: Money
    effective_rate: Money
    fee_policy_version: int
    source_balance_before: Money
    source_balance_after: Money
    destination_balance_before: Money
    destination_balance_after: Money
    rate_provider: str
    rate_published_at: datetime
    rate_policy_version: str
    rate_mode: str
    comment: str | None
    created_at: datetime


class FiatConversionHistoryOut(BaseModel):
    items: list[FiatConversionOut]
    total: int
    limit: int
    offset: int


class FiatLedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    currency: Currency
    type: FiatLedgerEntryType
    amount: Money
    balance_before: Money
    balance_after: Money
    reference_type: str
    reference_id: uuid.UUID
    description: str | None
    created_by_account_id: uuid.UUID
    created_at: datetime


class FiatLedgerListOut(BaseModel):
    items: list[FiatLedgerEntryOut]
    total: int
    limit: int
    offset: int
