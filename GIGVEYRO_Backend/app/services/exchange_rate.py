from abc import ABC, abstractmethod
from decimal import Decimal

from app.core.config import settings


class ExchangeRateProvider(ABC):
    """DealService only depends on this abstraction, never on where a rate
    actually comes from - a future stage can swap in a live provider
    (Binance or similar) without touching deal business logic."""

    @abstractmethod
    async def get_usdt_tjs_rate(self) -> Decimal:
        """How many TJS one USDT is worth."""


class ConfiguredExchangeRateProvider(ExchangeRateProvider):
    """Development/demo provider - returns a fixed rate from Settings.
    NOT a production exchange rate source.
    """

    async def get_usdt_tjs_rate(self) -> Decimal:
        return settings.DEMO_USDT_TJS_RATE
