from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PeriodQuery(BaseModel):
    period: Literal["today", "7d", "30d", "90d", "custom"] = "30d"
    date_from: datetime | None = None
    date_to: datetime | None = None


class AccountSummaryKPI(BaseModel):
    users_total: int = 0
    users_active: int = 0
    users_blocked: int = 0
    merchants_total: int = 0
    merchants_active: int = 0
    merchants_blocked: int = 0


class TrafficSummaryKPI(BaseModel):
    users_enabled: int = 0


class DealSummaryKPI(BaseModel):
    total: int = 0
    available: int = 0
    accepted: int = 0
    payment_pending: int = 0
    completed: int = 0
    disputed: int = 0
    cancelled: int = 0


class DepositSummaryKPI(BaseModel):
    total: int = 0
    credited: int = 0
    pending: int = 0
    amount_credited_usdt: Decimal = Field(default=Decimal("0.00000000"))


class WithdrawalSummaryKPI(BaseModel):
    total: int = 0
    pending: int = 0
    approved: int = 0
    paid: int = 0
    rejected: int = 0
    amount_paid_usdt: Decimal = Field(default=Decimal("0.00000000"))


class AppealSummaryKPI(BaseModel):
    open: int = 0
    under_review: int = 0
    resolved: int = 0


class FinancialTotalsKPI(BaseModel):
    total_user_available_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_user_insurance_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_user_frozen_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_merchant_available_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_merchant_held_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_credited_deposits_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_paid_withdrawals_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_completed_deal_volume_tjs: Decimal = Field(default=Decimal("0.00000000"))
    total_completed_deal_volume_usdt: Decimal = Field(default=Decimal("0.00000000"))


class DashboardSummaryResponse(BaseModel):
    accounts: AccountSummaryKPI
    traffic: TrafficSummaryKPI
    deals: DealSummaryKPI
    deposits: DepositSummaryKPI
    withdrawals: WithdrawalSummaryKPI
    appeals: AppealSummaryKPI
    financials: FinancialTotalsKPI


class DealAnalyticsResponse(BaseModel):
    total_deals: int = 0
    completed_deals: int = 0
    cancelled_deals: int = 0
    disputed_deals: int = 0
    total_volume_tjs: Decimal = Field(default=Decimal("0.00000000"))
    total_volume_usdt: Decimal = Field(default=Decimal("0.00000000"))
    average_deal_tjs: Decimal = Field(default=Decimal("0.00000000"))
    average_deal_usdt: Decimal = Field(default=Decimal("0.00000000"))
    completion_rate: Decimal = Field(default=Decimal("0.00"))
    dispute_rate: Decimal = Field(default=Decimal("0.00"))
    average_completion_time_seconds: float | None = None


class DealTimeSeriesPoint(BaseModel):
    period: str
    deals: int = 0
    completed: int = 0
    volume_tjs: Decimal = Field(default=Decimal("0.00000000"))
    volume_usdt: Decimal = Field(default=Decimal("0.00000000"))


class DepositAnalyticsResponse(BaseModel):
    total: int = 0
    waiting: int = 0
    detected: int = 0
    confirming: int = 0
    confirmed: int = 0
    credited: int = 0
    expired: int = 0
    failed: int = 0
    amount_credited_usdt: Decimal = Field(default=Decimal("0.00000000"))
    average_confirmation_time_seconds: float | None = None


class DepositTimeSeriesPoint(BaseModel):
    period: str
    credited_count: int = 0
    credited_amount_usdt: Decimal = Field(default=Decimal("0.00000000"))


class WithdrawalAnalyticsResponse(BaseModel):
    total: int = 0
    pending: int = 0
    approved: int = 0
    paid: int = 0
    rejected: int = 0
    cancelled: int = 0
    total_requested_usdt: Decimal = Field(default=Decimal("0.00000000"))
    total_paid_usdt: Decimal = Field(default=Decimal("0.00000000"))
    average_withdrawal_usdt: Decimal = Field(default=Decimal("0.00000000"))
    average_processing_time_seconds: float | None = None


class WithdrawalTimeSeriesPoint(BaseModel):
    period: str
    created_count: int = 0
    paid_count: int = 0
    paid_amount_usdt: Decimal = Field(default=Decimal("0.00000000"))


class AppealAnalyticsResponse(BaseModel):
    total: int = 0
    open: int = 0
    under_review: int = 0
    resolved: int = 0
    cancelled: int = 0
    merchant_wins: int = 0
    user_wins: int = 0
    average_resolution_time_seconds: float | None = None


class AccountAnalyticsResponse(BaseModel):
    users_total: int = 0
    users_active: int = 0
    users_blocked: int = 0
    merchants_total: int = 0
    merchants_active: int = 0
    merchants_blocked: int = 0
    traffic_enabled_users: int = 0
    users_with_requisites: int = 0
    users_without_requisites: int = 0


class TopMerchantRead(BaseModel):
    merchant_id: str
    username: str
    full_name: str
    completed_deals: int = 0
    volume_tjs: Decimal = Field(default=Decimal("0.00000000"))
    volume_usdt: Decimal = Field(default=Decimal("0.00000000"))
    merchant_available_balance: Decimal = Field(default=Decimal("0.00000000"))


class TopUserRead(BaseModel):
    account_id: str
    username: str
    full_name: str
    completed_deals: int = 0
    volume_tjs: Decimal = Field(default=Decimal("0.00000000"))
    volume_usdt: Decimal = Field(default=Decimal("0.00000000"))
    traffic_enabled: bool = False
    available_balance: Decimal = Field(default=Decimal("0.00000000"))
    frozen_balance: Decimal = Field(default=Decimal("0.00000000"))


class RecentActivityItem(BaseModel):
    type: str
    entity_id: str
    public_id: str | None = None
    description: str
    created_at: datetime


class FinancialFlowResponse(BaseModel):
    deposits_credited_usdt: Decimal = Field(default=Decimal("0.00000000"))
    deal_settlements_usdt: Decimal = Field(default=Decimal("0.00000000"))
    withdrawals_paid_usdt: Decimal = Field(default=Decimal("0.00000000"))
    merchant_balances_usdt: Decimal = Field(default=Decimal("0.00000000"))


class BalanceIntegrityResponse(BaseModel):
    user_wallet_total_usdt: Decimal = Field(default=Decimal("0.00000000"))
    merchant_wallet_total_usdt: Decimal = Field(default=Decimal("0.00000000"))
    credited_deposits_usdt: Decimal = Field(default=Decimal("0.00000000"))
    paid_withdrawals_usdt: Decimal = Field(default=Decimal("0.00000000"))
    status: Literal["ok"] = "ok"
