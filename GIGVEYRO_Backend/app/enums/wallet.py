from enum import StrEnum


class Currency(StrEnum):
    """Wallet balances are tracked in this currency. Stored uppercase in the
    DB, matching these enum values exactly - no case translation layer.
    """

    USDT = "USDT"
    TJS = "TJS"
    RUB = "RUB"

    @classmethod
    def managed_fiat(cls) -> tuple["Currency", "Currency"]:
        return cls.TJS, cls.RUB


class BalanceBucket(StrEnum):
    """Which wallet balance a LedgerEntry's amount was applied to."""

    AVAILABLE = "available"
    INSURANCE = "insurance"
    FROZEN = "frozen"
    HELD = "held"


class LedgerEntryType(StrEnum):
    OWNER_ALLOCATION = "owner_allocation"
    INSURANCE_ADJUSTMENT = "insurance_adjustment"
    MANUAL_ADJUSTMENT = "manual_adjustment"

    # Used since Stage 7's Deal accept flow.
    DEAL_FREEZE = "deal_freeze"
    # Stage 9 Deal settlement & release workflow.
    DEAL_RELEASE = "deal_release"
    DEAL_SETTLEMENT = "deal_settlement"
    DEAL_SETTLEMENT_CREDIT = "deal_settlement_credit"
    # Deal profit split: the accepting USER's own 10% cut, credited back to
    # their available balance alongside DEAL_SETTLEMENT debiting the full
    # deal amount from frozen - see DealService.complete_deal.
    DEAL_USER_PROFIT = "deal_user_profit"

    # Used since Stage 8's confirmed TRC20 deposit credit.
    DEPOSIT_CREDIT = "deposit_credit"

    # Stage 10 Merchant Withdrawal workflow.
    WITHDRAWAL_HOLD = "withdrawal_hold"
    WITHDRAWAL_RELEASE = "withdrawal_release"
    WITHDRAWAL_PAID = "withdrawal_paid"


class FiatLedgerEntryType(StrEnum):
    OWNER_ALLOCATION = "owner_allocation"
    CONVERSION_DEBIT = "conversion_debit"
    CONVERSION_CREDIT = "conversion_credit"
