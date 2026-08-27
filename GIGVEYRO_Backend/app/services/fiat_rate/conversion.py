from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.enums.wallet import Currency
from app.services.fiat_rate.errors import (
    FiatProviderBadResponse,
    FiatProviderStale,
    FiatProviderUnsupportedPair,
)
from app.services.fiat_rate.models import FiatConversionQuote, FiatQuote
from app.services.fiat_rate.providers import NbtFiatRateProvider

logger = logging.getLogger(__name__)
_RATE_QUANTUM = Decimal("0.00000001")


class FiatConversionRateService:
    """Authoritative NBT TJS/RUB rate with destination-per-source semantics."""

    def __init__(
        self,
        *,
        provider: NbtFiatRateProvider,
        redis: Redis | None,
        redis_prefix: str,
        cache_ttl_seconds: int,
        max_age_seconds: int,
        markup_bps: int,
        fee_bps: int,
        policy_version: str,
    ) -> None:
        self._provider = provider
        self._redis = redis
        self._redis_prefix = redis_prefix
        self._cache_ttl = cache_ttl_seconds
        self._max_age = max_age_seconds
        self._adjustment_bps = Decimal(markup_bps + fee_bps)
        self._policy_version = policy_version

    async def get_quote(
        self, from_currency: Currency, to_currency: Currency
    ) -> FiatConversionQuote:
        self._validate_pair(from_currency, to_currency)
        cached = await self._cache_get(from_currency, to_currency)
        if cached is not None:
            self._reject_stale(cached)
            return cached

        nbt_quote = await self._provider.get_rate("RUB", "TJS")
        quote = self._compose(nbt_quote, from_currency, to_currency)
        self._reject_stale(quote)
        await self._cache_set(quote)
        return quote

    def _compose(
        self,
        nbt_quote: FiatQuote,
        from_currency: Currency,
        to_currency: Currency,
    ) -> FiatConversionQuote:
        direct_rate = nbt_quote.rate
        if from_currency == Currency.RUB and to_currency == Currency.TJS:
            rate = direct_rate
        else:
            rate = Decimal(1) / direct_rate
        adjustment = (Decimal(10_000) + self._adjustment_bps) / Decimal(10_000)
        rate = (rate * adjustment).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)
        if not rate.is_finite() or rate <= 0:
            raise FiatProviderBadResponse("Composed TJS/RUB conversion rate is invalid")
        return FiatConversionQuote(
            from_currency=from_currency.value,
            to_currency=to_currency.value,
            rate=rate,
            provider=nbt_quote.provider,
            published_at=nbt_quote.published_at,
            received_at=nbt_quote.received_at,
            source_type=nbt_quote.source_type,
            provider_nominal=nbt_quote.provider_nominal,
            provider_rate=nbt_quote.provider_rate or nbt_quote.rate,
            policy_version=self._policy_version,
            mode="official",
            is_stale=False,
        )

    @staticmethod
    def _validate_pair(from_currency: Currency, to_currency: Currency) -> None:
        if (
            from_currency not in Currency.managed_fiat()
            or to_currency not in Currency.managed_fiat()
        ):
            raise FiatProviderUnsupportedPair("Only TJS and RUB conversion is supported")
        if from_currency == to_currency:
            raise FiatProviderUnsupportedPair("Source and destination currencies must differ")

    def _reject_stale(self, quote: FiatConversionQuote) -> None:
        age = max((datetime.now(UTC) - quote.published_at).total_seconds(), 0)
        if quote.is_stale or age > self._max_age:
            raise FiatProviderStale("NBT TJS/RUB quote is stale")

    async def _cache_get(
        self, from_currency: Currency, to_currency: Currency
    ) -> FiatConversionQuote | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(self._cache_key(from_currency, to_currency))
            if not value:
                return None
            return FiatConversionQuote.from_dict(json.loads(value), cached=True)
        except (RedisError, ValueError, TypeError, KeyError):
            logger.warning("fiat.conversion.cache_unavailable")
            return None

    async def _cache_set(self, quote: FiatConversionQuote) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                self._cache_key(Currency(quote.from_currency), Currency(quote.to_currency)),
                json.dumps(quote.to_dict()),
                ex=self._cache_ttl,
            )
        except RedisError:
            logger.warning("fiat.conversion.cache_unavailable")

    def _cache_key(self, from_currency: Currency, to_currency: Currency) -> str:
        return (
            f"{self._redis_prefix}:fiat-conversion:nbt:"
            f"{from_currency.value}:{to_currency.value}"
        )
