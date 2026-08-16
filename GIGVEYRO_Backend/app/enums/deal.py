from enum import StrEnum


class DealStatus(StrEnum):
    CREATED = "created"
    AVAILABLE = "available"
    ACCEPTED = "accepted"
    PAYMENT_PENDING = "payment_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DISPUTED = "disputed"
