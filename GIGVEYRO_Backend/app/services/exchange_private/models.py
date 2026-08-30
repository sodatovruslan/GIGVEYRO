from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

PermissionSafety = Literal["READ_ONLY_SAFE", "OVER_PRIVILEGED", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class ExchangeApiKeyInfo:
    provider: str
    masked_key: str
    read_only: bool
    permission_safety: PermissionSafety
    ip_restricted: bool
    expires_at: str | None
    deadline_days: int | None
    account_type: str


@dataclass(frozen=True, slots=True)
class ExchangeAccountInfo:
    provider: str
    account_type: str
    account_mode: str
    margin_mode: str
    account_status: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExchangeBalance:
    provider: str
    asset: Literal["USDT", "USDC"]
    wallet_balance: Decimal
    available_balance: Decimal | None
    equity: Decimal | None
    received_at: datetime

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("wallet_balance", "available_balance", "equity"):
            value = payload[key]
            payload[key] = str(value) if value is not None else None
        payload["received_at"] = self.received_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ExchangeWithdrawalNetwork:
    provider: str
    asset: Literal["USDT", "USDC"]
    chain: str
    chain_type: str
    fixed_fee: Decimal
    percentage_fee: Decimal
    minimum_amount: Decimal
    maximum_amount: Decimal | None
    decimal_places: int
    withdraw_enabled: bool
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ExchangePrivateDiagnostics:
    provider: str
    configured: bool
    enabled: bool
    status: str
    authentication: str
    mode: Literal["READ_ONLY"]
    permission_safety: PermissionSafety
    masked_key: str | None
    ip_restricted: bool | None
    expires_at: str | None
    deadline_days: int | None
    account: ExchangeAccountInfo | None
    balances: list[ExchangeBalance]
    latency_ms: float | None
    last_success_at: datetime | None
    rate_limit_remaining: int | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["balances"] = [item.to_dict() for item in self.balances]
        payload["last_success_at"] = (
            self.last_success_at.isoformat() if self.last_success_at else None
        )
        if self.account and self.account.updated_at:
            payload["account"]["updated_at"] = self.account.updated_at.isoformat()
        return payload
