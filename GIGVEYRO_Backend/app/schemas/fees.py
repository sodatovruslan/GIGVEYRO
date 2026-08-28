import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.enums.fees import FeePayer, FeePolicyStatus, FeeType
from app.enums.wallet import Currency
from app.schemas.common import Money


def _decimal_string(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("Financial values must be decimal strings, not binary floats")
    return value


FeeInput = Annotated[Decimal, BeforeValidator(_decimal_string)]


class FeeComponentInput(BaseModel):
    enabled: bool = False
    percent_bps: int = Field(default=0, ge=0, le=5000)
    fixed_fee: FeeInput = Field(default=Decimal("0"), ge=0)
    min_fee: FeeInput | None = Field(default=None, ge=0)
    max_fee: FeeInput | None = Field(default=None, ge=0)
    payer: FeePayer | None = None

    @model_validator(mode="after")
    def validate_financial_values(self) -> "FeeComponentInput":
        values = (self.fixed_fee, self.min_fee, self.max_fee)
        if any(value is not None and not value.is_finite() for value in values):
            raise ValueError("Fee values must be finite")
        if self.min_fee is not None and self.max_fee is not None and self.min_fee > self.max_fee:
            raise ValueError("min_fee cannot exceed max_fee")
        return self


class FeePolicyCreate(BaseModel):
    components: dict[FeeType, FeeComponentInput]

    @model_validator(mode="after")
    def require_all_components(self) -> "FeePolicyCreate":
        if set(self.components) != set(FeeType):
            raise ValueError("All four fee components are required")
        return self


class FeeComponentOut(BaseModel):
    fee_type: FeeType
    enabled: bool
    percent_bps: int
    fixed_fee: Money
    min_fee: Money | None
    max_fee: Money | None
    payer: FeePayer | None
    supported_for_charging: bool


class FeePolicyOut(BaseModel):
    id: uuid.UUID
    version: int
    status: FeePolicyStatus
    effective_from: datetime | None
    created_at: datetime
    activated_at: datetime | None
    components: list[FeeComponentOut]


class FeePreviewRequest(BaseModel):
    policy_id: uuid.UUID | None = None
    fee_type: FeeType
    currency: Currency
    amount: FeeInput = Field(gt=0)


class FeePreviewOut(BaseModel):
    policy_version: int
    fee_type: FeeType
    currency: Currency
    gross: Money
    percent_fee: Money
    fixed_fee: Money
    total_fee: Money
    net: Money


class ProfitMetricOut(BaseModel):
    currency: Currency
    fee_type: FeeType
    gross_volume: Money
    total_fees: Money
    transaction_count: int
    average_fee: Money


class ProfitSummaryOut(BaseModel):
    periods: dict[str, list[ProfitMetricOut]]


class ProfitEntryOut(BaseModel):
    id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    fee_type: FeeType
    currency: Currency
    gross_amount: Money
    fee_amount: Money
    policy_version: int
    created_at: datetime


class ProfitEntriesOut(BaseModel):
    items: list[ProfitEntryOut]
    total: int
    limit: int
    offset: int
