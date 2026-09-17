import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from app.enums.wallet import Currency
from app.schemas.common import Money


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is not accepted for financial configuration")
    return value


def _require_finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be a finite number (no NaN/Infinity)")
    try:
        return value.quantize(Decimal("0.00000001"))
    except InvalidOperation as exc:
        raise ValueError("value has too many significant digits") from exc


# Same float-rejection + finite-value convention as app.schemas.risk.RiskMoney
# / the retired app.schemas.insurance_reserve.ReservePercentage - an absolute
# money value (not a percentage), bounded to a sane business ceiling.
InsuranceTargetMoney = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_require_finite),
    Field(ge=0, le=Decimal("100000000")),
]


class WalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: Currency
    available_balance: Money
    insurance_balance: Money
    frozen_balance: Money


class AllocateRequest(BaseModel):
    amount: Money = Field(gt=0)
    description: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


class InsuranceAdjustRequest(BaseModel):
    amount: Money = Field(description="Positive to increase, negative to decrease")
    description: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


class ManualAdjustRequest(BaseModel):
    amount: Money = Field(description="Positive to credit, negative to debit")
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


class InsuranceTargetView(BaseModel):
    """Per-user insurance target figures for the Owner UI - every value read
    straight from the wallet row, nothing derived from a percentage."""

    account_id: uuid.UUID
    insurance_balance: Money
    insurance_target: Money
    remaining_to_target: Money


class InsuranceTargetUpdateRequest(BaseModel):
    insurance_target: InsuranceTargetMoney
