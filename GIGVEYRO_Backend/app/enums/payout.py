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


class LivePayoutCapability(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READ_ONLY = "READ_ONLY"
    WRITE_CREDENTIALS_MISSING = "WRITE_CREDENTIALS_MISSING"
    WRITE_PERMISSION_MISSING = "WRITE_PERMISSION_MISSING"
    DRY_RUN_READY = "DRY_RUN_READY"
    LIVE_DISABLED = "LIVE_DISABLED"
    LIVE_READY = "LIVE_READY"


class LivePayoutBlocker(StrEnum):
    PAYOUT_GLOBAL_DISABLED = "PAYOUT_GLOBAL_DISABLED"
    PROVIDER_NOT_LIVE = "PROVIDER_NOT_LIVE"
    WRITE_CREDENTIALS_MISSING = "WRITE_CREDENTIALS_MISSING"
    WRITE_PERMISSION_UNVERIFIED = "WRITE_PERMISSION_UNVERIFIED"
    IP_WHITELIST_REQUIRED = "IP_WHITELIST_REQUIRED"
    NO_APPROVED_DESTINATION = "NO_APPROVED_DESTINATION"
    NO_ALLOWED_NETWORK = "NO_ALLOWED_NETWORK"
    BUSINESS_PAYOUTS_DISABLED = "BUSINESS_PAYOUTS_DISABLED"
    RISK_POLICY_NOT_READY = "RISK_POLICY_NOT_READY"
    DUAL_APPROVAL_NOT_READY = "DUAL_APPROVAL_NOT_READY"
    RECONCILIATION_NOT_READY = "RECONCILIATION_NOT_READY"
    WRITE_NETWORK_TRANSPORT_DISABLED = "WRITE_NETWORK_TRANSPORT_DISABLED"
