import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from app.schemas.common import Money


def _decimal_only(value):
    if isinstance(value, float):
        raise ValueError("binary float is not accepted for financial configuration")
    return value


RiskMoney = Annotated[Decimal, BeforeValidator(_decimal_only)]


class RiskPolicyInput(BaseModel):
    reserve_coverage_enabled: bool = False
    minimum_reserve_ratio_bps: int = Field(default=10000, ge=0, le=50000)
    warning_reserve_ratio_bps: int = Field(default=11000, ge=0, le=50000)
    max_treasury_data_age_seconds: int = Field(default=300, ge=30, le=86400)
    single_deal_enabled: bool = False
    max_single_deal_usdt: RiskMoney | None = Field(default=None, ge=0)
    user_exposure_enabled: bool = False
    max_user_exposure_usdt: RiskMoney | None = Field(default=None, ge=0)
    pending_withdrawals_enabled: bool = False
    max_pending_withdrawals_usdt: RiskMoney | None = Field(default=None, ge=0)
    total_open_deals_enabled: bool = False
    max_total_open_deals_usdt: RiskMoney | None = Field(default=None, ge=0)
    minimum_external_reserve_enabled: bool = False
    minimum_external_usdt_reserve: RiskMoney | None = Field(default=None, ge=0)


class RiskPolicyOut(RiskPolicyInput):
    id: uuid.UUID
    version: int
    status: str
    effective_from: datetime | None
    created_at: datetime
    activated_at: datetime | None


class TreasurySummaryOut(BaseModel):
    generated_at: datetime
    external_observed_at: datetime | None
    data_age_seconds: int | None
    provider_status: str
    external_bybit_usdt: Money
    external_bybit_usdc: Money
    total_external_stable_reserve: Money | None = None
    internal_user_liability_usdt: Money
    merchant_liability_usdt: Money
    total_internal_liability_usdt: Money
    frozen_usdt: Money
    pending_withdrawal_usdt: Money
    open_deal_exposure_usdt: Money
    owner_profit_usdt: Money
    required_reserve_usdt: Money
    available_reserve_usdt: Money
    reserve_surplus_usdt: Money
    reserve_deficit_usdt: Money
    coverage_ratio_bps: int | None
    risk_status: str
    policy_version: int


class TreasuryHistoryOut(BaseModel):
    items: list[TreasurySummaryOut]
    total: int
    limit: int
    offset: int


class RiskPreviewOut(BaseModel):
    snapshot: TreasurySummaryOut
    reserve_decision: str
    reason_code: str | None
