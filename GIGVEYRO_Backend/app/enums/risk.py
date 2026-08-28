from enum import StrEnum


class RiskPolicyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class RiskStatus(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    STALE = "stale"
    UNKNOWN = "unknown"


class RiskDecision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class RiskReason(StrEnum):
    RESERVE_DATA_STALE = "reserve_data_stale"
    INSUFFICIENT_RESERVE = "insufficient_reserve"
    SINGLE_DEAL_LIMIT = "single_deal_limit"
    USER_EXPOSURE_LIMIT = "user_exposure_limit"
    PENDING_WITHDRAWAL_LIMIT = "pending_withdrawal_limit"
    TOTAL_OPEN_EXPOSURE_LIMIT = "total_open_exposure_limit"
    MINIMUM_EXTERNAL_RESERVE = "minimum_external_reserve"
