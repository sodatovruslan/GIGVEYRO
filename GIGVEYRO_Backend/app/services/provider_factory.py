from app.core.config import settings
from app.services.deposit_provider import (
    CryptoDepositProvider,
    MockTRC20DepositProvider,
    TronGridTRC20DepositProvider,
)
from app.services.exchange_rate import (
    ConfiguredExchangeRateProvider,
    ExchangeRateProvider,
    ExternalExchangeRateProvider,
    FallbackExchangeRateProvider,
)
from app.services.withdrawal import ExternalPayoutAdapter, MockPayoutProvider, PayoutProvider


def get_deposit_provider() -> CryptoDepositProvider:
    if settings.DEPOSIT_PROVIDER_TYPE == "trongrid":
        return TronGridTRC20DepositProvider()
    return MockTRC20DepositProvider()


def get_exchange_rate_provider() -> ExchangeRateProvider:
    if settings.EXCHANGE_RATE_PROVIDER_TYPE == "external":
        return ExternalExchangeRateProvider()
    if settings.EXCHANGE_RATE_PROVIDER_TYPE == "fallback":
        return FallbackExchangeRateProvider(
            primary=ExternalExchangeRateProvider(),
            fallback=ConfiguredExchangeRateProvider(),
            max_retries=settings.EXCHANGE_RATE_MAX_RETRIES,
            cache_ttl_seconds=settings.EXCHANGE_RATE_CACHE_TTL_SECONDS,
        )
    return ConfiguredExchangeRateProvider()


def get_payout_provider() -> PayoutProvider:
    if settings.PAYOUT_PROVIDER_TYPE == "external_adapter":
        return ExternalPayoutAdapter(
            api_url=settings.PAYOUT_API_URL,
            api_key=settings.PAYOUT_API_KEY,
        )
    return MockPayoutProvider()
