from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.enums.deposit import DepositNetwork
from app.infra.metrics import (
    observe_deposit_scanner_latency,
    record_deposit_scanner_event,
    record_deposit_scanner_rate_limit,
    record_deposit_scanner_request,
)
from app.services.deposit_provider import CryptoDepositProvider, OnChainTransactionDTO

logger = logging.getLogger(__name__)
_PROVIDER = "trongrid"
_TX_ID = re.compile(r"^[0-9a-fA-F]{64}$")
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: index for index, char in enumerate(_BASE58)}


class DepositProviderError(Exception):
    category = "provider_error"


class DepositProviderTimeout(DepositProviderError):
    category = "timeout"


class DepositProviderRateLimited(DepositProviderError):
    category = "rate_limited"


class DepositProviderUnavailable(DepositProviderError):
    category = "upstream_unavailable"


class DepositProviderAuthenticationError(DepositProviderError):
    category = "authentication"


class DepositProviderInvalidResponse(DepositProviderError):
    category = "invalid_response"


class DepositProviderRejectedEvent(DepositProviderInvalidResponse):
    category = "invalid_event"


class DepositProviderConfigurationError(DepositProviderError):
    category = "configuration"


class TronGridTRC20DepositProvider(CryptoDepositProvider):
    provider = _PROVIDER

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        token_contract: str | None = None,
        token_decimals: int | None = None,
        deposit_address: str | None = None,
    ) -> None:
        self._api_url = (api_url or settings.TRONGRID_API_URL).rstrip("/")
        configured_key = settings.TRONGRID_API_KEY.get_secret_value()
        self._api_key = configured_key if api_key is None else api_key
        self._max_retries = settings.TRONGRID_MAX_RETRIES if max_retries is None else max_retries
        self._page_size = settings.TRONGRID_PAGE_SIZE if page_size is None else page_size
        self._max_pages = settings.TRONGRID_MAX_PAGES if max_pages is None else max_pages
        self._token_contract = token_contract or settings.USDT_TRC20_CONTRACT_ADDRESS
        self._token_decimals = (
            settings.USDT_TRC20_DECIMALS if token_decimals is None else token_decimals
        )
        self._deposit_address = deposit_address or settings.USDT_TRC20_DEPOSIT_ADDRESS
        timeout = timeout_seconds or settings.TRON_SCANNER_TIMEOUT_SECONDS
        headers = {"User-Agent": "GIGVEYRO-TronGridReadOnly/1.0"}
        if self._api_key:
            headers["TRON-PRO-API-KEY"] = self._api_key
        self._headers = headers
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 3.0)),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers=headers,
        )
        self._owns_client = client is None
        self._event_cache: dict[str, list[object]] = {}
        self._event_match_offsets: dict[tuple[str, str, str, str], int] = {}
        self.last_scan_upper_timestamp_ms: int | None = None
        if not 1 <= self._page_size <= 200:
            raise DepositProviderConfigurationError("TronGrid page size must be 1..200")
        if self._max_pages < 1:
            raise DepositProviderConfigurationError("TronGrid max pages must be positive")
        if not 0 <= self._token_decimals <= 18:
            raise DepositProviderConfigurationError("USDT token decimals are invalid")

    def __repr__(self) -> str:
        return (
            "TronGridTRC20DepositProvider(provider='trongrid', mode='READ_ONLY', "
            f"configured={bool(self._api_key)})"
        )

    def get_deposit_address(self) -> str:
        require_tron_address(self._deposit_address, "deposit address")
        return self._deposit_address

    async def fetch_recent_transactions(
        self, address: str, *, min_timestamp_ms: int | None = None
    ) -> list[OnChainTransactionDTO]:
        require_tron_address(address, "deposit address")
        require_tron_address(self._token_contract, "USDT contract address")
        upper_ms = time.time_ns() // 1_000_000
        lower_ms = max(0, min_timestamp_ms or 0)
        if lower_ms > upper_ms:
            raise DepositProviderConfigurationError("scan lower timestamp is in the future")

        started = time.monotonic()
        logger.info(
            "trongrid.scan.started",
            extra={"provider": self.provider, "min_timestamp_ms": lower_ms},
        )
        results: list[OnChainTransactionDTO] = []
        self._event_cache.clear()
        self._event_match_offsets.clear()
        seen_events: set[str] = set()
        seen_fingerprints: set[str] = set()
        fingerprint: str | None = None
        pages = 0
        try:
            head_number = await self._latest_head_number()
            for page_number in range(1, self._max_pages + 1):
                pages = page_number
                params = {
                    "only_confirmed": "true",
                    "only_to": "true",
                    "limit": str(self._page_size),
                    "contract_address": self._token_contract,
                    "order_by": "block_timestamp,asc",
                    "min_timestamp": str(lower_ms),
                    "max_timestamp": str(upper_ms),
                }
                if fingerprint:
                    params["fingerprint"] = fingerprint
                payload = await self._get_json(
                    f"/v1/accounts/{quote(address, safe='')}/transactions/trc20",
                    params=params,
                    operation="history",
                )
                rows, next_fingerprint = history_page(payload)
                accepted = 0
                for row in rows:
                    try:
                        candidate = await self._normalize_history_row(
                            row, address=address, head_number=head_number
                        )
                    except DepositProviderRejectedEvent as exc:
                        record_deposit_scanner_event(self.provider, "malformed")
                        logger.warning(
                            "trongrid.scan.event_rejected",
                            extra={"provider": self.provider, "error_category": exc.category},
                        )
                        continue
                    if candidate.provider_event_id in seen_events:
                        record_deposit_scanner_event(self.provider, "duplicate")
                        continue
                    seen_events.add(candidate.provider_event_id)
                    results.append(candidate)
                    accepted += 1
                    record_deposit_scanner_event(self.provider, "accepted")
                logger.info(
                    "trongrid.scan.page",
                    extra={
                        "provider": self.provider,
                        "page": page_number,
                        "rows": len(rows),
                        "accepted": accepted,
                    },
                )
                if not next_fingerprint:
                    break
                if next_fingerprint in seen_fingerprints:
                    raise DepositProviderInvalidResponse(
                        "TronGrid returned a repeated pagination fingerprint"
                    )
                seen_fingerprints.add(next_fingerprint)
                fingerprint = next_fingerprint
            else:
                if fingerprint:
                    raise DepositProviderInvalidResponse(
                        "TronGrid scan exceeded the configured maximum page count"
                    )
            self.last_scan_upper_timestamp_ms = upper_ms
            mark_trongrid_success(len(results))
            logger.info(
                "trongrid.scan.completed",
                extra={
                    "provider": self.provider,
                    "pages": pages,
                    "events": len(results),
                    "latency_ms": round((time.monotonic() - started) * 1000),
                },
            )
            return results
        except DepositProviderError as exc:
            mark_trongrid_failure(exc.category)
            logger.warning(
                "trongrid.scan.failed",
                extra={"provider": self.provider, "error_category": exc.category},
            )
            raise
        finally:
            observe_deposit_scanner_latency(self.provider, time.monotonic() - started)

    async def _latest_head_number(self) -> int:
        payload = await self._get_json(
            "/wallet/getnowblock", params=None, operation="latest_block"
        )
        try:
            number = payload["block_header"]["raw_data"]["number"]
        except (KeyError, TypeError) as exc:
            raise DepositProviderInvalidResponse(
                "TronGrid latest block response was malformed"
            ) from exc
        if not isinstance(number, int) or number < 0:
            raise DepositProviderInvalidResponse("TronGrid latest block number was invalid")
        return number

    async def _normalize_history_row(
        self, row: object, *, address: str, head_number: int
    ) -> OnChainTransactionDTO:
        if not isinstance(row, dict):
            raise DepositProviderRejectedEvent("TronGrid history row was not an object")
        tx_hash = required_string(row.get("transaction_id"), "transaction id")
        if not _TX_ID.fullmatch(tx_hash):
            raise DepositProviderRejectedEvent("TronGrid transaction id was malformed")
        from_address = required_string(row.get("from"), "sender address")
        to_address = required_string(row.get("to"), "recipient address")
        require_tron_address(from_address, "sender address", response_error=True)
        require_tron_address(to_address, "recipient address", response_error=True)
        if to_address != address:
            raise DepositProviderRejectedEvent("TronGrid returned a different recipient")
        if row.get("type") != "Transfer":
            raise DepositProviderRejectedEvent("TronGrid row was not a Transfer event")

        token = row.get("token_info")
        if not isinstance(token, dict):
            raise DepositProviderRejectedEvent("TronGrid token info was malformed")
        contract = required_string(token.get("address"), "token contract")
        if contract != self._token_contract:
            raise DepositProviderRejectedEvent("TronGrid returned a different token contract")
        decimals = token.get("decimals")
        if isinstance(decimals, str) and decimals.isdigit():
            decimals = int(decimals)
        if decimals != self._token_decimals:
            raise DepositProviderRejectedEvent("TronGrid returned unexpected token decimals")
        raw_value = required_string(row.get("value"), "token value")
        if not raw_value.isdigit():
            raise DepositProviderRejectedEvent("TronGrid token value was not an integer")
        try:
            amount = Decimal(raw_value).scaleb(-self._token_decimals)
        except InvalidOperation as exc:
            raise DepositProviderRejectedEvent("TronGrid token value was invalid") from exc
        if not amount.is_finite() or amount <= 0:
            raise DepositProviderRejectedEvent("TronGrid token value was not positive")

        timestamp_ms = row.get("block_timestamp")
        if not isinstance(timestamp_ms, int) or timestamp_ms <= 0:
            raise DepositProviderRejectedEvent("TronGrid block timestamp was invalid")
        event_index, block_number = await self._event_identity(
            tx_hash=tx_hash,
            from_address=from_address,
            to_address=to_address,
            raw_value=raw_value,
        )
        return OnChainTransactionDTO(
            tx_hash=tx_hash.lower(),
            network=DepositNetwork.TRC20,
            asset_contract=contract,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            confirmations=max(0, head_number - block_number + 1),
            is_success=True,
            timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
            provider=self.provider,
            event_index=event_index,
            block_number=block_number,
            is_finalized=True,
        )

    async def _event_identity(
        self, *, tx_hash: str, from_address: str, to_address: str, raw_value: str
    ) -> tuple[int, int]:
        rows = await self._transaction_events(tx_hash)
        matches: list[tuple[int, int]] = []
        for event in rows:
            if not isinstance(event, dict):
                continue
            result = event.get("result")
            if (
                event.get("transaction_id") != tx_hash
                or event.get("event_name") != "Transfer"
                or event.get("contract_address") != self._token_contract
                or not isinstance(result, dict)
                or result.get("from") != from_address
                or result.get("to") != to_address
                or str(result.get("value")) != raw_value
            ):
                continue
            event_index = event.get("event_index")
            block_number = event.get("block_number")
            if (
                isinstance(event_index, int)
                and event_index >= 0
                and isinstance(block_number, int)
                and block_number >= 0
            ):
                matches.append((event_index, block_number))
        if not matches:
            raise DepositProviderInvalidResponse(
                "TronGrid event identity was missing"
            )
        matches.sort()
        signature = (tx_hash, from_address, to_address, raw_value)
        offset = self._event_match_offsets.get(signature, 0)
        if offset >= len(matches):
            raise DepositProviderInvalidResponse(
                "TronGrid history contained more events than the transaction event log"
            )
        self._event_match_offsets[signature] = offset + 1
        return matches[offset]

    async def _transaction_events(self, tx_hash: str) -> list[object]:
        cached = self._event_cache.get(tx_hash)
        if cached is not None:
            return cached

        rows: list[object] = []
        fingerprint: str | None = None
        seen_fingerprints: set[str] = set()
        for _page in range(self._max_pages):
            params = {"only_confirmed": "true", "limit": "200"}
            if fingerprint:
                params["fingerprint"] = fingerprint
            payload = await self._get_json(
                f"/v1/transactions/{quote(tx_hash, safe='')}/events",
                params=params,
                operation="transaction_events",
            )
            page_rows, next_fingerprint = history_page(payload)
            rows.extend(page_rows)
            if not next_fingerprint:
                self._event_cache[tx_hash] = rows
                return rows
            if next_fingerprint in seen_fingerprints:
                raise DepositProviderInvalidResponse(
                    "TronGrid returned a repeated event pagination fingerprint"
                )
            seen_fingerprints.add(next_fingerprint)
            fingerprint = next_fingerprint
        raise DepositProviderInvalidResponse(
            "TronGrid transaction event scan exceeded the maximum page count"
        )

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None,
        operation: str,
    ) -> dict[str, Any]:
        url = f"{self._api_url}{path}"
        last_error: DepositProviderError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, params=params, headers=self._headers)
                if response.status_code == 429:
                    record_deposit_scanner_request(self.provider, "rate_limited")
                    record_deposit_scanner_rate_limit(self.provider)
                    logger.warning(
                        "trongrid.scan.rate_limited",
                        extra={"provider": self.provider, "operation": operation},
                    )
                    last_error = DepositProviderRateLimited("TronGrid rate limited the request")
                    if attempt < self._max_retries:
                        await asyncio.sleep(retry_delay(response, attempt + 1))
                        continue
                    raise last_error
                if response.status_code >= 500:
                    record_deposit_scanner_request(self.provider, "upstream_error")
                    last_error = DepositProviderUnavailable(
                        f"TronGrid returned HTTP {response.status_code}"
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(backoff(attempt + 1))
                        continue
                    raise last_error
                if response.status_code in {401, 403}:
                    record_deposit_scanner_request(self.provider, "authentication_error")
                    raise DepositProviderAuthenticationError(
                        "TronGrid rejected the API credential or request policy"
                    )
                if response.status_code >= 400:
                    record_deposit_scanner_request(self.provider, "rejected")
                    raise DepositProviderInvalidResponse(
                        f"TronGrid rejected a read request with HTTP {response.status_code}"
                    )
                try:
                    payload = json.loads(response.text, parse_float=Decimal)
                except ValueError as exc:
                    record_deposit_scanner_request(self.provider, "invalid_json")
                    raise DepositProviderInvalidResponse("TronGrid returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    record_deposit_scanner_request(self.provider, "invalid_response")
                    raise DepositProviderInvalidResponse(
                        "TronGrid returned a non-object response"
                    )
                record_deposit_scanner_request(self.provider, "success")
                return payload
            except httpx.TimeoutException as exc:
                record_deposit_scanner_request(self.provider, "timeout")
                last_error = DepositProviderTimeout("TronGrid request timed out")
                if attempt < self._max_retries:
                    await asyncio.sleep(backoff(attempt + 1))
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                record_deposit_scanner_request(self.provider, "network_error")
                last_error = DepositProviderUnavailable("TronGrid connection failed")
                if attempt < self._max_retries:
                    await asyncio.sleep(backoff(attempt + 1))
                    continue
                raise last_error from exc
        raise last_error or DepositProviderUnavailable("TronGrid request failed")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def history_page(payload: dict[str, Any]) -> tuple[list[object], str | None]:
    if payload.get("success") is not True:
        raise DepositProviderInvalidResponse("TronGrid response reported failure")
    rows = payload.get("data")
    meta = payload.get("meta")
    if not isinstance(rows, list) or not isinstance(meta, dict):
        raise DepositProviderInvalidResponse("TronGrid page envelope was malformed")
    fingerprint = meta.get("fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise DepositProviderInvalidResponse("TronGrid pagination fingerprint was malformed")
    return rows, fingerprint or None


def required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepositProviderRejectedEvent(f"TronGrid {field} was missing")
    return value


def require_tron_address(address: str, field: str, *, response_error: bool = False) -> None:
    error_type = (
        DepositProviderRejectedEvent
        if response_error
        else DepositProviderConfigurationError
    )
    if len(address) != 34 or not address.startswith("T"):
        raise error_type(f"TRON {field} is not a valid Base58Check address")
    try:
        value = 0
        for char in address:
            value = value * 58 + _BASE58_INDEX[char]
        decoded = value.to_bytes(25, "big")
    except (KeyError, OverflowError, ValueError) as exc:
        raise error_type(f"TRON {field} is not a valid Base58Check address") from exc
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if len(payload) != 21 or payload[0] != 0x41 or checksum != expected:
        raise error_type(f"TRON {field} is not a valid Base58Check address")


def backoff(attempt: int) -> float:
    return min(0.25 * (2 ** (attempt - 1)) + random.uniform(0, 0.1), 3.0)


def retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(max(float(value), 0.0), 30.0)
        except ValueError:
            pass
    return backoff(attempt)


_diagnostics: dict[str, object] = {
    "last_success_at": None,
    "last_scan_at": None,
    "last_error_category": None,
    "last_event_count": 0,
}


def mark_trongrid_success(event_count: int) -> None:
    now = datetime.now(UTC).isoformat()
    _diagnostics.update(
        last_success_at=now,
        last_scan_at=now,
        last_error_category=None,
        last_event_count=event_count,
    )


def mark_trongrid_failure(category: str) -> None:
    _diagnostics.update(
        last_scan_at=datetime.now(UTC).isoformat(), last_error_category=category
    )


def trongrid_diagnostics() -> dict[str, object]:
    return {
        "provider": _PROVIDER,
        "configured": bool(settings.TRONGRID_API_KEY.get_secret_value()),
        "mode": "READ_ONLY",
        **_diagnostics,
    }
