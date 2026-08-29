from enum import StrEnum


class PayoutStatus(StrEnum):
    REQUESTED = "requested"
    RISK_REVIEW = "risk_review"
    APPROVED = "approved"
    QUEUED = "queued"
    EXECUTION_PENDING = "execution_pending"
    EXECUTING = "executing"
    AWAITING_MANUAL_SETTLEMENT = "awaiting_manual_settlement"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class PayoutProviderMode(StrEnum):
    DISABLED = "disabled"
    SIMULATED = "simulated"
    LIVE = "live"


class PayoutApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class PayoutFailureKind(StrEnum):
    RETRYABLE = "retryable_failure"
    PERMANENT = "permanent_failure"
    UNKNOWN = "unknown_result"


class PayoutProviderResult(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PayoutSimulationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"
    UNKNOWN = "unknown"
