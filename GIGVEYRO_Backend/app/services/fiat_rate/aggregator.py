from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.metrics import (
    observe_business_rate_deviation,
    observe_fiat_rate_age,
    record_fiat_failover,
    record_fiat_request,
)
from app.services.fiat_rate.errors import (
    FiatProviderError,
    FiatProviderStale,
    FiatProviderUnavailable,
)
from app.services.fiat_rate.models import FiatQuote, FiatSourceType
from app.services.fiat_rate.providers import FiatRateProvider

logger = logging.getLogger(__name__)


class FiatRateAggregator:
    def __init__(
        self,
        *,
        primary: FiatRateProvider,
        secondary: FiatRateProvider,
        redis: Redis | None,
        redis_prefix: str,
        cache_ttl_seconds: int,
        max_age_seconds: int,
        max_deviation_bps: int,
        allow_indicative_fallback: bool,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self._redis = redis
        self._redis_prefix = redis_prefix
        self._cache_ttl = cache_ttl_seconds
        self._max_age = max_age_seconds
        self._max_deviation_bps = Decimal(max_deviation_bps)
        self._allow_indicative_fallback = allow_indicative_fallback
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_provider: str | None = None
        self._last_deviation_bps: Decimal | None = None
        self._degraded = False

    async def get_rate(self, base: str = "USD", quote: str = "TJS") -> FiatQuote:
        pair = f"{base.upper()}:{quote.upper()}"
        lock = self._locks.setdefault(pair, asyncio.Lock())
        async with lock:
            try:
                primary = await self._get_provider_rate(self.primary, base, quote)
                if primary.is_stale:
                    raise FiatProviderStale(f"{self.primary.name} quote is stale")
                self._active_provider = primary.provider
                self._degraded = False
                return primary
            except FiatProviderError as primary_error:
                logger.warning(
                    "fiat.provider.failover provider=%s to=%s pair=%s/%s mode=fallback",
                    self.primary.name,
                    self.secondary.name,
                    base,
                    quote,
                )
                record_fiat_failover(self.primary.name, self.secondary.name)
                try:
                    secondary = await self._get_provider_rate(self.secondary, base, quote)
                except FiatProviderError as secondary_error:
                    self._active_provider = None
                    self._degraded = True
                    raise FiatProviderUnavailable("All fiat-rate providers are unavailable") from (
                        secondary_error
                    )
                if secondary.is_stale:
                    self._degraded = True
                    raise FiatProviderStale("All fiat-rate providers are stale") from primary_error
                if (
                    secondary.source_type == FiatSourceType.INDICATIVE_FX
                    and not self._allow_indicative_fallback
                ):
                    self._degraded = True
                    raise FiatProviderUnavailable(
                        "Indicative fiat fallback is disabled for business rates"
                    ) from primary_error
                self._active_provider = secondary.provider
                self._degraded = True
                return secondary

    async def compare_rates(self, base: str = "USD", quote: str = "TJS") -> dict[str, Any]:
        results = await asyncio.gather(
            self._get_provider_rate(self.primary, base, quote),
            self._get_provider_rate(self.secondary, base, quote),
            return_exceptions=True,
        )
        quotes: dict[str, FiatQuote] = {}
        errors: dict[str, str] = {}
        for provider, result in zip((self.primary, self.secondary), results, strict=True):
            if isinstance(result, FiatQuote):
                quotes[provider.name] = result
            else:
                errors[provider.name] = type(result).__name__
        deviation = None
        degraded = bool(errors)
        if len(quotes) == 2:
            values = list(quotes.values())
            deviation = _deviation_bps(values[0].rate, values[1].rate)
            self._last_deviation_bps = deviation
            observe_business_rate_deviation(float(deviation))
            if deviation > self._max_deviation_bps:
                degraded = True
                logger.warning(
                    "fiat.provider.deviation pair=%s/%s deviation_bps=%s",
                    base,
                    quote,
                    deviation,
                )
        self._degraded = degraded
        return {
            "quotes": {name: item.to_dict() for name, item in quotes.items()},
            "errors": errors,
            "deviation_bps": str(deviation) if deviation is not None else None,
            "degraded": degraded,
        }

    async def diagnostics(self) -> dict[str, Any]:
        comparison = await self.compare_rates()
        providers: dict[str, Any] = {}
        for provider in (self.primary, self.secondary):
            quote = comparison["quotes"].get(provider.name)
            if not quote:
                status = "unavailable"
            elif quote["is_stale"]:
                status = "stale"
            elif comparison["degraded"]:
                status = "degraded"
            else:
                status = "connected"
            providers[provider.name] = {
                "status": status,
                "source_type": provider.source_type.value,
                "pair": "USD/TJS",
                "rate": quote["rate"] if quote else None,
                "published_at": quote["published_at"] if quote else None,
                "received_at": quote["received_at"] if quote else None,
                "latency_ms": quote["latency_ms"] if quote else None,
                "cached": quote["cached"] if quote else False,
                "role": "primary" if provider is self.primary else "secondary",
                "business_fallback_allowed": (
                    provider.source_type == FiatSourceType.OFFICIAL
                    or self._allow_indicative_fallback
                ),
            }
        return {
            "status": "degraded" if comparison["degraded"] else "connected",
            "primary": self.primary.name,
            "secondary": self.secondary.name,
            "active_provider": self._active_provider,
            "cache": "redis" if self._redis is not None else "direct",
            "max_age_seconds": self._max_age,
            "deviation_bps": comparison["deviation_bps"],
            "providers": providers,
        }

    async def _get_provider_rate(
        self, provider: FiatRateProvider, base: str, quote: str
    ) -> FiatQuote:
        cached = await self._cache_get(provider.name, base, quote)
        if cached is not None:
            return self._apply_freshness(cached)
        started = time.monotonic()
        logger.info(
            "fiat.provider.request provider=%s pair=%s/%s mode=live", provider.name, base, quote
        )
        try:
            result = await provider.get_rate(base, quote)
        except FiatProviderError as exc:
            record_fiat_request(provider.name, "error", time.monotonic() - started)
            logger.warning(
                "fiat.provider.error provider=%s pair=%s/%s mode=%s",
                provider.name,
                base,
                quote,
                type(exc).__name__,
            )
            raise
        record_fiat_request(provider.name, "success", time.monotonic() - started)
        result = self._apply_freshness(result)
        await self._cache_set(result)
        logger.info(
            "fiat.provider.success provider=%s pair=%s/%s latency_ms=%.1f age_seconds=%.0f",
            provider.name,
            base,
            quote,
            result.latency_ms,
            self._age_seconds(result),
        )
        return result

    def _apply_freshness(self, quote: FiatQuote) -> FiatQuote:
        age = self._age_seconds(quote)
        observe_fiat_rate_age(quote.provider, age)
        stale = age > self._max_age
        if stale:
            logger.warning(
                "fiat.provider.stale provider=%s pair=%s/%s age_seconds=%.0f",
                quote.provider,
                quote.base_currency,
                quote.quote_currency,
                age,
            )
        return quote.with_state(is_stale=stale)

    def _age_seconds(self, quote: FiatQuote) -> float:
        return max((datetime.now(UTC) - quote.published_at).total_seconds(), 0.0)

    async def _cache_get(self, provider: str, base: str, quote: str) -> FiatQuote | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(self._cache_key(provider, base, quote))
            if not value:
                return None
            return FiatQuote.from_dict(json.loads(value), cached=True)
        except (RedisError, ValueError, TypeError, KeyError):
            logger.warning("fiat.provider.cache_unavailable provider=%s", provider)
            return None

    async def _cache_set(self, quote: FiatQuote) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                self._cache_key(quote.provider, quote.base_currency, quote.quote_currency),
                json.dumps(quote.to_dict()),
                ex=self._cache_ttl,
            )
        except RedisError:
            logger.warning("fiat.provider.cache_unavailable provider=%s", quote.provider)

    def _cache_key(self, provider: str, base: str, quote: str) -> str:
        return f"{self._redis_prefix}:fiat:{provider}:{base.upper()}:{quote.upper()}"


def _deviation_bps(first: Decimal, second: Decimal) -> Decimal:
    midpoint = (first + second) / Decimal(2)
    return (abs(first - second) / midpoint) * Decimal(10_000)
