import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field

from app.schemas.common import Money


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is not accepted for financial configuration")
    return value


def _normalize_percentage(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be a finite number (no NaN/Infinity)")
    try:
        return value.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("value has too many significant digits") from exc


# Same float-rejection convention as app.schemas.risk.RiskMoney - reused, not
# reinvented - plus an explicit finite-value guard and 2-decimal-place
# normalization ("10.00%") on top, since this type is a percentage, not money.
ReservePercentage = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_normalize_percentage),
    Field(ge=0, le=100),
]


class InsuranceReservePolicyInput(BaseModel):
    enabled: bool = False
    minimum_reserve_percentage: ReservePercentage = Decimal("0")


class InsuranceReservePolicyOut(InsuranceReservePolicyInput):
    id: uuid.UUID
    version: int
    status: str
    created_by_account_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None


class InsuranceReserveWalletView(BaseModel):
    """Per-wallet reserve figures for the Owner UI - every value read
    straight from the wallet row and the active policy, nothing invented."""

    account_id: uuid.UUID
    insurance_balance: Money
    insurance_reserve_basis: Money
    minimum_reserve_percentage: Decimal
    required_minimum_reserve: Money
    available_above_reserve: Money
    policy_version: int
    policy_enabled: bool
    policy_updated_at: datetime
