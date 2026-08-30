from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import SecretStr

from app.enums.payout import PayoutProviderResult
from app.models.payout import PayoutIntent
from app.services.payout_provider import ExchangePayoutProvider, ProviderPayoutResult

BYBIT_WITHDRAW_PATH = "/v5/asset/withdraw/create"
BYBIT_WITHDRAW_HISTORY_PATH = "/v5/asset/withdraw/query-record"
_NETWORK_TO_BYBIT_CHAIN = {"TRC20": "TRX"}
_ALLOWED_ASSETS = {"USDT"}
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class LivePayoutSecurityError(Exception):
    pass


class LivePayoutNetworkBlocked(LivePayoutSecurityError):
    pass


@dataclass(frozen=True, slots=True)
class BybitWithdrawalMetadata:
    asset: str
    network: str
    bybit_chain: str
    fixed_fee: Decimal
    percentage_fee: Decimal
    minimum_amount: Decimal
    maximum_amount: Decimal | None
    decimal_places: int
    withdraw_enabled: bool
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class BybitWithdrawalDryRun:
    path: str
    body: str
    request_id: str
    recipient_amount: Decimal
    network_fee: Decimal
    treasury_impact: Decimal
    metadata_observed_at: datetime

    def __repr__(self) -> str:
        return (
            "BybitWithdrawalDryRun(path='/v5/asset/withdraw/create', "
            f"request_id='{self.request_id}', recipient_amount={self.recipient_amount}, "
            "destination='[REDACTED]')"
        )


@dataclass(frozen=True, slots=True)
class DryRunAuthEnvelope:
    timestamp_ms: int
    recv_window_ms: int
    signature: str
    api_key_configured: bool

    def __repr__(self) -> str:
        return (
            "DryRunAuthEnvelope(api_key='[REDACTED]', signature='[REDACTED]', "
            f"timestamp_ms={self.timestamp_ms}, recv_window_ms={self.recv_window_ms})"
        )


def validate_tron_base58check(address: str) -> None:
    if len(address) != 34 or not address.startswith("T"):
        raise LivePayoutSecurityError("INVALID_TRC20_ADDRESS")
    number = 0
    try:
        for char in address:
            number = number * 58 + _BASE58_ALPHABET.index(char)
    except ValueError as exc:
        raise LivePayoutSecurityError("INVALID_TRC20_ADDRESS") from exc
    decoded = number.to_bytes(25, "big")
    if decoded[0] != 0x41:
        raise LivePayoutSecurityError("INVALID_TRC20_ADDRESS")
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if not hmac.compare_digest(checksum, expected):
        raise LivePayoutSecurityError("INVALID_TRC20_CHECKSUM")


def destination_fingerprint(asset: str, network: str, address: str) -> str:
    normalized = f"{asset.upper()}|{network.upper()}|{address}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def mask_live_destination(address: str) -> str:
    return address if len(address) <= 10 else f"{address[:5]}…{address[-5:]}"


def build_bybit_withdrawal_dry_run(
    *,
    intent: PayoutIntent,
    metadata: BybitWithdrawalMetadata,
    now: datetime,
    max_metadata_age_seconds: int,
) -> BybitWithdrawalDryRun:
    asset = intent.asset.upper()
    network = intent.network.upper()
    if asset not in _ALLOWED_ASSETS:
        raise LivePayoutSecurityError("ASSET_NOT_ALLOWED")
    if network not in _NETWORK_TO_BYBIT_CHAIN:
        raise LivePayoutSecurityError("NETWORK_NOT_ALLOWED")
    if metadata.asset != asset or metadata.network != network:
        raise LivePayoutSecurityError("WITHDRAW_METADATA_MISMATCH")
    if metadata.bybit_chain != _NETWORK_TO_BYBIT_CHAIN[network]:
        raise LivePayoutSecurityError("BYBIT_CHAIN_MISMATCH")
    if not metadata.withdraw_enabled:
        raise LivePayoutSecurityError("NETWORK_WITHDRAWAL_DISABLED")
    age = (now.astimezone(UTC) - metadata.observed_at.astimezone(UTC)).total_seconds()
    if age < 0 or age > max_metadata_age_seconds:
        raise LivePayoutSecurityError("WITHDRAW_METADATA_STALE")
    validate_tron_base58check(intent.destination)
    amount = Decimal(intent.amount)
    if not amount.is_finite() or amount <= 0:
        raise LivePayoutSecurityError("INVALID_WITHDRAW_AMOUNT")
    if amount < metadata.minimum_amount:
        raise LivePayoutSecurityError("BELOW_PROVIDER_WITHDRAW_MINIMUM")
    if metadata.maximum_amount is not None and amount > metadata.maximum_amount:
        raise LivePayoutSecurityError("ABOVE_PROVIDER_WITHDRAW_MAXIMUM")
    exponent = -amount.as_tuple().exponent
    if exponent > metadata.decimal_places:
        raise LivePayoutSecurityError("INVALID_WITHDRAW_PRECISION")
    if not Decimal("0") <= metadata.percentage_fee < Decimal("1"):
        raise LivePayoutSecurityError("INVALID_PROVIDER_FEE")
    percentage = (
        amount / (Decimal("1") - metadata.percentage_fee) * metadata.percentage_fee
        if metadata.percentage_fee
        else Decimal("0")
    )
    fee = metadata.fixed_fee + percentage
    if not fee.is_finite() or fee < 0:
        raise LivePayoutSecurityError("INVALID_PROVIDER_FEE")
    request_id = intent.id.hex
    payload = {
        "accountType": "UTA",
        "address": intent.destination,
        "amount": format(amount, "f"),
        "chain": metadata.bybit_chain,
        "coin": asset,
        "feeType": 0,
        "forceChain": 1,
        "requestId": request_id,
        "timestamp": int(now.timestamp() * 1000),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return BybitWithdrawalDryRun(
        path=BYBIT_WITHDRAW_PATH,
        body=body,
        request_id=request_id,
        recipient_amount=amount,
        network_fee=fee,
        treasury_impact=amount + fee,
        metadata_observed_at=metadata.observed_at,
    )


def sign_post_dry_run(
    *,
    timestamp_ms: int,
    recv_window_ms: int,
    api_key: SecretStr,
    api_secret: SecretStr,
    body: str,
) -> DryRunAuthEnvelope:
    key = api_key.get_secret_value()
    secret = api_secret.get_secret_value()
    if not key or not secret:
        raise LivePayoutSecurityError("WRITE_CREDENTIALS_MISSING")
    message = f"{timestamp_ms}{key}{recv_window_ms}{body}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return DryRunAuthEnvelope(timestamp_ms, recv_window_ms, signature, True)


def validate_post_payout_reserve(
    *, observed_reserve: Decimal, required_reserve: Decimal, treasury_impact: Decimal
) -> Decimal:
    values = (observed_reserve, required_reserve, treasury_impact)
    if any(not value.is_finite() or value < 0 for value in values):
        raise LivePayoutSecurityError("INVALID_RESERVE_INPUT")
    remaining = observed_reserve - treasury_impact
    if remaining < required_reserve:
        raise LivePayoutSecurityError("POST_PAYOUT_RESERVE_INSUFFICIENT")
    return remaining


class BybitLivePayoutProvider(ExchangePayoutProvider):
    """Non-network-capable skeleton. It cannot submit or reconcile a live withdrawal."""

    def __repr__(self) -> str:
        return "BybitLivePayoutProvider(mode='LIVE_DISABLED', transport='NONE')"

    async def prepare(self, intent: PayoutIntent) -> None:
        raise LivePayoutNetworkBlocked("BYBIT_WRITE_NETWORK_DISABLED")

    async def execute(self, intent: PayoutIntent) -> ProviderPayoutResult:
        raise LivePayoutNetworkBlocked("BYBIT_WRITE_NETWORK_DISABLED")

    async def get_status(self, intent: PayoutIntent) -> ProviderPayoutResult:
        return ProviderPayoutResult(PayoutProviderResult.UNKNOWN, failure_code="LIVE_READ_DISABLED")
