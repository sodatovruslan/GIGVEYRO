from pydantic import BaseModel

from app.schemas.common import Money


class MerchantInvoiceStatsRead(BaseModel):
    total: int
    pending_payment: int
    paid: int
    expired: int
    cancelled: int
    paid_volume: Money


class MerchantWithdrawalStatsRead(BaseModel):
    total: int
    pending: int
    approved: int
    paid: int
    rejected: int
    cancelled: int
    paid_volume: Money


class MerchantStatisticsRead(BaseModel):
    invoices: MerchantInvoiceStatsRead
    withdrawals: MerchantWithdrawalStatsRead
