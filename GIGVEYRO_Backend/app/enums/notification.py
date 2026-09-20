from enum import StrEnum


class NotificationChannel(StrEnum):
    TELEGRAM = "TELEGRAM"
    IN_APP = "IN_APP"


class NotificationType(StrEnum):
    DEAL_CREATED = "DEAL_CREATED"
    DEAL_ACCEPTED = "DEAL_ACCEPTED"
    DEAL_PAID = "DEAL_PAID"
    DEAL_COMPLETED = "DEAL_COMPLETED"
    DEAL_CANCELLED = "DEAL_CANCELLED"
    APPEAL_OPENED = "APPEAL_OPENED"
    APPEAL_RESOLVED = "APPEAL_RESOLVED"
    DEPOSIT_CONFIRMED = "DEPOSIT_CONFIRMED"
    WITHDRAWAL_STATUS_CHANGED = "WITHDRAWAL_STATUS_CHANGED"
    PAYOUT_ACTION_REQUIRED = "PAYOUT_ACTION_REQUIRED"
    SECURITY_EVENT = "SECURITY_EVENT"
    FIAT_BALANCE_UPDATED = "FIAT_BALANCE_UPDATED"
    TREASURY_RISK_CHANGED = "TREASURY_RISK_CHANGED"
    ACCESS_REQUEST_SUBMITTED = "ACCESS_REQUEST_SUBMITTED"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationMessageKey(StrEnum):
    APPEAL_OPENED = "appeal.opened"
    APPEAL_RESOLVED = "appeal.resolved"
    DEPOSIT_CREDITED = "deposit.credited"
    WITHDRAWAL_CANCELLED = "withdrawal.cancelled"
    WITHDRAWAL_APPROVED = "withdrawal.approved"
    WITHDRAWAL_REJECTED = "withdrawal.rejected"
    WITHDRAWAL_COMPLETED = "withdrawal.completed"
    FIAT_BALANCE_UPDATED = "fiat.balance_updated"
    SECURITY_RECOVERY_USED = "security.recovery_used"
    SECURITY_TWO_FACTOR_ENABLED = "security.2fa_enabled"
    SECURITY_TWO_FACTOR_DISABLED = "security.2fa_disabled"
    SECURITY_RECOVERY_REGENERATED = "security.recovery_regenerated"
    SECURITY_PASSWORD_CHANGED = "security.password_changed"
    SECURITY_LOGOUT_ALL = "security.logout_all"
    SECURITY_SESSION_REVOKED = "security.session_revoked"
    PAYOUT_APPROVAL_REQUIRED = "payout.approval_required"
    PAYOUT_EXECUTION_FAILED = "payout.execution_failed"
    PAYOUT_RECONCILIATION_REQUIRED = "payout.reconciliation_required"
    TREASURY_WARNING = "treasury.warning"
    TREASURY_CRITICAL = "treasury.critical"
    TREASURY_STALE = "treasury.stale"
    ACCESS_REQUEST_SUBMITTED = "access_request.submitted"
