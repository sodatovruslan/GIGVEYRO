from enum import StrEnum


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class WithdrawalDestinationType(StrEnum):
    USDT_TRC20_ADDRESS = "usdt_trc20_address"
    BYBIT_UID = "bybit_uid"
