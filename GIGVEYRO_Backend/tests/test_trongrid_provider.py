import json
from collections.abc import Callable
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.enums.deposit import DepositNetwork
from app.services.trongrid_provider import (
    DepositProviderAuthenticationError,
    DepositProviderInvalidResponse,
    DepositProviderRateLimited,
    DepositProviderUnavailable,
    TronGridTRC20DepositProvider,
)

USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
DEPOSIT = "TMwFHYXLJaRUPeW6421aqXL4ZEzPRFGkGT"
SENDER = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
TX_A = "a" * 64
TX_B = "b" * 64


def history_row(tx_id: str, value: str) -> dict:
    return {
        "transaction_id": tx_id,
        "block_timestamp": 1_700_000_000_000,
        "from": SENDER,
        "to": DEPOSIT,
        "type": "Transfer",
        "value": value,
        "token_info": {"address": USDT, "decimals": 6, "symbol": "USDT"},
    }


def event_row(tx_id: str, value: str, event_index: int, block_number: int) -> dict:
    return {
        "transaction_id": tx_id,
        "event_name": "Transfer",
        "event_index": event_index,
        "block_number": block_number,
        "contract_address": USDT,
        "result": {"from": SENDER, "to": DEPOSIT, "value": value},
    }


def response(payload: object, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, text=json.dumps(payload), headers=headers)


def provider(handler: Callable[[httpx.Request], httpx.Response], **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    max_retries = kwargs.pop("max_retries", 0)
    instance = TronGridTRC20DepositProvider(
        api_url="https://api.trongrid.io",
        api_key="test-key",
        client=client,
        max_retries=max_retries,
        token_contract=USDT,
        deposit_address=DEPOSIT,
        **kwargs,
    )
    return instance, client


def base_handler(history: list[dict], events: dict[str, list[dict]]):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["TRON-PRO-API-KEY"] == "test-key"
        if request.url.path == "/wallet/getnowblock":
            return response({"block_header": {"raw_data": {"number": 1_005}}})
        if request.url.path.endswith("/transactions/trc20"):
            assert request.url.params["only_confirmed"] == "true"
            assert request.url.params["only_to"] == "true"
            assert request.url.params["contract_address"] == USDT
            assert request.url.params["min_timestamp"] == "123"
            return response({"success": True, "data": history, "meta": {}})
        tx_id = request.url.path.split("/")[-2]
        return response({"success": True, "data": events[tx_id], "meta": {}})

    return handle


@pytest.mark.asyncio
async def test_parses_usdt_event_and_numeric_confirmations():
    handler = base_handler(
        [history_row(TX_A, "12345678")],
        {TX_A: [event_row(TX_A, "12345678", 7, 1_000)]},
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()

    assert len(transfers) == 1
    transfer = transfers[0]
    assert transfer.amount == Decimal("12.345678")
    assert transfer.network == DepositNetwork.TRC20
    assert transfer.confirmations == 6
    assert transfer.is_finalized is True
    assert transfer.provider_event_id == f"trongrid:{TX_A}:7"
    assert scanner.last_scan_upper_timestamp_ms is not None


@pytest.mark.asyncio
async def test_paginates_by_fingerprint_and_keeps_multiple_events_in_one_tx():
    calls: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wallet/getnowblock":
            return response({"block_header": {"raw_data": {"number": 200}}})
        if request.url.path.endswith("/transactions/trc20"):
            fingerprint = request.url.params.get("fingerprint")
            calls.append(fingerprint)
            if fingerprint is None:
                return response(
                    {
                        "success": True,
                        "data": [history_row(TX_A, "1000000")],
                        "meta": {"fingerprint": "next-page"},
                    }
                )
            return response(
                {"success": True, "data": [history_row(TX_A, "1000000")], "meta": {}}
            )
        return response(
            {
                "success": True,
                "data": [
                    event_row(TX_A, "1000000", 3, 190),
                    event_row(TX_A, "1000000", 4, 190),
                ],
                "meta": {},
            }
        )

    scanner, client = provider(handle)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()

    assert calls == [None, "next-page"]
    assert [item.provider_event_id for item in transfers] == [
        f"trongrid:{TX_A}:3",
        f"trongrid:{TX_A}:4",
    ]


@pytest.mark.asyncio
async def test_rejects_repeated_pagination_fingerprint():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wallet/getnowblock":
            return response({"block_header": {"raw_data": {"number": 1}}})
        return response(
            {"success": True, "data": [], "meta": {"fingerprint": "same-cursor"}}
        )

    scanner, client = provider(handle, max_pages=3)
    try:
        with pytest.raises(DepositProviderInvalidResponse, match="repeated"):
            await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()
    assert scanner.last_scan_upper_timestamp_ms is None


@pytest.mark.asyncio
async def test_incomplete_transaction_event_pagination_fails_entire_scan():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wallet/getnowblock":
            return response({"block_header": {"raw_data": {"number": 1}}})
        if request.url.path.endswith("/transactions/trc20"):
            return response(
                {"success": True, "data": [history_row(TX_A, "1000000")], "meta": {}}
            )
        return response(
            {"success": True, "data": [], "meta": {"fingerprint": "same-event-cursor"}}
        )

    scanner, client = provider(handle, max_pages=3)
    try:
        with pytest.raises(DepositProviderInvalidResponse, match="event pagination"):
            await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()
    assert scanner.last_scan_upper_timestamp_ms is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception"),
    [(403, DepositProviderAuthenticationError), (500, DepositProviderUnavailable)],
)
async def test_maps_upstream_http_errors(status: int, exception: type[Exception]):
    scanner, client = provider(lambda _request: response({}, status=status))
    try:
        with pytest.raises(exception):
            await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_honors_bounded_retry():
    attempts = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, status=429, headers={"Retry-After": "0"})

    scanner, client = provider(handle, max_retries=1)
    try:
        with (
            patch("app.services.trongrid_provider.asyncio.sleep", new=AsyncMock()) as sleep,
            pytest.raises(DepositProviderRateLimited),
        ):
            await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()
    assert attempts == 2
    sleep.assert_awaited_once_with(0.0)


@pytest.mark.asyncio
async def test_malformed_envelope_fails_closed():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wallet/getnowblock":
            return response({"block_header": {"raw_data": {"number": 1}}})
        return response({"success": True, "data": "not-a-list", "meta": {}})

    scanner, client = provider(handle)
    try:
        with pytest.raises(DepositProviderInvalidResponse, match="envelope"):
            await scanner.fetch_recent_transactions(DEPOSIT)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_filters_wrong_contract_recipient_and_non_positive_amount():
    wrong_contract = history_row(TX_A, "1000000")
    wrong_contract["token_info"] = {"address": DEPOSIT, "decimals": 6}
    wrong_recipient = history_row(TX_B, "1000000")
    wrong_recipient["to"] = SENDER
    invalid_amount = history_row("c" * 64, "0")
    handler = base_handler([wrong_contract, wrong_recipient, invalid_amount], {})
    scanner, client = provider(handler)
    try:
        assert await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123) == []
    finally:
        await client.aclose()
