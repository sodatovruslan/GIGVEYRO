from enum import StrEnum


class DepositStatus(StrEnum):
    WAITING = "waiting"
    DETECTED = "detected"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    CREDITED = "credited"
    EXPIRED = "expired"
    FAILED = "failed"
    AMOUNT_MISMATCH = "amount_mismatch"


class DepositNetwork(StrEnum):
    TRC20 = "TRC20"


class DepositAsset(StrEnum):
    USDT = "USDT"


class CorrelationStatus(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


class ReconciliationStatus(StrEnum):
    PENDING = "PENDING"
    LINKED = "LINKED"
    REPROCESSED = "REPROCESSED"
    IGNORED = "IGNORED"
    CREDITED = "CREDITED"
    FAILED = "FAILED"


class ReconciliationActionType(StrEnum):
    LINK = "LINK"
    REPROCESS = "REPROCESS"
    IGNORE = "IGNORE"
