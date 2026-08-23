from __future__ import annotations

from app.core.config import settings
from app.infra.redis_client import get_redis
from app.services.exchange_rate import ExchangeRateError
from app.services.fiat_rate.aggregator import FiatRateAggregator
from app.services.fiat_rate.business import BusinessExchangeRateService
from app.services.fiat_rate.providers import ExchangeRateApiProvider, NbtFiatRateProvider
from app.services.market_data.http import MarketHttpClient
from app.services.market_data.runtime import get_market_data_aggregator

_client: MarketHttpClient | None = None
_aggregator: FiatRateAggregator | None = None
_business: BusinessExchangeRateService | None = None


async def init_fiat_rate() -> None:
    global _aggregator, _business, _client  # noqa: PLW0603
    if _business is not None:
        return
    _client = MarketHttpClient(
        timeout_seconds=settings.FIAT_RATE_TIMEOUT_SECONDS,
        max_retries=settings.FIAT_RATE_MAX_RETRIES,
        max_concurrency=settings.FIAT_RATE_MAX_CONCURRENCY,
    )
    provider_args = {
        "minimum_rate": settings.FIAT_RATE_MIN_TJS_PER_USD,
        "maximum_rate": settings.FIAT_RATE_MAX_TJS_PER_USD,
    }
    providers = {
        "nbt": NbtFiatRateProvider(
            _client,
            settings.NBT_FIAT_BASE_URL,
            **provider_args,
        ),
        "exchange_rate_api": ExchangeRateApiProvider(
            _client,
            settings.EXCHANGE_RATE_API_BASE_URL,
            **provider_args,
        ),
    }
    try:
        redis = get_redis()
    except RuntimeError:
        redis = None
    _aggregator = FiatRateAggregator(
        primary=providers[settings.FIAT_RATE_PRIMARY],
        secondary=providers[settings.FIAT_RATE_SECONDARY],
        redis=redis,
        redis_prefix=settings.REDIS_KEY_PREFIX,
        cache_ttl_seconds=settings.FIAT_RATE_CACHE_TTL_SECONDS,
        max_age_seconds=settings.FIAT_RATE_MAX_AGE_SECONDS,
        max_deviation_bps=settings.FIAT_RATE_MAX_DEVIATION_BPS,
        allow_indicative_fallback=settings.FIAT_ALLOW_INDICATIVE_FALLBACK,
    )
    _business = BusinessExchangeRateService(
        fiat=_aggregator,
        market=get_market_data_aggregator(),
        peg_mode=settings.USDT_PEG_MODE,
        fixed_usdt_usd_rate=settings.USDT_FIXED_USD_RATE,
        markup_bps=settings.BUSINESS_RATE_MARKUP_BPS,
        spread_bps=settings.BUSINESS_RATE_SPREAD_BPS,
        minimum_rate=settings.BUSINESS_RATE_MIN_TJS_PER_USDT,
        maximum_rate=settings.BUSINESS_RATE_MAX_TJS_PER_USDT,
        policy_version=settings.BUSINESS_RATE_POLICY_VERSION,
    )


async def close_fiat_rate() -> None:
    global _aggregator, _business, _client  # noqa: PLW0603
    if _client is not None:
        await _client.close()
    _client = None
    _aggregator = None
    _business = None


def get_fiat_rate_aggregator() -> FiatRateAggregator:
    if _aggregator is None:
        raise RuntimeError("Fiat-rate runtime is not initialised")
    return _aggregator


def get_business_exchange_rate_service() -> BusinessExchangeRateService:
    if _business is None:
        raise RuntimeError("Business exchange-rate runtime is not initialised")
    return _business


async def get_fiat_diagnostics() -> dict:
    try:
        return await get_fiat_rate_aggregator().diagnostics()
    except RuntimeError:
        return {
            "status": "unavailable",
            "primary": settings.FIAT_RATE_PRIMARY,
            "secondary": settings.FIAT_RATE_SECONDARY,
            "active_provider": None,
            "cache": "unavailable",
            "max_age_seconds": settings.FIAT_RATE_MAX_AGE_SECONDS,
            "deviation_bps": None,
            "providers": {},
        }


async def get_business_rate_diagnostics() -> dict:
    try:
        snapshot = await get_business_exchange_rate_service().calculate()
    except (RuntimeError, ExchangeRateError):
        return {
            "status": "unavailable",
            "rate_tjs_per_usdt": None,
            "peg_mode": settings.USDT_PEG_MODE,
            "policy_version": settings.BUSINESS_RATE_POLICY_VERSION,
            "fiat_provider": None,
            "market_provider": None,
            "calculated_at": None,
            "is_degraded": True,
        }
    payload = snapshot.to_dict()
    return {"status": "degraded" if snapshot.is_degraded else "connected", **payload}
