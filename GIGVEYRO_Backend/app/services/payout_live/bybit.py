from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from app.enums.payout import PayoutProviderResult
from app.infra.metrics import record_payout_live_write
from app.models.payout import PayoutIntent
from app.services.payout_provider import ExchangePayoutProvider, ProviderPayoutResult

logger = logging.getLogger(__name__)

BYBIT_WITHDRAW_PATH = "/v5/asset/withdraw/create"
BYBIT_WITHDRAW_HISTORY_PATH = "/v5/asset/withdraw/query-record"
BYBIT_SERVER_TIME_PATH = "/v5/market/time"
_NETWORK_TO_BYBIT_CHAIN = {"TRC20": "TRX"}
_ALLOWED_ASSETS = {"USDT"}
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Bybit V5 retCode classification - verified against the official error-code
# reference. A code absent from every set below is treated as UNKNOWN (fails
# closed into reconciliation_required), never assumed safe.
_DUPLICATE_REQUEST_CODE = 131082
_PERMANENT_FAILURE_CODES = {
    131065: "KYC_INCOMPLETE",
    131066: "ADDRESS_WITHDRAWAL_UNSUPPORTED",
    131075: "SELF_TRANSFER_PROHIBITED",
    131083: "ADDRESS_NOT_ALLOWLISTED",
    131085: "RISK_DEPLOYMENT_LIMIT",
    131086: "RISK_MARGIN_LIMIT",
    131087: "RISK_LEVEL_TOO_HIGH",
    131088: "VERIFICATION_TIER_LIMIT",
    131089: "SENSITIVE_OPERATION_LOCKOUT",
    131090: "WITHDRAWAL_ACCESS_RESTRICTED",
    131093: "ADDRESS_NOT_IN_APPROVED_LIST",
    131094: "USER_NOT_ON_OPERATIONAL_WHITELIST",
    131095: "DAILY_PLATFORM_LIMIT_REACHED",
    131097: "COIN_WITHDRAWAL_UNAVAILABLE",
    110007: "INSUFFICIENT_AVAILABLE_BALANCE",
    110012: "INSUFFICIENT_AVAILABLE_BALANCE",
    110045: "INSUFFICIENT_WALLET_BALANCE",
}
_RATE_LIMIT_CODES = {10006, 10018}
_AUTH_CODES = {10003, 10004, 10005, 33004}
_TIMESTAMP_CODES = {10002}


class LivePayoutTransportError(Exception):
    """Safe normalized live-payout write failure. Never carries secrets, the
    destination address, or any other sensitive field in its message."""


class LivePayoutTimeout(LivePayoutTransportError):
    pass


class LivePayoutUnavailable(LivePayoutTransportError):
    pass


class LivePayoutRateLimited(LivePayoutTransportError):
    pass


class LivePayoutAuthenticationError(LivePayoutTransportError):
    pass


class LivePayoutPermissionError(LivePayoutTransportError):
    pass


class LivePayoutBadResponse(LivePayoutTransportError):
    pass


class LivePayoutDuplicateRequest(LivePayoutTransportError):
    """Bybit retCode 131082 - this requestId was already submitted. This is
    NOT a permission to create a new withdrawal and NOT proof of success -
    the caller must reconcile, never resubmit with a fresh requestId."""


class LivePayoutPermanentFailure(LivePayoutTransportError):
    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


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


def _canonical_query(params: dict[str, str]) -> str:
    return urlencode(sorted(params.items()))


def _write_backoff(attempt: int) -> float:
    return min(0.25 * (2**attempt) + random.uniform(0, 0.1), 2.0)


# Terminal-success / terminal-failure / non-terminal withdrawal record statuses,
# verified against the official Bybit V5 enum reference. Anything not listed
# here is treated as UNKNOWN (fails closed) rather than guessed.
_STATUS_SUCCEEDED = {"success", "BlockchainConfirmed"}
_STATUS_FAILED = {"Reject", "Fail", "CancelByUser"}
_STATUS_PENDING = {
    "Pending",
    "SecurityCheck",
    "MoreInformationRequired",
    "HighValueReviewPending",
    "HighValueReviewEDDSubmission",
}


def _map_withdraw_record_status(row: dict, withdraw_id: str) -> ProviderPayoutResult:
    status = row.get("status")
    if status in _STATUS_SUCCEEDED:
        return ProviderPayoutResult(PayoutProviderResult.SUCCEEDED, external_reference=withdraw_id)
    if status in _STATUS_FAILED:
        return ProviderPayoutResult(
            PayoutProviderResult.FAILED, external_reference=withdraw_id, failure_code=str(status)
        )
    if status in _STATUS_PENDING:
        return ProviderPayoutResult(PayoutProviderResult.PENDING, external_reference=withdraw_id)
    return ProviderPayoutResult(
        PayoutProviderResult.UNKNOWN,
        external_reference=withdraw_id,
        failure_code="UNRECOGNIZED_STATUS",
    )


class BybitWritePayoutClient:
    """Official Bybit V5 signed write client for exactly two endpoints:
    POST /v5/asset/withdraw/create and GET /v5/asset/withdraw/query-record.

    Uses BYBIT_WRITE_API_KEY/SECRET - entirely separate credentials from the
    read-only BybitPrivateClient (app.services.exchange_private.bybit), which
    this module never imports or shares state with.

    create_withdrawal() is attempted exactly once per call - no internal
    retry - because retrying a POST that may already have been accepted by
    Bybit risks submitting a second, real withdrawal. query_record() is a
    read and may retry safely on transient failures."""

    provider = "bybit"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        recv_window_ms: int,
        timeout_seconds: float,
        query_max_retries: int,
        client: httpx.AsyncClient | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._recv_window_ms = recv_window_ms
        self._query_max_retries = query_max_retries
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._clock_offset_ms = 0
        self._clock_synchronized = False
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            headers={"User-Agent": "GIGVEYRO-BybitLivePayoutWrite/1.0"},
        )
        self._owns_client = client is None

    def __repr__(self) -> str:
        return (
            "BybitWritePayoutClient(provider='bybit', mode='LIVE_WRITE', "
            f"configured={bool(self._api_key and self._api_secret)})"
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _sign(self, *, timestamp_ms: int, payload: str) -> str:
        message = f"{timestamp_ms}{self._api_key}{self._recv_window_ms}{payload}"
        return hmac.new(self._api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    def _headers(self, *, timestamp_ms: int, payload: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": str(timestamp_ms),
            "X-BAPI-RECV-WINDOW": str(self._recv_window_ms),
            "X-BAPI-SIGN": self._sign(timestamp_ms=timestamp_ms, payload=payload),
        }

    async def _ensure_clock_synced(self) -> None:
        if self._clock_synchronized:
            return
        try:
            response = await self._client.get(f"{self._base_url}{BYBIT_SERVER_TIME_PATH}")
            payload = response.json()
            server_time = payload.get("time") if isinstance(payload, dict) else None
            if (
                response.status_code != 200
                or not isinstance(payload, dict)
                or payload.get("retCode") != 0
                or server_time is None
            ):
                return
            self._clock_offset_ms = int(str(server_time)) - self._clock_ms()
            self._clock_synchronized = True
        except (httpx.HTTPError, TypeError, ValueError, json.JSONDecodeError):
            # Clock sync is best-effort. An unsynced clock either signs within
            # recv_window anyway, or Bybit rejects with a timestamp retCode,
            # which create_withdrawal() surfaces as LivePayoutBadResponse
            # (never silently retried on the write path).
            return

    async def create_withdrawal(self, dry_run: BybitWithdrawalDryRun) -> str:
        await self._ensure_clock_synced()
        timestamp = self._clock_ms() + self._clock_offset_ms
        headers = {
            **self._headers(timestamp_ms=timestamp, payload=dry_run.body),
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}{BYBIT_WITHDRAW_PATH}", content=dry_run.body, headers=headers
            )
        except httpx.TimeoutException as exc:
            record_payout_live_write("timeout")
            logger.warning("payout.live.write.timeout", extra={"provider": "bybit"})
            raise LivePayoutTimeout("Bybit withdrawal request timed out") from exc
        except httpx.RequestError as exc:
            record_payout_live_write("network_error")
            logger.warning("payout.live.write.network_error", extra={"provider": "bybit"})
            raise LivePayoutUnavailable("Bybit withdrawal request failed to send") from exc
        latency_ms = (time.monotonic() - started) * 1000
        return self._handle_create_response(response, latency_ms)

    def _handle_create_response(self, response: httpx.Response, latency_ms: float) -> str:
        if response.status_code in (401, 403):
            record_payout_live_write("auth_failed")
            raise LivePayoutAuthenticationError("Bybit rejected write authentication or IP access")
        if response.status_code == 429:
            record_payout_live_write("rate_limited")
            raise LivePayoutRateLimited("Bybit rate limited the withdrawal request")
        if response.status_code >= 500:
            record_payout_live_write("unavailable")
            raise LivePayoutUnavailable("Bybit was temporarily unavailable")
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            record_payout_live_write("bad_response")
            raise LivePayoutBadResponse("Bybit returned malformed JSON") from exc
        if not isinstance(payload, dict):
            record_payout_live_write("bad_response")
            raise LivePayoutBadResponse("Bybit returned a non-object response")
        code = payload.get("retCode")
        if code == 0:
            result = payload.get("result")
            withdraw_id = result.get("id") if isinstance(result, dict) else None
            if not isinstance(withdraw_id, str) or not withdraw_id:
                record_payout_live_write("bad_response")
                raise LivePayoutBadResponse("Bybit success response was missing a withdrawal id")
            record_payout_live_write("success")
            logger.info(
                "payout.live.write.success",
                extra={"provider": "bybit", "latency_ms": round(latency_ms, 2)},
            )
            return withdraw_id
        if code == _DUPLICATE_REQUEST_CODE:
            record_payout_live_write("duplicate")
            logger.warning("payout.live.write.duplicate_request", extra={"provider": "bybit"})
            raise LivePayoutDuplicateRequest("requestId was already submitted to Bybit")
        if code in _PERMANENT_FAILURE_CODES:
            reason = _PERMANENT_FAILURE_CODES[code]
            record_payout_live_write("permanent_failure")
            logger.warning(
                "payout.live.write.permanent_failure",
                extra={"provider": "bybit", "ret_code": code, "reason": reason},
            )
            raise LivePayoutPermanentFailure(code, reason)
        if code in _RATE_LIMIT_CODES:
            record_payout_live_write("rate_limited")
            raise LivePayoutRateLimited(f"Bybit rate limited the request (retCode={code})")
        if code in _AUTH_CODES:
            record_payout_live_write("auth_failed")
            raise LivePayoutAuthenticationError(
                f"Bybit rejected write credentials (retCode={code})"
            )
        if code in _TIMESTAMP_CODES:
            record_payout_live_write("timestamp_error")
            raise LivePayoutBadResponse(f"Bybit rejected the request timestamp (retCode={code})")
        record_payout_live_write("unknown_code")
        logger.warning(
            "payout.live.write.unrecognized_retcode", extra={"provider": "bybit", "ret_code": code}
        )
        raise LivePayoutBadResponse(f"Bybit returned an unrecognised retCode={code}")

    async def query_record(self, *, withdraw_id: str) -> dict | None:
        """Read-only lookup by Bybit's own withdrawId, safe to retry."""
        params = {"withdrawID": withdraw_id, "coin": "USDT", "withdrawType": "0", "limit": "1"}
        query = _canonical_query(params)
        last_error: LivePayoutTransportError | None = None
        for attempt in range(self._query_max_retries + 1):
            await self._ensure_clock_synced()
            timestamp = self._clock_ms() + self._clock_offset_ms
            headers = self._headers(timestamp_ms=timestamp, payload=query)
            try:
                response = await self._client.get(
                    f"{self._base_url}{BYBIT_WITHDRAW_HISTORY_PATH}", params=params, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = LivePayoutTimeout("Bybit query-record timed out")
                if attempt < self._query_max_retries:
                    await asyncio.sleep(_write_backoff(attempt))
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                last_error = LivePayoutUnavailable("Bybit query-record request failed")
                if attempt < self._query_max_retries:
                    await asyncio.sleep(_write_backoff(attempt))
                    continue
                raise last_error from exc
            if response.status_code == 429 or response.status_code >= 500:
                last_error = (
                    LivePayoutRateLimited("Bybit query-record was rate limited")
                    if response.status_code == 429
                    else LivePayoutUnavailable("Bybit query-record is temporarily unavailable")
                )
                if attempt < self._query_max_retries:
                    await asyncio.sleep(_write_backoff(attempt))
                    continue
                raise last_error
            if response.status_code in (401, 403):
                raise LivePayoutAuthenticationError(
                    "Bybit rejected query-record authentication or IP access"
                )
            try:
                payload = json.loads(response.text, parse_float=Decimal)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise LivePayoutBadResponse("Bybit query-record returned malformed JSON") from exc
            if not isinstance(payload, dict) or payload.get("retCode") != 0:
                raise LivePayoutBadResponse("Bybit query-record returned an error")
            result = payload.get("result")
            rows = result.get("rows") if isinstance(result, dict) else None
            if not isinstance(rows, list):
                raise LivePayoutBadResponse("Bybit query-record rows were malformed")
            return next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict) and row.get("withdrawId") == withdraw_id
                ),
                None,
            )
        raise last_error or LivePayoutUnavailable("Bybit query-record failed")


class BybitLivePayoutProvider(ExchangePayoutProvider):
    """Live Bybit withdrawal provider - USDT/TRC20 only (V1 scope). Reads
    withdrawal-network metadata/fees through the existing READ-ONLY
    BybitPrivateClient (BYBIT_API_KEY/SECRET, unchanged, untouched), and
    submits/queries withdrawals through a separate BybitWritePayoutClient
    (BYBIT_WRITE_API_KEY/SECRET). The two credential sets and the two HTTP
    clients are never shared or mixed."""

    def __init__(
        self,
        *,
        write_client: BybitWritePayoutClient | None = None,
        risk_repository=None,
    ) -> None:
        self._write_client = write_client
        self._owns_write_client = write_client is None
        self._risk_repository = risk_repository

    def __repr__(self) -> str:
        from app.core.config import settings

        configured = bool(
            settings.BYBIT_WRITE_API_KEY.get_secret_value()
            and settings.BYBIT_WRITE_API_SECRET.get_secret_value()
        )
        return f"BybitLivePayoutProvider(mode='LIVE', transport='HTTP', configured={configured})"

    def _get_write_client(self) -> BybitWritePayoutClient:
        from app.core.config import settings

        if self._write_client is None:
            if not settings.BYBIT_WRITE_ENABLED:
                raise LivePayoutNetworkBlocked("BYBIT_WRITE_NETWORK_DISABLED")
            self._write_client = BybitWritePayoutClient(
                base_url=settings.BYBIT_PUBLIC_BASE_URL,
                api_key=settings.BYBIT_WRITE_API_KEY.get_secret_value(),
                api_secret=settings.BYBIT_WRITE_API_SECRET.get_secret_value(),
                recv_window_ms=settings.BYBIT_WRITE_RECV_WINDOW_MS,
                timeout_seconds=settings.BYBIT_WRITE_TIMEOUT_SECONDS,
                query_max_retries=settings.BYBIT_WRITE_QUERY_MAX_RETRIES,
            )
        return self._write_client

    async def _build_dry_run(self, intent: PayoutIntent) -> BybitWithdrawalDryRun:
        from app.core.config import settings
        from app.services.exchange_private.runtime import get_bybit_private_client

        if intent.network != "TRC20":
            raise LivePayoutSecurityError("NETWORK_NOT_ALLOWED")
        read_client = get_bybit_private_client()
        networks = await read_client.get_withdrawal_networks(intent.asset)
        chain = next((item for item in networks if item.chain_type == "TRC20"), None)
        if chain is None:
            raise LivePayoutSecurityError("NETWORK_METADATA_UNAVAILABLE")
        metadata = BybitWithdrawalMetadata(
            asset=chain.asset,
            network="TRC20",
            bybit_chain=chain.chain,
            fixed_fee=chain.fixed_fee,
            percentage_fee=chain.percentage_fee,
            minimum_amount=chain.minimum_amount,
            maximum_amount=chain.maximum_amount,
            decimal_places=chain.decimal_places,
            withdraw_enabled=chain.withdraw_enabled,
            observed_at=chain.received_at,
        )
        return build_bybit_withdrawal_dry_run(
            intent=intent,
            metadata=metadata,
            now=datetime.now(UTC),
            max_metadata_age_seconds=settings.BYBIT_WITHDRAW_METADATA_MAX_AGE_SECONDS,
        )

    async def _verify_post_payout_reserve(self, dry_run: BybitWithdrawalDryRun) -> None:
        from app.services.risk import TreasurySnapshotService

        policy = await self._risk_repository.active_policy()
        snapshot = await TreasurySnapshotService(self._risk_repository).current(policy)
        required = (
            snapshot.total_internal_liability_usdt
            * Decimal(policy.minimum_reserve_ratio_bps)
            / Decimal(10000)
        )
        validate_post_payout_reserve(
            observed_reserve=snapshot.external_bybit_usdt,
            required_reserve=required,
            treasury_impact=dry_run.treasury_impact,
        )

    async def prepare(self, intent: PayoutIntent) -> None:
        await self._build_dry_run(intent)

    async def execute(self, intent: PayoutIntent) -> ProviderPayoutResult:
        try:
            dry_run = await self._build_dry_run(intent)
        except LivePayoutSecurityError as exc:
            return ProviderPayoutResult(PayoutProviderResult.FAILED, failure_code=str(exc))
        except RuntimeError:
            # The read-only metadata client isn't initialised (e.g. app not
            # started via the normal lifespan). We cannot safely price or
            # validate a withdrawal without it - fail closed, don't guess.
            return ProviderPayoutResult(
                PayoutProviderResult.FAILED, failure_code="READ_ONLY_CLIENT_UNAVAILABLE"
            )
        if self._risk_repository is not None:
            try:
                await self._verify_post_payout_reserve(dry_run)
            except LivePayoutSecurityError as exc:
                return ProviderPayoutResult(PayoutProviderResult.FAILED, failure_code=str(exc))
        intent.fee_amount = dry_run.network_fee
        try:
            client = self._get_write_client()
        except LivePayoutNetworkBlocked as exc:
            return ProviderPayoutResult(PayoutProviderResult.FAILED, failure_code=str(exc))
        try:
            withdraw_id = await client.create_withdrawal(dry_run)
        except LivePayoutDuplicateRequest:
            return ProviderPayoutResult(
                PayoutProviderResult.UNKNOWN,
                failure_code="DUPLICATE_REQUEST_REQUIRES_RECONCILIATION",
            )
        except LivePayoutPermanentFailure as exc:
            return ProviderPayoutResult(PayoutProviderResult.FAILED, failure_code=exc.reason)
        except LivePayoutTransportError as exc:
            return ProviderPayoutResult(
                PayoutProviderResult.UNKNOWN, failure_code=type(exc).__name__
            )
        return ProviderPayoutResult(PayoutProviderResult.SUCCEEDED, external_reference=withdraw_id)

    async def get_status(self, intent: PayoutIntent) -> ProviderPayoutResult:
        if not intent.external_reference:
            return ProviderPayoutResult(
                PayoutProviderResult.UNKNOWN, failure_code="NO_PROVIDER_REFERENCE_YET"
            )
        try:
            client = self._get_write_client()
            row = await client.query_record(withdraw_id=intent.external_reference)
        except LivePayoutTransportError as exc:
            return ProviderPayoutResult(
                PayoutProviderResult.UNKNOWN, failure_code=type(exc).__name__
            )
        if row is None:
            return ProviderPayoutResult(
                PayoutProviderResult.UNKNOWN, failure_code="RECORD_NOT_FOUND"
            )
        return _map_withdraw_record_status(row, intent.external_reference)

    async def close(self) -> None:
        if self._write_client is not None and self._owns_write_client:
            await self._write_client.close()
