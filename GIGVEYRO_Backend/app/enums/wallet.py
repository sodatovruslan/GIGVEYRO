from enum import StrEnum


class Currency(StrEnum):
    """Wallet balances are tracked in this currency. Stored uppercase in the
    DB, matching these enum values exactly - no case translation layer.
    """

    USDT = "USDT"


class BalanceBucket(StrEnum):
    """Which wallet balance a LedgerEntry's amount was applied to."""

    AVAILABLE = "available"
    INSURANCE = "insurance"
    FROZEN = "frozen"


class LedgerEntryType(StrEnum):
    OWNER_ALLOCATION = "owner_allocation"
    INSURANCE_ADJUSTMENT = "insurance_adjustment"
    MANUAL_ADJUSTMENT = "manual_adjustment"

    # Used since Stage 7's Deal accept flow.
    DEAL_FREEZE = "deal_freeze"
    # Reserved for the future Deal settlement workflow.
    DEAL_RELEASE = "deal_release"
    DEAL_SETTLEMENT = "deal_settlement"

    # Used since Stage 8's confirmed TRC20 deposit credit.
    DEPOSIT_CREDIT = "deposit_credit"
