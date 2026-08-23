from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.metrics import (
    observe_market_quote_age,
    record_market_cache_hit,
    record_market_failover,
    record_market_request,
)
from app.services.market_data.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.services.market_data.models import MarketQuote
from app.services.market_data.providers import PublicMarketProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderHealth:
    failures: int = 0
    cooldown_until: datetime | None = None
    last_success_at: datetime | None = None
    last_latency_ms: float | None = None

    def is_open(self, now: datetime) -> bool:
        return self.cooldown_until is not None and now < self.cooldown_until


class MarketDataAggregator:
    def __init__(
        self,
        *,
        primary: PublicMarketProvider,
        secondary: PublicMarketProvider,
        redis: Redis | None,
        redis_prefix: str,
        cache_ttl_seconds: int,
        max_deviation_bps: int,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self._redis = redis
        self._redis_prefix = redis_prefix
        self._cache_ttl = cache_ttl_seconds
        self._max_deviation_bps = Decimal(max_deviation_bps)
        self._failure_threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._health = {primary.name: ProviderHealth(), secondary.name: ProviderHealth()}
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_provider: str | None = None
        self._degraded = False

    async def get_quote(self, symbol: str) -> MarketQuote:
        symbol = self.primary.validate_symbol(symbol)
        cached = await self._cache_get(self.primary.name, symbol)
        if cached:
            self._active_provider = cached.provider
            return cached
        lock = self._locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            cached = await self._cache_get(self.primary.name, symbol)
            if cached:
                self._active_provider = cached.provider
                return cached
            return await self._query_with_failover(symbol)

    async def compare_quotes(self, symbol: str) -> dict[str, Any]:
        results = await asyncio.gather(
            self._query_provider(self.primary, symbol, use_cache=True),
            self._query_provider(self.secondary, symbol, use_cache=True),
            return_exceptions=True,
        )
        quotes: dict[str, MarketQuote] = {}
        errors: dict[str, str] = {}
        for provider, result in zip((self.primary, self.secondary), results, strict=True):
            if isinstance(result, MarketQuote):
                quotes[provider.name] = result
            else:
                errors[provider.name] = type(result).__name__
        if self.primary.name in quotes:
            self._active_provider = self.primary.name
        elif self.secondary.name in quotes:
            self._active_provider = self.secondary.name
        deviation = None
        if len(quotes) == 2:
            values = list(quotes.values())
            deviation = _deviation_bps(values[0].last, values[1].last)
            self._degraded = deviation > self._max_deviation_bps
            if self._degraded:
                logger.warning(
                    "market.provider.deviation primary=%s secondary=%s deviation_bps=%s",
                    self.primary.name,
                    self.secondary.name,
                    deviation,
                )
        elif errors:
            self._degraded = True
        return {
            "quotes": {name: quote.to_dict() for name, quote in quotes.items()},
            "errors": errors,
            "deviation_bps": str(deviation) if deviation is not None else None,
            "degraded": self._degraded,
        }

    async def diagnostics(self, symbol: str) -> dict[str, Any]:
        comparison = await self.compare_quotes(symbol)
        now = datetime.now(UTC)
        providers: dict[str, Any] = {}
        for provider in (self.primary, self.secondary):
            state = self._health[provider.name]
            quote = comparison["quotes"].get(provider.name)
            status = "connected" if quote else "unavailable"
            if state.is_open(now) or (quote and comparison["degraded"]):
                status = "degraded"
            providers[provider.name] = {
                "status": status,
                "public_api": True,
                "read_only": True,
                "base_url": provider.base_url,
                "latency_ms": quote["latency_ms"] if quote else state.last_latency_ms,
                "last_success_at": (
                    quote["received_at"] if quote else _isoformat(state.last_success_at)
                ),
                "role": "primary" if provider is self.primary else "fallback",
                "circuit": "open" if state.is_open(now) else "closed",
            }
        return {
            "primary": self.primary.name,
            "secondary": self.secondary.name,
            "active_provider": self._active_provider,
            "status": "degraded" if comparison["degraded"] else "connected",
            "cache": "redis" if self._redis is not None else "direct",
            "symbol": symbol,
            "deviation_bps": comparison["deviation_bps"],
            "providers": providers,
        }

    async def _query_with_failover(self, symbol: str) -> MarketQuote:
        try:
            quote = await self._query_provider(self.primary, symbol)
            self._active_provider = self.primary.name
            return quote
        except ProviderError as primary_error:
            logger.warning(
                "market.provider.failover from=%s to=%s reason=%s",
                self.primary.name,
                self.secondary.name,
                type(primary_error).__name__,
            )
            record_market_failover(self.primary.name, self.secondary.name)
            cached = await self._cache_get(self.secondary.name, symbol)
            if cached:
                self._active_provider = cached.provider
                return cached
            try:
                quote = await self._query_provider(self.secondary, symbol)
                self._active_provider = self.secondary.name
                return quote
            except ProviderError as secondary_error:
                self._degraded = True
                raise ProviderUnavailable(
                    "All public market data providers are unavailable"
                ) from secondary_error

    async def _query_provider(
        self, provider: PublicMarketProvider, symbol: str, *, use_cache: bool = False
    ) -> MarketQuote:
        if use_cache:
            cached = await self._cache_get(provider.name, symbol)
            if cached:
                return cached
        state = self._health[provider.name]
        now = datetime.now(UTC)
        if state.is_open(now):
            raise ProviderUnavailable(f"{provider.name} circuit is cooling down")
        started = time.monotonic()
        logger.info("market.provider.request provider=%s attempt=1", provider.name)
        try:
            quote = await provider.get_quote(symbol)
        except ProviderError as exc:
            state.failures += 1
            if state.failures >= self._failure_threshold:
                state.cooldown_until = now + self._cooldown
            record_market_request(provider.name, "error", time.monotonic() - started)
            if isinstance(exc, ProviderTimeout):
                event = "market.provider.timeout"
            elif isinstance(exc, ProviderRateLimited):
                event = "market.provider.rate_limited"
            else:
                event = "market.provider.error"
            logger.warning(
                "%s provider=%s status=error attempt=1 latency_ms=%.1f",
                event,
                provider.name,
                (time.monotonic() - started) * 1000,
            )
            raise
        record_market_request(provider.name, "success", time.monotonic() - started)
        logger.info(
            "market.provider.success provider=%s status=success attempt=1 latency_ms=%.1f",
            provider.name,
            quote.latency_ms,
        )
        state.failures = 0
        state.cooldown_until = None
        state.last_success_at = quote.received_at
        state.last_latency_ms = quote.latency_ms
        await self._cache_set(quote)
        observe_market_quote_age(provider.name, 0.0)
        return quote

    async def _cache_get(self, provider: str, symbol: str) -> MarketQuote | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(self._cache_key(provider, symbol))
            if not value:
                return None
            quote = MarketQuote.from_dict(json.loads(value), cached=True)
            age = max((datetime.now(UTC) - quote.received_at).total_seconds(), 0.0)
            if age > self._cache_ttl:
                return None
            record_market_cache_hit(provider)
            observe_market_quote_age(provider, age)
            return quote
        except (RedisError, ValueError, TypeError, KeyError):
            logger.warning("market.provider.cache_unavailable provider=%s", provider)
            return None

    async def _cache_set(self, quote: MarketQuote) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                self._cache_key(quote.provider, quote.symbol),
                json.dumps(quote.to_dict()),
                ex=self._cache_ttl,
            )
        except RedisError:
            logger.warning("market.provider.cache_unavailable provider=%s", quote.provider)

    def _cache_key(self, provider: str, symbol: str) -> str:
        return f"{self._redis_prefix}:market:{provider}:{symbol}"


def _deviation_bps(first: Decimal, second: Decimal) -> Decimal:
    midpoint = (first + second) / Decimal(2)
    return (abs(first - second) / midpoint) * Decimal(10_000)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
