"""Safe public/read-only Binance + Bybit connectivity smoke.

No API keys, signing, account calls, trading, or money movement.
"""

import asyncio

from app.core.config import settings
from app.services.market_data.http import MarketHttpClient
from app.services.market_data.providers import BinanceMarketProvider, BybitMarketProvider


async def main() -> None:
    client = MarketHttpClient(
        timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
        max_retries=settings.MARKET_DATA_MAX_RETRIES,
        max_concurrency=2,
    )
    symbols = set(settings.MARKET_DATA_SYMBOLS)
    providers = (
        BinanceMarketProvider(client, settings.BINANCE_PUBLIC_BASE_URL, symbols),
        BybitMarketProvider(client, settings.BYBIT_PUBLIC_BASE_URL, symbols),
    )
    try:
        for provider in providers:
            quote = await provider.get_quote(settings.MARKET_DATA_SYMBOLS[0])
            print(
                f"{quote.provider}: status=200 symbol={quote.symbol} "
                f"decimal={type(quote.last).__name__} price={quote.last} "
                f"latency_ms={quote.latency_ms:.1f}"
            )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
