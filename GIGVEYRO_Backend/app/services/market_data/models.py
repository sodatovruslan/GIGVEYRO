from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketQuote:
    provider: str
    symbol: str
    last: Decimal
    received_at: datetime
    latency_ms: float
    bid: Decimal | None = None
    ask: Decimal | None = None
    timestamp: datetime | None = None
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("last", "bid", "ask"):
            value = payload[key]
            payload[key] = str(value) if value is not None else None
        for key in ("timestamp", "received_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value is not None else None
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, cached: bool = False) -> MarketQuote:
        return cls(
            provider=str(payload["provider"]),
            symbol=str(payload["symbol"]),
            last=Decimal(str(payload["last"])),
            bid=Decimal(str(payload["bid"])) if payload.get("bid") is not None else None,
            ask=Decimal(str(payload["ask"])) if payload.get("ask") is not None else None,
            timestamp=_parse_datetime(payload.get("timestamp")),
            received_at=_parse_datetime(payload["received_at"]) or datetime.now(UTC),
            latency_ms=float(payload["latency_ms"]),
            cached=cached,
        )


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
