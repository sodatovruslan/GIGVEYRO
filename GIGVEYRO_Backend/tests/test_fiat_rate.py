from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from redis.exceptions import RedisError

from app.enums.wallet import Currency
from app.services.exchange_rate import ExchangeRateError
from app.services.fiat_rate.aggregator import FiatRateAggregator
from app.services.fiat_rate.business import BusinessExchangeRateService
from app.services.fiat_rate.conversion import FiatConversionRateService
from app.services.fiat_rate.errors import (
    FiatProviderBadResponse,
    FiatProviderRateLimited,
    FiatProviderStale,
    FiatProviderTimeout,
    FiatProviderUnavailable,
    FiatProviderUnsupportedPair,
)
from app.services.fiat_rate.models import FiatQuote, FiatSourceType
from app.services.fiat_rate.providers import ExchangeRateApiProvider, NbtFiatRateProvider
from app.services.market_data.http import MarketHttpClient
from app.services.market_data.models import MarketQuote


def _client(handler, *, retries: int = 0) -> MarketHttpClient:
    return MarketHttpClient(
        timeout_seconds=0.05,
        max_retries=retries,
        max_concurrency=2,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _nbt_xml(*, value: str = "9.2521", nominal: str = "1", code: str = "USD") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ValCurs Date="2026-08-21">
  <Valute ID="840"><CharCode>{code}</CharCode><Nominal>{nominal}</Nominal>
  <Name>US Dollar</Name><Value>{value}</Value></Valute>
</ValCurs>"""


def _nbt(handler) -> NbtFiatRateProvider:
    return NbtFiatRateProvider(
        _client(handler),
        "https://nbt.test/export_xml.php",
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
        today=lambda: date(2026, 8, 23),
    )


@pytest.mark.asyncio
async def test_nbt_success_is_decimal_normalizes_nominal_and_uses_explicit_date():
    seen: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request
        return httpx.Response(200, text=_nbt_xml(value="92.521", nominal="10"))

    quote = await _nbt(handler).get_rate()
    assert quote.rate == Decimal("9.2521")
    assert quote.source_type == FiatSourceType.OFFICIAL
    assert quote.published_at == datetime(2026, 8, 20, 19, tzinfo=UTC)
    assert seen is not None
    assert seen.url.params["date"] == "2026-08-23"
    assert seen.url.params["export"] == "xmlout"


@pytest.mark.asyncio
async def test_nbt_looks_back_after_unpublished_date():
    dates: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dates.append(request.url.params["date"])
        if len(dates) < 3:
            return httpx.Response(500)
        return httpx.Response(200, text=_nbt_xml())

    quote = await _nbt(handler).get_rate()
    assert quote.rate == Decimal("9.2521")
    assert dates == ["2026-08-23", "2026-08-22", "2026-08-21"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, headers={"Retry-After": "0"}), FiatProviderRateLimited),
        (httpx.Response(200, text="not xml"), FiatProviderBadResponse),
        (httpx.Response(200, text=_nbt_xml(code="EUR")), FiatProviderUnsupportedPair),
        (httpx.Response(200, text=_nbt_xml(value="0")), FiatProviderBadResponse),
        (httpx.Response(200, text=_nbt_xml(value="10000")), FiatProviderBadResponse),
    ],
)
async def test_nbt_normalizes_permanent_provider_errors(response, error):
    with pytest.raises(error):
        await _nbt(lambda _: response).get_rate()


@pytest.mark.asyncio
async def test_nbt_normalizes_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(FiatProviderTimeout):
        await _nbt(handler).get_rate()


@pytest.mark.asyncio
async def test_nbt_rub_normalizes_official_nominal_before_rate_use():
    xml = _nbt_xml(value="11.09", nominal="100", code="RUB")
    provider = NbtFiatRateProvider(
        _client(lambda _: httpx.Response(200, text=xml)),
        "https://nbt.test/export_xml.php",
        minimum_rate=Decimal("0.01"),
        maximum_rate=Decimal("1"),
        today=lambda: date(2026, 8, 23),
    )
    quote = await provider.get_rate("RUB", "TJS")
    assert quote.rate == Decimal("0.1109")
    assert quote.provider_nominal == Decimal("100")
    assert quote.provider_rate == Decimal("11.09")


@pytest.mark.asyncio
async def test_tjs_rub_conversion_rate_has_destination_per_source_semantics():
    provider = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, _quote("nbt", "0.1109")
    )
    service = FiatConversionRateService(
        provider=provider,
        redis=None,
        redis_prefix="gigveyro:test",
        cache_ttl_seconds=60,
        max_age_seconds=3600,
        markup_bps=0,
        fee_bps=0,
        policy_version="test-v1",
    )
    rub_tjs = await service.get_quote(Currency.RUB, Currency.TJS)
    tjs_rub = await service.get_quote(Currency.TJS, Currency.RUB)
    assert rub_tjs.rate == Decimal("0.11090000")
    assert tjs_rub.rate == Decimal("9.01713255")
    assert abs((rub_tjs.rate * tjs_rub.rate) - Decimal("1")) < Decimal("1e-8")


@pytest.mark.asyncio
async def test_tjs_rub_conversion_rejects_stale_official_quote():
    stale = _quote("nbt", "0.1109", age_seconds=7200)
    provider = StubFiatProvider("nbt", FiatSourceType.OFFICIAL, stale)
    service = FiatConversionRateService(
        provider=provider,
        redis=None,
        redis_prefix="gigveyro:test",
        cache_ttl_seconds=60,
        max_age_seconds=3600,
        markup_bps=0,
        fee_bps=0,
        policy_version="test-v1",
    )
    with pytest.raises(FiatProviderStale):
        await service.get_quote(Currency.RUB, Currency.TJS)


def _exchange_api(handler) -> ExchangeRateApiProvider:
    return ExchangeRateApiProvider(
        _client(handler),
        "https://fx.test/latest/USD",
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
    )


@pytest.mark.asyncio
async def test_exchange_rate_api_success_and_timestamp():
    provider = _exchange_api(
        lambda _: httpx.Response(
            200,
            json={
                "result": "success",
                "base_code": "USD",
                "time_last_update_unix": 1787443200,
                "rates": {"TJS": 9.16235},
            },
        )
    )
    quote = await provider.get_rate()
    assert quote.rate == Decimal("9.16235")
    assert quote.source_type == FiatSourceType.INDICATIVE_FX
    assert quote.published_at == datetime.fromtimestamp(1787443200, tz=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"result": "error"},
        {"result": "success", "base_code": "USD", "rates": {}},
        {"result": "success", "base_code": "EUR", "rates": {"TJS": "9"}},
    ],
)
async def test_exchange_rate_api_rejects_errors_and_missing_pair(payload):
    provider = _exchange_api(lambda _: httpx.Response(200, json=payload))
    with pytest.raises((FiatProviderBadResponse, FiatProviderUnsupportedPair)):
        await provider.get_rate()


class StubFiatProvider:
    def __init__(self, name: str, source_type: FiatSourceType, result):
        self.name = name
        self.source_type = source_type
        self.result = result
        self.calls = 0

    async def get_rate(self, base: str = "USD", quote: str = "TJS") -> FiatQuote:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeRedis:
    def __init__(self, *, fail: bool = False):
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


def _quote(
    provider: str,
    rate: str,
    *,
    source_type: FiatSourceType = FiatSourceType.OFFICIAL,
    age_seconds: int = 0,
) -> FiatQuote:
    now = datetime.now(UTC)
    return FiatQuote(
        provider=provider,
        base_currency="USD",
        quote_currency="TJS",
        rate=Decimal(rate),
        published_at=now - timedelta(seconds=age_seconds),
        received_at=now,
        latency_ms=4.2,
        source_type=source_type,
    )


def _aggregator(primary, secondary, redis=None, *, allow=False, max_age=3600, deviation=500):
    return FiatRateAggregator(
        primary=primary,
        secondary=secondary,
        redis=redis,
        redis_prefix="gigveyro:test",
        cache_ttl_seconds=600,
        max_age_seconds=max_age,
        max_deviation_bps=deviation,
        allow_indicative_fallback=allow,
    )


@pytest.mark.asyncio
async def test_primary_success_and_fresh_redis_cache():
    redis = FakeRedis()
    primary = StubFiatProvider("nbt", FiatSourceType.OFFICIAL, _quote("nbt", "9.25"))
    secondary = StubFiatProvider(
        "fx", FiatSourceType.INDICATIVE_FX, _quote("fx", "9.20")
    )
    aggregator = _aggregator(primary, secondary, redis)
    first = await aggregator.get_rate()
    second = await aggregator.get_rate()
    assert first.rate == second.rate == Decimal("9.25")
    assert second.cached is True
    assert primary.calls == 1
    assert "gigveyro:test:fiat:nbt:USD:TJS" in redis.values


@pytest.mark.asyncio
async def test_primary_failure_uses_allowed_secondary_and_marks_degraded():
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, FiatProviderUnavailable("offline")
    )
    secondary = StubFiatProvider(
        "fx",
        FiatSourceType.INDICATIVE_FX,
        _quote("fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX),
    )
    aggregator = _aggregator(primary, secondary, allow=True)
    assert (await aggregator.get_rate()).provider == "fx"
    assert (await aggregator.diagnostics())["status"] == "degraded"


@pytest.mark.asyncio
async def test_indicative_secondary_is_fail_closed_by_default():
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, FiatProviderUnavailable("offline")
    )
    secondary = StubFiatProvider(
        "fx",
        FiatSourceType.INDICATIVE_FX,
        _quote("fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX),
    )
    with pytest.raises(FiatProviderUnavailable, match="disabled"):
        await _aggregator(primary, secondary).get_rate()


@pytest.mark.asyncio
async def test_stale_primary_falls_back_and_both_stale_fail():
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, _quote("nbt", "9.25", age_seconds=7200)
    )
    secondary = StubFiatProvider(
        "fx",
        FiatSourceType.INDICATIVE_FX,
        _quote("fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX),
    )
    assert (await _aggregator(primary, secondary, allow=True).get_rate()).provider == "fx"
    secondary.result = _quote(
        "fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX, age_seconds=7200
    )
    with pytest.raises(FiatProviderStale):
        await _aggregator(primary, secondary, allow=True).get_rate()


@pytest.mark.asyncio
async def test_both_fail_and_redis_outage_falls_through_to_live_provider():
    failing = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, FiatProviderUnavailable("offline")
    )
    secondary_failure = StubFiatProvider(
        "fx", FiatSourceType.INDICATIVE_FX, FiatProviderUnavailable("offline")
    )
    with pytest.raises(FiatProviderUnavailable, match="All"):
        await _aggregator(failing, secondary_failure).get_rate()

    live = StubFiatProvider("nbt", FiatSourceType.OFFICIAL, _quote("nbt", "9.25"))
    result = await _aggregator(live, secondary_failure, FakeRedis(fail=True)).get_rate()
    assert result.rate == Decimal("9.25")


@pytest.mark.asyncio
async def test_cached_stale_quote_is_rejected_and_large_deviation_degrades():
    redis = FakeRedis()
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, _quote("nbt", "9.25", age_seconds=7200)
    )
    secondary = StubFiatProvider(
        "fx",
        FiatSourceType.INDICATIVE_FX,
        _quote("fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX),
    )
    seeded = _aggregator(primary, secondary, redis, allow=True)
    await seeded._cache_set(primary.result)
    assert (await seeded.get_rate()).provider == "fx"

    primary.result = _quote("nbt", "10.00")
    comparison = await _aggregator(primary, secondary, deviation=50).compare_rates()
    assert Decimal(comparison["deviation_bps"]) > Decimal("50")
    assert comparison["degraded"] is True


class UnusedMarket:
    async def get_quote(self, symbol: str):
        raise AssertionError(f"market should not be called in fixed mode: {symbol}")


class StubMarket:
    async def get_quote(self, symbol: str) -> MarketQuote:
        assert symbol == "USDCUSDT"
        return MarketQuote(
            provider="binance",
            symbol=symbol,
            last=Decimal("0.998"),
            received_at=datetime.now(UTC),
            latency_ms=3.0,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fiat_rate", "expected"),
    [("10.50", "10.50000000"), ("9.2521", "9.25210000"), ("9.123456789", "9.12345679")],
)
async def test_business_rate_fixed_policy_decimal_and_snapshot(fiat_rate, expected):
    primary = StubFiatProvider("nbt", FiatSourceType.OFFICIAL, _quote("nbt", fiat_rate))
    secondary = StubFiatProvider(
        "fx", FiatSourceType.INDICATIVE_FX, FiatProviderUnavailable("unused")
    )
    service = BusinessExchangeRateService(
        fiat=_aggregator(primary, secondary),
        market=UnusedMarket(),
        peg_mode="fixed",
        fixed_usdt_usd_rate=Decimal("1.0000"),
        markup_bps=0,
        spread_bps=0,
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
        policy_version="official-fiat-fixed-peg-v1",
    )
    snapshot = await service.calculate()
    assert snapshot.rate_tjs_per_usdt == Decimal(expected)
    assert snapshot.fiat_provider == "nbt"
    assert snapshot.peg_mode == "fixed"
    assert snapshot.policy_version == "official-fiat-fixed-peg-v1"
    assert snapshot.is_degraded is False


@pytest.mark.asyncio
async def test_business_rate_rejects_unavailable_authoritative_rate():
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, FiatProviderUnavailable("offline")
    )
    secondary = StubFiatProvider(
        "fx", FiatSourceType.INDICATIVE_FX, FiatProviderUnavailable("offline")
    )
    service = BusinessExchangeRateService(
        fiat=_aggregator(primary, secondary),
        market=UnusedMarket(),
        peg_mode="fixed",
        fixed_usdt_usd_rate=Decimal("1"),
        markup_bps=0,
        spread_bps=0,
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
        policy_version="v1",
    )
    with pytest.raises(ExchangeRateError, match="Authoritative"):
        await service.calculate()


@pytest.mark.asyncio
async def test_business_rate_market_peg_uses_inverse_usdcusdt_reference():
    primary = StubFiatProvider("nbt", FiatSourceType.OFFICIAL, _quote("nbt", "9.25"))
    secondary = StubFiatProvider(
        "fx", FiatSourceType.INDICATIVE_FX, FiatProviderUnavailable("unused")
    )
    service = BusinessExchangeRateService(
        fiat=_aggregator(primary, secondary),
        market=StubMarket(),
        peg_mode="market",
        fixed_usdt_usd_rate=Decimal("1"),
        markup_bps=0,
        spread_bps=0,
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
        policy_version="market-v1",
    )
    snapshot = await service.calculate()
    assert snapshot.usdt_usd_rate == Decimal(1) / Decimal("0.998")
    assert snapshot.rate_tjs_per_usdt == Decimal("9.26853707")
    assert snapshot.market_provider == "binance"


@pytest.mark.asyncio
async def test_business_snapshot_marks_allowed_indicative_fallback_degraded():
    primary = StubFiatProvider(
        "nbt", FiatSourceType.OFFICIAL, FiatProviderUnavailable("offline")
    )
    secondary = StubFiatProvider(
        "fx",
        FiatSourceType.INDICATIVE_FX,
        _quote("fx", "9.20", source_type=FiatSourceType.INDICATIVE_FX),
    )
    service = BusinessExchangeRateService(
        fiat=_aggregator(primary, secondary, allow=True),
        market=UnusedMarket(),
        peg_mode="fixed",
        fixed_usdt_usd_rate=Decimal("1"),
        markup_bps=0,
        spread_bps=0,
        minimum_rate=Decimal("5"),
        maximum_rate=Decimal("20"),
        policy_version="v1",
    )
    snapshot = await service.calculate()
    assert snapshot.is_degraded is True
    assert snapshot.mode == "fallback"
