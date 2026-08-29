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


def get_deposit_provider() -> CryptoDepositProvider:
    if settings.DEPOSIT_PROVIDER_TYPE == "trongrid":
        return TronGridTRC20DepositProvider()
    return MockTRC20DepositProvider()


def get_exchange_rate_provider() -> ExchangeRateProvider:
    if settings.EXCHANGE_RATE_PROVIDER_TYPE == "business":
        from app.services.fiat_rate.runtime import get_business_exchange_rate_service

        return get_business_exchange_rate_service()
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


def get_provider_diagnostics() -> dict:
    """Return current provider configuration for diagnostics endpoint.

    Safe to expose — no credentials included.
    """
    return {
        "deposit_provider": settings.DEPOSIT_PROVIDER_TYPE,
        "exchange_rate_provider": settings.EXCHANGE_RATE_PROVIDER_TYPE,
        "payout_provider": settings.PAYOUT_PROVIDER_MODE,
        "payout_simulation_enabled": settings.PAYOUT_SIMULATION_ENABLED,
        "payout_live_provider_available": False,
        "payout_enabled": settings.PAYOUT_ENABLED,
        "allow_mock_in_production": settings.ALLOW_MOCK_PROVIDERS_IN_PRODUCTION,
        "trongrid_configured": bool(settings.TRONGRID_API_KEY),
        "payout_api_configured": bool(settings.PAYOUT_API_KEY),
        "market_data_primary": settings.MARKET_DATA_PRIMARY,
        "market_data_secondary": settings.MARKET_DATA_SECONDARY,
        "market_data_symbols": settings.MARKET_DATA_SYMBOLS,
        "market_data_public_only": True,
        "fiat_rate_primary": settings.FIAT_RATE_PRIMARY,
        "fiat_rate_secondary": settings.FIAT_RATE_SECONDARY,
        "fiat_rate_public_only": True,
        "fiat_indicative_fallback_allowed": settings.FIAT_ALLOW_INDICATIVE_FALLBACK,
        "usdt_peg_mode": settings.USDT_PEG_MODE,
    }
