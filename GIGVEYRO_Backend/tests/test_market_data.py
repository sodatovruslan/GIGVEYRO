import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from redis.exceptions import RedisError

from app.services.market_data import (
    BinanceMarketProvider,
    BybitMarketProvider,
    MarketDataAggregator,
    MarketQuote,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
)
from app.services.market_data.http import MarketHttpClient

SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def _client(handler, *, retries: int = 0) -> MarketHttpClient:
    transport = httpx.MockTransport(handler)
    raw = httpx.AsyncClient(transport=transport)
    return MarketHttpClient(
        timeout_seconds=0.05,
        max_retries=retries,
        max_concurrency=2,
        client=raw,
    )


@pytest.mark.asyncio
async def test_binance_success_decimal_and_public_request():
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json={"symbol": "BTCUSDT", "price": "64231.12000000"})

    provider = BinanceMarketProvider(
        _client(handler), "https://data-api.binance.vision", SYMBOLS
    )
    quote = await provider.get_quote("btcusdt")
    assert quote.last == Decimal("64231.12000000")
    assert quote.provider == "binance"
    assert seen_request is not None
    assert seen_request.url.path == "/api/v3/ticker/price"
    assert seen_request.url.params["symbol"] == "BTCUSDT"
    assert "X-MBX-APIKEY" not in seen_request.headers
    assert "signature" not in seen_request.url.params


@pytest.mark.asyncio
async def test_binance_rejects_unsupported_symbol_before_network():
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    provider = BinanceMarketProvider(_client(handler), "https://example.test", SYMBOLS)
    with pytest.raises(ProviderUnsupportedSymbol):
        await provider.get_quote("USDTTJS")
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, headers={"Retry-After": "0"}), ProviderRateLimited),
        (httpx.Response(500), ProviderUnavailable),
        (httpx.Response(200, content=b"not-json"), ProviderBadResponse),
        (httpx.Response(200, json={"symbol": "BTCUSDT", "price": "NaN"}), ProviderBadResponse),
    ],
)
async def test_binance_normalizes_provider_errors(response, error):
    provider = BinanceMarketProvider(
        _client(lambda _: response), "https://example.test", SYMBOLS
    )
    with pytest.raises(error):
        await provider.get_quote("BTCUSDT")


@pytest.mark.asyncio
async def test_timeout_is_normalized():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = BinanceMarketProvider(_client(handler), "https://example.test", SYMBOLS)
    with pytest.raises(ProviderTimeout):
        await provider.get_quote("BTCUSDT")


@pytest.mark.asyncio
async def test_bybit_v5_success_parses_nested_quote_without_auth():
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "category": "spot",
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "lastPrice": "64230.1",
                            "bid1Price": "64230.0",
                            "ask1Price": "64230.2",
                        }
                    ],
                },
                "time": 1700000000000,
            },
        )

    provider = BybitMarketProvider(_client(handler), "https://api.bybit.com", SYMBOLS)
    quote = await provider.get_quote("BTCUSDT")
    assert quote.last == Decimal("64230.1")
    assert quote.bid == Decimal("64230.0")
    assert quote.ask == Decimal("64230.2")
    assert quote.timestamp is not None
    assert seen_request is not None
    assert seen_request.url.params["category"] == "spot"
    assert not any(name.lower().startswith("x-bapi") for name in seen_request.headers)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"retCode": 10001, "retMsg": "bad", "result": {}},
        {"retCode": 0, "result": {"list": []}},
        {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT"}]}},
        {"retCode": 0, "result": {"list": [{"symbol": "ETHUSDT", "lastPrice": "1"}]}},
    ],
)
async def test_bybit_rejects_api_errors_empty_or_malformed_results(payload):
    provider = BybitMarketProvider(
        _client(lambda _: httpx.Response(200, json=payload)),
        "https://example.test",
        SYMBOLS,
    )
    with pytest.raises(ProviderBadResponse):
        await provider.get_quote("BTCUSDT")


class StubProvider:
    def __init__(self, name: str, result: MarketQuote | Exception, *, delay: float = 0) -> None:
        self.name = name
        self.base_url = f"https://{name}.test"
        self.result = result
        self.delay = delay
        self.calls = 0

    def validate_symbol(self, symbol: str) -> str:
        if symbol.upper() not in SYMBOLS:
            raise ProviderUnsupportedSymbol(symbol)
        return symbol.upper()

    async def get_quote(self, symbol: str) -> MarketQuote:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.fail = fail

    async def get(self, key: str):
        if self.fail:
            raise RedisError("offline")
        return self.values.get(key)

    async def set(self, key: str, value: str, **_: object):
        if self.fail:
            raise RedisError("offline")
        self.values[key] = value


def _quote(provider: str, price: str, *, age_seconds: int = 0) -> MarketQuote:
    return MarketQuote(
        provider=provider,
        symbol="BTCUSDT",
        last=Decimal(price),
        received_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        latency_ms=12.5,
    )


def _aggregator(primary, secondary, redis=None, *, deviation=100):
    return MarketDataAggregator(
        primary=primary,
        secondary=secondary,
        redis=redis,
        redis_prefix="gigveyro:test",
        cache_ttl_seconds=10,
        max_deviation_bps=deviation,
        failure_threshold=2,
        cooldown_seconds=30,
    )


@pytest.mark.asyncio
async def test_aggregator_primary_success_and_fallback():
    primary = StubProvider("binance", _quote("binance", "100"))
    secondary = StubProvider("bybit", _quote("bybit", "101"))
    assert (await _aggregator(primary, secondary).get_quote("BTCUSDT")).provider == "binance"

    failed = StubProvider("binance", ProviderUnavailable("down"))
    fallback = StubProvider("bybit", _quote("bybit", "101"))
    assert (await _aggregator(failed, fallback).get_quote("BTCUSDT")).provider == "bybit"


@pytest.mark.asyncio
async def test_aggregator_respects_bybit_primary_and_both_fail():
    bybit = StubProvider("bybit", _quote("bybit", "100"))
    binance = StubProvider("binance", _quote("binance", "100"))
    assert (await _aggregator(bybit, binance).get_quote("BTCUSDT")).provider == "bybit"

    aggregate = _aggregator(
        StubProvider("binance", ProviderUnavailable("down")),
        StubProvider("bybit", ProviderUnavailable("down")),
    )
    with pytest.raises(ProviderUnavailable, match="All public market data providers"):
        await aggregate.get_quote("BTCUSDT")


@pytest.mark.asyncio
async def test_aggregator_deviation_cache_and_stale_cache():
    redis = FakeRedis()
    primary = StubProvider("binance", _quote("binance", "100"))
    secondary = StubProvider("bybit", _quote("bybit", "103"))
    aggregate = _aggregator(primary, secondary, redis, deviation=100)
    comparison = await aggregate.compare_quotes("BTCUSDT")
    assert comparison["degraded"] is True
    assert Decimal(comparison["deviation_bps"]) > 100

    primary.calls = 0
    cached = await aggregate.get_quote("BTCUSDT")
    assert cached.cached is True
    assert primary.calls == 0

    key = "gigveyro:test:market:binance:BTCUSDT"
    redis.values[key] = json.dumps(_quote("binance", "99", age_seconds=20).to_dict())
    refreshed = await aggregate.get_quote("BTCUSDT")
    assert refreshed.cached is False
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_direct_and_singleflight_uses_cache():
    primary = StubProvider("binance", _quote("binance", "100"))
    aggregate = _aggregator(
        primary,
        StubProvider("bybit", _quote("bybit", "100")),
        FakeRedis(fail=True),
    )
    assert (await aggregate.get_quote("BTCUSDT")).last == Decimal("100")

    redis = FakeRedis()
    slow = StubProvider("binance", _quote("binance", "100"), delay=0.01)
    aggregate = _aggregator(slow, StubProvider("bybit", _quote("bybit", "100")), redis)
    quotes = await asyncio.gather(
        aggregate.get_quote("BTCUSDT"), aggregate.get_quote("BTCUSDT")
    )
    assert len(quotes) == 2
    assert slow.calls == 1
