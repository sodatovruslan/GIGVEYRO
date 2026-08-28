from enum import StrEnum


class FeePolicyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class FeeType(StrEnum):
    DEAL = "deal_fee"
    FIAT_CONVERSION = "fiat_conversion_spread"
    WITHDRAWAL = "withdrawal_fee"
    MERCHANT = "merchant_fee"


class FeePayer(StrEnum):
    USER = "USER"
    MERCHANT = "MERCHANT"
