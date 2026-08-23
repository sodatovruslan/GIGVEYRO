"""Safe public/read-only USD/TJS provider and business-rate smoke."""

import asyncio
from decimal import Decimal

from app.core.config import settings
from app.services.fiat_rate.aggregator import FiatRateAggregator
from app.services.fiat_rate.business import BusinessExchangeRateService
from app.services.fiat_rate.providers import ExchangeRateApiProvider, NbtFiatRateProvider
from app.services.market_data.http import MarketHttpClient


class UnusedMarket:
    async def get_quote(self, symbol: str):
        raise RuntimeError(f"market provider unexpectedly called in fixed mode: {symbol}")


async def main() -> None:
    client = MarketHttpClient(
        timeout_seconds=settings.FIAT_RATE_TIMEOUT_SECONDS,
        max_retries=settings.FIAT_RATE_MAX_RETRIES,
        max_concurrency=settings.FIAT_RATE_MAX_CONCURRENCY,
    )
    bounds = {
        "minimum_rate": settings.FIAT_RATE_MIN_TJS_PER_USD,
        "maximum_rate": settings.FIAT_RATE_MAX_TJS_PER_USD,
    }
    primary = NbtFiatRateProvider(client, settings.NBT_FIAT_BASE_URL, **bounds)
    secondary = ExchangeRateApiProvider(
        client, settings.EXCHANGE_RATE_API_BASE_URL, **bounds
    )
    aggregator = FiatRateAggregator(
        primary=primary,
        secondary=secondary,
        redis=None,
        redis_prefix=settings.REDIS_KEY_PREFIX,
        cache_ttl_seconds=settings.FIAT_RATE_CACHE_TTL_SECONDS,
        max_age_seconds=settings.FIAT_RATE_MAX_AGE_SECONDS,
        max_deviation_bps=settings.FIAT_RATE_MAX_DEVIATION_BPS,
        allow_indicative_fallback=False,
    )
    business = BusinessExchangeRateService(
        fiat=aggregator,
        market=UnusedMarket(),
        peg_mode="fixed",
        fixed_usdt_usd_rate=Decimal("1"),
        markup_bps=0,
        spread_bps=0,
        minimum_rate=settings.BUSINESS_RATE_MIN_TJS_PER_USDT,
        maximum_rate=settings.BUSINESS_RATE_MAX_TJS_PER_USDT,
        policy_version=settings.BUSINESS_RATE_POLICY_VERSION,
    )
    try:
        official = await primary.get_rate()
        indicative = await secondary.get_rate()
        composed = await business.calculate()
        print(
            f"nbt: pair=USD/TJS decimal={type(official.rate).__name__} "
            f"rate={official.rate} published_at={official.published_at.isoformat()}"
        )
        print(
            f"exchange_rate_api: pair=USD/TJS rate={indicative.rate} "
            f"published_at={indicative.published_at.isoformat()}"
        )
        print(
            f"business: pair=TJS/USDT rate={composed.rate_tjs_per_usdt} "
            f"peg_mode={composed.peg_mode} source={composed.fiat_provider}"
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
