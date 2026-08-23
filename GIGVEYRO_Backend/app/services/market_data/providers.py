from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.services.market_data.errors import ProviderBadResponse, ProviderUnsupportedSymbol
from app.services.market_data.http import MarketHttpClient
from app.services.market_data.models import MarketQuote


class PublicMarketProvider(ABC):
    name: str

    def __init__(self, client: MarketHttpClient, base_url: str, symbols: set[str]) -> None:
        self._client = client
        self.base_url = base_url.rstrip("/")
        self._symbols = symbols

    def validate_symbol(self, symbol: str) -> str:
        normalized = symbol.upper()
        if normalized not in self._symbols:
            raise ProviderUnsupportedSymbol(f"Unsupported market symbol: {normalized}")
        return normalized

    @abstractmethod
    async def get_quote(self, symbol: str) -> MarketQuote: ...


class BinanceMarketProvider(PublicMarketProvider):
    name = "binance"

    async def get_quote(self, symbol: str) -> MarketQuote:
        symbol = self.validate_symbol(symbol)
        started = time.monotonic()
        payload = await self._client.get_json(
            provider=self.name,
            url=f"{self.base_url}/api/v3/ticker/price",
            params={"symbol": symbol},
        )
        latency_ms = (time.monotonic() - started) * 1000
        if payload.get("symbol") != symbol:
            raise ProviderBadResponse("Binance ticker symbol did not match the request")
        last = _positive_decimal(payload.get("price"), "Binance price")
        return MarketQuote(
            provider=self.name,
            symbol=symbol,
            last=last,
            received_at=datetime.now(UTC),
            latency_ms=latency_ms,
        )


class BybitMarketProvider(PublicMarketProvider):
    name = "bybit"

    async def get_quote(self, symbol: str) -> MarketQuote:
        symbol = self.validate_symbol(symbol)
        started = time.monotonic()
        payload = await self._client.get_json(
            provider=self.name,
            url=f"{self.base_url}/v5/market/tickers",
            params={"category": "spot", "symbol": symbol},
        )
        latency_ms = (time.monotonic() - started) * 1000
        if payload.get("retCode") != 0:
            raise ProviderBadResponse("Bybit API rejected the public ticker request")
        result = payload.get("result")
        rows = result.get("list") if isinstance(result, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise ProviderBadResponse("Bybit ticker response contained no quote")
        ticker = rows[0]
        if ticker.get("symbol") != symbol:
            raise ProviderBadResponse("Bybit ticker symbol did not match the request")
        timestamp = _timestamp_ms(payload.get("time"))
        return MarketQuote(
            provider=self.name,
            symbol=symbol,
            last=_positive_decimal(ticker.get("lastPrice"), "Bybit lastPrice"),
            bid=_optional_decimal(ticker.get("bid1Price"), "Bybit bid1Price"),
            ask=_optional_decimal(ticker.get("ask1Price"), "Bybit ask1Price"),
            timestamp=timestamp,
            received_at=datetime.now(UTC),
            latency_ms=latency_ms,
        )


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProviderBadResponse(f"{field} was not a decimal") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ProviderBadResponse(f"{field} must be a positive finite decimal")
    return parsed


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    return _positive_decimal(value, field)


def _timestamp_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None
