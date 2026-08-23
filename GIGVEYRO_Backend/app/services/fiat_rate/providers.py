from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation

from app.services.fiat_rate.errors import (
    FiatProviderBadResponse,
    FiatProviderError,
    FiatProviderRateLimited,
    FiatProviderTimeout,
    FiatProviderUnavailable,
    FiatProviderUnsupportedPair,
)
from app.services.fiat_rate.models import FiatQuote, FiatSourceType
from app.services.market_data.errors import (
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
)
from app.services.market_data.http import MarketHttpClient

_DUSHANBE = timezone(timedelta(hours=5), name="Asia/Dushanbe")


class FiatRateProvider(ABC):
    name: str
    source_type: FiatSourceType

    def __init__(
        self,
        client: MarketHttpClient,
        base_url: str,
        *,
        minimum_rate: Decimal,
        maximum_rate: Decimal,
    ) -> None:
        self._client = client
        self.base_url = base_url
        self._minimum_rate = minimum_rate
        self._maximum_rate = maximum_rate

    def validate_pair(self, base: str, quote: str) -> tuple[str, str]:
        normalized = (base.upper(), quote.upper())
        if normalized != ("USD", "TJS"):
            raise FiatProviderUnsupportedPair(f"Unsupported fiat pair: {base}/{quote}")
        return normalized

    def validate_rate(self, value: object) -> Decimal:
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise FiatProviderBadResponse(f"{self.name} returned a non-decimal rate") from exc
        if not rate.is_finite() or rate <= 0:
            raise FiatProviderBadResponse(f"{self.name} returned a non-positive rate")
        if not self._minimum_rate <= rate <= self._maximum_rate:
            raise FiatProviderBadResponse(f"{self.name} rate failed configured sanity bounds")
        return rate

    @abstractmethod
    async def get_rate(self, base: str = "USD", quote: str = "TJS") -> FiatQuote: ...


class NbtFiatRateProvider(FiatRateProvider):
    name = "nbt"
    source_type = FiatSourceType.OFFICIAL

    def __init__(self, *args, today: Callable[[], date] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._today = today or (lambda: datetime.now(_DUSHANBE).date())

    async def get_rate(self, base: str = "USD", quote: str = "TJS") -> FiatQuote:
        base, quote = self.validate_pair(base, quote)
        last_error: FiatProviderError | None = None
        for offset in range(7):
            rate_date = self._today() - timedelta(days=offset)
            started = time.monotonic()
            try:
                xml = await self._client.get_text(
                    provider=self.name,
                    url=self.base_url,
                    params={"date": rate_date.isoformat(), "export": "xmlout"},
                )
                return self._parse(xml, base, quote, (time.monotonic() - started) * 1000)
            except Exception as exc:
                translated = _translate_error(exc, self.name)
                # NBT does not publish a separate quote on every calendar day and
                # may answer 5xx for non-publication dates. Only availability
                # failures justify looking back; malformed data, throttling and
                # permanent pair errors must remain explicit.
                if type(translated) is not FiatProviderUnavailable:
                    raise translated from exc
                last_error = translated
        raise FiatProviderUnavailable("NBT published no usable USD/TJS quote in seven days") from (
            last_error
        )

    def _parse(self, xml: str, base: str, quote: str, latency_ms: float) -> FiatQuote:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise FiatProviderBadResponse("NBT returned malformed XML") from exc
        if root.tag != "ValCurs" or not root.attrib.get("Date"):
            raise FiatProviderBadResponse("NBT XML omitted the publication date")
        row = next(
            (item for item in root.findall("Valute") if item.findtext("CharCode") == base),
            None,
        )
        if row is None:
            raise FiatProviderUnsupportedPair(f"NBT response omitted {base}/{quote}")
        try:
            nominal = Decimal(str(row.findtext("Nominal")))
            raw_rate = Decimal(str(row.findtext("Value")))
        except (InvalidOperation, ValueError) as exc:
            raise FiatProviderBadResponse("NBT returned invalid nominal or rate") from exc
        if nominal <= 0:
            raise FiatProviderBadResponse("NBT returned a non-positive nominal")
        rate = self.validate_rate(raw_rate / nominal)
        try:
            published_date = date.fromisoformat(root.attrib["Date"])
        except ValueError as exc:
            raise FiatProviderBadResponse("NBT returned an invalid publication date") from exc
        published_at = datetime.combine(
            published_date, datetime_time.min, tzinfo=_DUSHANBE
        ).astimezone(UTC)
        return FiatQuote(
            provider=self.name,
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            published_at=published_at,
            received_at=datetime.now(UTC),
            latency_ms=latency_ms,
            source_type=self.source_type,
        )


class ExchangeRateApiProvider(FiatRateProvider):
    name = "exchange_rate_api"
    source_type = FiatSourceType.INDICATIVE_FX

    async def get_rate(self, base: str = "USD", quote: str = "TJS") -> FiatQuote:
        base, quote = self.validate_pair(base, quote)
        started = time.monotonic()
        try:
            payload = await self._client.get_json(provider=self.name, url=self.base_url)
        except Exception as exc:
            raise _translate_error(exc, self.name) from exc
        if payload.get("result") != "success" or payload.get("base_code") != base:
            raise FiatProviderBadResponse("ExchangeRate-API returned an error response")
        rates = payload.get("rates")
        if not isinstance(rates, dict) or quote not in rates:
            raise FiatProviderUnsupportedPair(f"ExchangeRate-API omitted {base}/{quote}")
        rate = self.validate_rate(rates[quote])
        try:
            published_at = datetime.fromtimestamp(
                int(str(payload["time_last_update_unix"])), tz=UTC
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise FiatProviderBadResponse("ExchangeRate-API omitted its update timestamp") from exc
        return FiatQuote(
            provider=self.name,
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            published_at=published_at,
            received_at=datetime.now(UTC),
            latency_ms=(time.monotonic() - started) * 1000,
            source_type=self.source_type,
        )


def _translate_error(exc: Exception, provider: str) -> FiatProviderError:
    if isinstance(exc, ProviderTimeout):
        return FiatProviderTimeout(f"{provider} request timed out")
    if isinstance(exc, ProviderRateLimited):
        return FiatProviderRateLimited(f"{provider} rate limited the request")
    if isinstance(exc, ProviderUnsupportedSymbol):
        return FiatProviderUnsupportedPair(f"{provider} rejected USD/TJS")
    if isinstance(exc, ProviderBadResponse):
        return FiatProviderBadResponse(f"{provider} returned a malformed response")
    if isinstance(exc, ProviderUnavailable):
        return FiatProviderUnavailable(f"{provider} is unavailable")
    if isinstance(exc, FiatProviderError):
        return exc
    return FiatProviderUnavailable(f"{provider} request failed")
