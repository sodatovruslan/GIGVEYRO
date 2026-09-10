from enum import StrEnum


class InvoiceStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
