from __future__ import annotations

from app.core.config import settings
from app.infra.redis_client import get_redis
from app.services.market_data.aggregator import MarketDataAggregator
from app.services.market_data.http import MarketHttpClient
from app.services.market_data.providers import BinanceMarketProvider, BybitMarketProvider

_client: MarketHttpClient | None = None
_aggregator: MarketDataAggregator | None = None


async def init_market_data() -> None:
    global _aggregator, _client  # noqa: PLW0603
    if _aggregator is not None:
        return
    _client = MarketHttpClient(
        timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
        max_retries=settings.MARKET_DATA_MAX_RETRIES,
        max_concurrency=settings.MARKET_DATA_MAX_CONCURRENCY,
    )
    symbols = set(settings.MARKET_DATA_SYMBOLS)
    providers = {
        "binance": BinanceMarketProvider(_client, settings.BINANCE_PUBLIC_BASE_URL, symbols),
        "bybit": BybitMarketProvider(_client, settings.BYBIT_PUBLIC_BASE_URL, symbols),
    }
    try:
        redis = get_redis()
    except RuntimeError:
        redis = None
    _aggregator = MarketDataAggregator(
        primary=providers[settings.MARKET_DATA_PRIMARY],
        secondary=providers[settings.MARKET_DATA_SECONDARY],
        redis=redis,
        redis_prefix=settings.REDIS_KEY_PREFIX,
        cache_ttl_seconds=settings.MARKET_DATA_CACHE_TTL_SECONDS,
        max_deviation_bps=settings.MARKET_MAX_DEVIATION_BPS,
        failure_threshold=settings.MARKET_CIRCUIT_FAILURE_THRESHOLD,
        cooldown_seconds=settings.MARKET_CIRCUIT_COOLDOWN_SECONDS,
    )


async def close_market_data() -> None:
    global _aggregator, _client  # noqa: PLW0603
    if _client is not None:
        await _client.close()
    _client = None
    _aggregator = None


def get_market_data_aggregator() -> MarketDataAggregator:
    if _aggregator is None:
        raise RuntimeError("Market data runtime is not initialised")
    return _aggregator


async def get_market_diagnostics() -> dict:
    try:
        aggregator = get_market_data_aggregator()
    except RuntimeError:
        return _unavailable_diagnostics()
    return await aggregator.diagnostics(settings.MARKET_DATA_SYMBOLS[0])


def _unavailable_diagnostics() -> dict:
    providers = {
        "binance": settings.BINANCE_PUBLIC_BASE_URL,
        "bybit": settings.BYBIT_PUBLIC_BASE_URL,
    }
    return {
        "primary": settings.MARKET_DATA_PRIMARY,
        "secondary": settings.MARKET_DATA_SECONDARY,
        "active_provider": None,
        "status": "unavailable",
        "cache": "unavailable",
        "symbol": settings.MARKET_DATA_SYMBOLS[0],
        "deviation_bps": None,
        "providers": {
            name: {
                "status": "unavailable",
                "public_api": True,
                "read_only": True,
                "base_url": base_url,
                "latency_ms": None,
                "last_success_at": None,
                "role": "primary" if settings.MARKET_DATA_PRIMARY == name else "fallback",
                "circuit": "closed",
            }
            for name, base_url in providers.items()
        },
    }
