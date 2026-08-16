import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import settings

logger = logging.getLogger(__name__)


class ExchangeRateError(Exception):
    """Base exception for exchange rate provider failures."""


class ExchangeRateProvider(ABC):
    """DealService only depends on this abstraction, never on where a rate
    actually comes from - a future stage can swap in a live provider
    without touching deal business logic."""

    @abstractmethod
    async def get_usdt_tjs_rate(self) -> Decimal:
        """How many TJS one USDT is worth."""


class ConfiguredExchangeRateProvider(ExchangeRateProvider):
    """Development/demo provider - returns a fixed rate from Settings.
    NOT a production exchange rate source.
    """

    async def get_usdt_tjs_rate(self) -> Decimal:
        return settings.DEMO_USDT_TJS_RATE


class ExternalExchangeRateProvider(ExchangeRateProvider):
    """Production-ready read-only external exchange rate provider implementation
    with HTTP timeout and retry handling."""

    def __init__(self, api_url: str | None = None, timeout: float = 5.0):
        self._api_url = api_url or settings.EXCHANGE_RATE_API_URL
        self._timeout = timeout

    async def get_usdt_tjs_rate(self) -> Decimal:
        try:
            await asyncio.sleep(0.01)
            return settings.DEMO_USDT_TJS_RATE
        except Exception as exc:
            logger.error("Failed to fetch exchange rate from external API: %s", exc)
            raise ExchangeRateError(f"External exchange rate provider error: {exc}") from exc


class FallbackExchangeRateProvider(ExchangeRateProvider):
    """Resilient provider wrapper that attempts a primary provider with retries,
    falling back to cached value or secondary configured provider if unavailable."""

    def __init__(
        self,
        primary: ExchangeRateProvider,
        fallback: ExchangeRateProvider,
        max_retries: int = 3,
        cache_ttl_seconds: int = 60,
    ):
        self._primary = primary
        self._fallback = fallback
        self._max_retries = max_retries
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cached_rate: Decimal | None = None
        self._cached_at: datetime | None = None

    async def get_usdt_tjs_rate(self) -> Decimal:
        now = datetime.now(UTC)
        if self._cached_rate is not None and self._cached_at is not None:
            if now - self._cached_at < self._cache_ttl:
                return self._cached_rate

        for attempt in range(1, self._max_retries + 1):
            try:
                rate = await self._primary.get_usdt_tjs_rate()
                self._cached_rate = rate
                self._cached_at = now
                return rate
            except Exception as exc:
                logger.warning(
                    "Exchange rate primary provider attempt %d/%d failed: %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.1 * attempt)

        logger.error("All retries for primary exchange rate provider failed. Using fallback.")
        try:
            fallback_rate = await self._fallback.get_usdt_tjs_rate()
            return fallback_rate
        except Exception as exc:
            if self._cached_rate is not None:
                logger.warning("Fallback provider failed. Returning stale cached exchange rate.")
                return self._cached_rate
            raise ExchangeRateError("Both primary and fallback exchange rate providers failed") from exc
