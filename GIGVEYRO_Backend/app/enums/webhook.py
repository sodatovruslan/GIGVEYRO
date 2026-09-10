from enum import StrEnum


class WebhookStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class WebhookDeliveryStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class WebhookEventType(StrEnum):
    INVOICE_PAID = "invoice.paid"
