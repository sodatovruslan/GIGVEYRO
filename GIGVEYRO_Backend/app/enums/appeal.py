from enum import StrEnum


class AppealStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class AppealReason(StrEnum):
    PAYMENT_NOT_RECEIVED = "payment_not_received"
    WRONG_AMOUNT = "wrong_amount"
    PAYMENT_PROOF_ISSUE = "payment_proof_issue"
    TIMEOUT_DISPUTE = "timeout_dispute"
    OTHER = "other"


class AppealResolution(StrEnum):
    SETTLE_TO_MERCHANT = "settle_to_merchant"
    RELEASE_TO_USER = "release_to_user"
