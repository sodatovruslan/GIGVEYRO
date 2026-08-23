from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class FiatSourceType(StrEnum):
    OFFICIAL = "official"
    INDICATIVE_FX = "indicative_fx"


@dataclass(frozen=True, slots=True)
class FiatQuote:
    provider: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    published_at: datetime
    received_at: datetime
    latency_ms: float
    source_type: FiatSourceType
    is_stale: bool = False
    cached: bool = False

    def with_state(self, *, is_stale: bool | None = None, cached: bool | None = None) -> FiatQuote:
        return replace(
            self,
            is_stale=self.is_stale if is_stale is None else is_stale,
            cached=self.cached if cached is None else cached,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rate"] = str(self.rate)
        payload["published_at"] = self.published_at.isoformat()
        payload["received_at"] = self.received_at.isoformat()
        payload["source_type"] = self.source_type.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, cached: bool = False) -> FiatQuote:
        return cls(
            provider=str(payload["provider"]),
            base_currency=str(payload["base_currency"]),
            quote_currency=str(payload["quote_currency"]),
            rate=Decimal(str(payload["rate"])),
            published_at=datetime.fromisoformat(str(payload["published_at"])),
            received_at=datetime.fromisoformat(str(payload["received_at"])),
            latency_ms=float(payload["latency_ms"]),
            source_type=FiatSourceType(str(payload["source_type"])),
            is_stale=bool(payload.get("is_stale", False)),
            cached=cached,
        )


@dataclass(frozen=True, slots=True)
class BusinessRateSnapshot:
    rate_tjs_per_usdt: Decimal
    fiat_rate_tjs_per_usd: Decimal
    usdt_usd_rate: Decimal
    fiat_provider: str
    fiat_source_type: FiatSourceType
    market_provider: str
    fiat_published_at: datetime
    market_received_at: datetime | None
    calculated_at: datetime
    peg_mode: str
    policy_version: str
    mode: str
    is_degraded: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("rate_tjs_per_usdt", "fiat_rate_tjs_per_usd", "usdt_usd_rate"):
            payload[key] = str(payload[key])
        payload["fiat_source_type"] = self.fiat_source_type.value
        for key in ("fiat_published_at", "market_received_at", "calculated_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value is not None else None
        return payload
