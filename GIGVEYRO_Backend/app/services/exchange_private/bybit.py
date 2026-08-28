from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

from app.infra.metrics import (
    record_exchange_private_auth_failure,
    record_exchange_private_rate_limit,
    record_exchange_private_request,
)
from app.services.exchange_private.errors import (
    ExchangePrivateAuthenticationError,
    ExchangePrivateBadResponse,
    ExchangePrivateError,
    ExchangePrivatePermissionError,
    ExchangePrivateRateLimited,
    ExchangePrivateTimeout,
    ExchangePrivateTimestampError,
    ExchangePrivateUnavailable,
)
from app.services.exchange_private.models import (
    ExchangeAccountInfo,
    ExchangeApiKeyInfo,
    ExchangeBalance,
)

logger = logging.getLogger(__name__)
_ALLOWED_COINS = ("USDT", "USDC")
_RETRYABLE_RET_CODES = {10000, 10006, 10016}
_AUTH_RET_CODES = {-2015, 33004, 10003, 10004, 10007}


def canonical_query(params: Mapping[str, str] | None) -> str:
    return urlencode(sorted((params or {}).items()))


def sign_get(
    *, timestamp_ms: int, api_key: str, recv_window_ms: int, query: str, secret: str
) -> str:
    payload = f"{timestamp_ms}{api_key}{recv_window_ms}{query}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class BybitPrivateClient:
    """Official Bybit V5 signed GET-only client. No write method exists."""

    provider = "bybit"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        recv_window_ms: int,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._recv_window_ms = recv_window_ms
        self._max_retries = max_retries
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._clock_offset_ms = 0
        self._clock_synchronized = False
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            headers={"User-Agent": "GIGVEYRO-BybitPrivateReadOnly/1.0"},
        )
        self._owns_client = client is None
        self.last_latency_ms: float | None = None
        self.last_success_at: datetime | None = None
        self.rate_limit_remaining: int | None = None

    def __repr__(self) -> str:
        return (
            "BybitPrivateClient(provider='bybit', mode='READ_ONLY', "
            f"configured={bool(self._api_key and self._api_secret)})"
        )

    async def get_api_key_info(self) -> ExchangeApiKeyInfo:
        result = await self._get("/v5/user/query-api", None, "api_key_info")
        read_only = result.get("readOnly") == 1
        permissions = result.get("permissions")
        if not isinstance(permissions, dict):
            raise ExchangePrivateBadResponse("Bybit API key permissions were malformed")
        wallet_permissions = permissions.get("Wallet", [])
        has_withdraw = isinstance(wallet_permissions, list) and "Withdraw" in wallet_permissions
        safe = read_only and not has_withdraw
        ips = result.get("ips")
        deadline = result.get("deadlineDay")
        return ExchangeApiKeyInfo(
            provider=self.provider,
            masked_key=_mask_key(self._api_key),
            read_only=read_only,
            permission_safety="READ_ONLY_SAFE" if safe else "OVER_PRIVILEGED",
            ip_restricted=isinstance(ips, list) and bool(ips),
            expires_at=_optional_string(result.get("expiredAt")),
            deadline_days=deadline if isinstance(deadline, int) else None,
            account_type="unified" if result.get("uta") == 1 else "classic",
        )

    async def get_account_info(self) -> ExchangeAccountInfo:
        result = await self._get("/v5/account/info", None, "account_info")
        unified_status = result.get("unifiedMarginStatus")
        if not isinstance(unified_status, int):
            raise ExchangePrivateBadResponse("Bybit account status was malformed")
        return ExchangeAccountInfo(
            provider=self.provider,
            account_type=_account_type(unified_status),
            account_mode=f"unified_margin_{unified_status}",
            margin_mode=_required_string(result.get("marginMode"), "margin mode"),
            account_status="active",
            updated_at=_optional_timestamp_ms(result.get("updatedTime")),
        )

    async def get_balances(self) -> list[ExchangeBalance]:
        result = await self._get(
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED", "coin": ",".join(_ALLOWED_COINS)},
            "wallet_balance",
        )
        accounts = result.get("list")
        if not isinstance(accounts, list) or not accounts or not isinstance(accounts[0], dict):
            raise ExchangePrivateBadResponse("Bybit wallet response contained no account")
        coins = accounts[0].get("coin")
        if not isinstance(coins, list):
            raise ExchangePrivateBadResponse("Bybit wallet coin list was malformed")
        by_asset = {
            row.get("coin"): row
            for row in coins
            if isinstance(row, dict) and row.get("coin") in _ALLOWED_COINS
        }
        received_at = datetime.now(UTC)
        return [
            ExchangeBalance(
                provider=self.provider,
                asset=asset,  # type: ignore[arg-type]
                wallet_balance=_decimal(row.get("walletBalance", "0"), "wallet balance"),
                available_balance=_optional_decimal(row.get("availableToWithdraw")),
                equity=_optional_decimal(row.get("equity")),
                received_at=received_at,
            )
            for asset in _ALLOWED_COINS
            if (row := by_asset.get(asset)) is not None
        ]

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(
        self, path: str, params: Mapping[str, str] | None, endpoint_class: str
    ) -> dict[str, Any]:
        query = canonical_query(params)
        last_error: ExchangePrivateError | None = None
        for attempt in range(self._max_retries + 1):
            timestamp = self._clock_ms() + self._clock_offset_ms
            headers = {
                "X-BAPI-API-KEY": self._api_key,
                "X-BAPI-TIMESTAMP": str(timestamp),
                "X-BAPI-RECV-WINDOW": str(self._recv_window_ms),
                "X-BAPI-SIGN": sign_get(
                    timestamp_ms=timestamp,
                    api_key=self._api_key,
                    recv_window_ms=self._recv_window_ms,
                    query=query,
                    secret=self._api_secret,
                ),
            }
            started = time.monotonic()
            logger.info(
                "exchange.private.request",
                extra={"provider": self.provider, "endpoint_class": endpoint_class},
            )
            try:
                response = await self._client.get(
                    f"{self._base_url}{path}", params=params, headers=headers
                )
                latency = time.monotonic() - started
                self.last_latency_ms = latency * 1000
                self.rate_limit_remaining = _optional_int(
                    response.headers.get("X-Bapi-Limit-Status")
                )
                if response.status_code == 429 or response.status_code >= 500:
                    error = (
                        ExchangePrivateRateLimited("Bybit private API rate limited the request")
                        if response.status_code == 429
                        else ExchangePrivateUnavailable(
                            "Bybit private API is temporarily unavailable"
                        )
                    )
                    if isinstance(error, ExchangePrivateRateLimited):
                        record_exchange_private_rate_limit(self.provider)
                    if attempt < self._max_retries:
                        await asyncio.sleep(_retry_delay(response, attempt))
                        last_error = error
                        continue
                    raise error
                if response.status_code in (401, 403):
                    raise ExchangePrivateAuthenticationError(
                        "Bybit rejected private API authentication or IP access"
                    )
                payload = json.loads(response.text, parse_float=Decimal)
                if not isinstance(payload, dict):
                    raise ExchangePrivateBadResponse("Bybit returned a non-object response")
                code = payload.get("retCode")
                if code != 0:
                    error = _error_for_code(code)
                    if (
                        code == 10002
                        and not self._clock_synchronized
                        and attempt < self._max_retries
                    ):
                        await self._synchronize_clock()
                        last_error = error
                        continue
                    if code in _RETRYABLE_RET_CODES and attempt < self._max_retries:
                        if code == 10006:
                            record_exchange_private_rate_limit(self.provider)
                        await asyncio.sleep(_retry_delay(response, attempt))
                        last_error = error
                        continue
                    raise error
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise ExchangePrivateBadResponse("Bybit response result was malformed")
                self.last_success_at = datetime.now(UTC)
                record_exchange_private_request(self.provider, "success", latency)
                logger.info(
                    "exchange.private.success",
                    extra={
                        "provider": self.provider,
                        "endpoint_class": endpoint_class,
                        "latency_ms": round(self.last_latency_ms, 2),
                    },
                )
                return result
            except ExchangePrivateAuthenticationError:
                record_exchange_private_auth_failure(self.provider)
                record_exchange_private_request(
                    self.provider, "auth_failed", time.monotonic() - started
                )
                logger.warning(
                    "exchange.private.auth_failed",
                    extra={"provider": self.provider, "endpoint_class": endpoint_class},
                )
                raise
            except httpx.TimeoutException as exc:
                last_error = ExchangePrivateTimeout("Bybit private API request timed out")
                if attempt < self._max_retries:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                last_error = ExchangePrivateUnavailable(
                    "Bybit private API connection failed"
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise last_error from exc
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ExchangePrivateBadResponse("Bybit returned malformed JSON") from exc
            except ExchangePrivateError:
                record_exchange_private_request(
                    self.provider, "error", time.monotonic() - started
                )
                raise
        raise ExchangePrivateUnavailable("Bybit private API request failed") from last_error

    async def _synchronize_clock(self) -> None:
        """Apply a process-local offset from Bybit's public server-time endpoint."""
        try:
            response = await self._client.get(f"{self._base_url}/v5/market/time")
            payload = response.json()
            server_time = payload.get("time") if isinstance(payload, dict) else None
            if (
                response.status_code != 200
                or not isinstance(payload, dict)
                or payload.get("retCode") != 0
            ):
                raise ValueError
            self._clock_offset_ms = int(str(server_time)) - self._clock_ms()
            self._clock_synchronized = True
            logger.info(
                "exchange.private.clock_synchronized",
                extra={"provider": self.provider, "endpoint_class": "server_time"},
            )
        except (httpx.HTTPError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExchangePrivateTimestampError(
                "Bybit timestamp synchronization failed"
            ) from exc


def _error_for_code(code: object) -> ExchangePrivateError:
    if code in _AUTH_RET_CODES:
        return ExchangePrivateAuthenticationError(
            "Bybit private API credentials are invalid, expired, or incorrectly signed"
        )
    if code == 10002:
        return ExchangePrivateTimestampError("Bybit rejected the request timestamp window")
    if code == 10005:
        return ExchangePrivatePermissionError("Bybit API key permission denied")
    if code == 10006:
        return ExchangePrivateRateLimited("Bybit private API rate limit exceeded")
    if code in (10009, 10010, 10024):
        return ExchangePrivateAuthenticationError(
            "Bybit private API access is restricted by region, IP, or compliance policy"
        )
    if code in _RETRYABLE_RET_CODES:
        return ExchangePrivateUnavailable("Bybit private API is temporarily unavailable")
    return ExchangePrivateBadResponse("Bybit private API rejected the read-only request")


def _mask_key(value: str) -> str:
    return f"****{value[-4:]}" if value else ""


def _account_type(status: int) -> str:
    return {1: "classic", 3: "uta1", 4: "uta1_pro", 5: "uta2", 6: "uta2_pro"}.get(
        status, "unknown"
    )


def _decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExchangePrivateBadResponse(f"Bybit {field} was not decimal") from exc
    if not parsed.is_finite():
        raise ExchangePrivateBadResponse(f"Bybit {field} was not finite")
    return parsed


def _optional_decimal(value: object) -> Decimal | None:
    return None if value in (None, "") else _decimal(value, "balance")


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExchangePrivateBadResponse(f"Bybit {field} was malformed")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value and not value.startswith("1970-") else None


def _optional_timestamp_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int) -> float:
    return min(0.25 * (2**attempt) + random.uniform(0, 0.1), 2.0)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(float(retry_after), 0), 5)
        except ValueError:
            pass
    return _backoff(attempt)
