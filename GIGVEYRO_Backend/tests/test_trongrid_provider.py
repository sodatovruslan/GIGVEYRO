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
    normalize_tron_address,
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


# ---------------------------------------------------------------------------
# Address normalization: TronGrid's history endpoint returns Base58Check
# ("T...") from/to addresses, but its transaction-events endpoint's
# ABI-decoded result.from/result.to fields return raw EVM-style hex
# ("0x..." or "41..." for the TRON-prefixed form) - the SAME address in two
# different textual representations. Comparing them as raw strings (the
# original bug) means a real, legitimate transfer never matches its own
# event log entry. These hex forms were computed from the exact same
# checksummed bytes as the DEPOSIT/SENDER/USDT Base58 constants above -
# not invented - so every "match" assertion below is a real equivalence.
# ---------------------------------------------------------------------------

DEPOSIT_HEX20 = "834295921a488d9d42b4b3021ed1a3c39fb0f03e"
SENDER_HEX20 = "0000000000000000000000000000000000000000"
USDT_HEX20 = "a614f803b6fd780986a42c78ec9c7f77e6ded13c"


# Case A: Base58 -> Base58 (round-trip / already-canonical)
def test_normalize_base58_to_base58_is_identity():
    assert normalize_tron_address(DEPOSIT) == DEPOSIT
    assert normalize_tron_address(SENDER) == SENDER


# Case B: Base58 vs "0x" + 40-hex raw form - the exact real TronGrid
# history-vs-events discrepancy this bug fix addresses.
def test_normalize_base58_matches_0x_hex_form():
    assert normalize_tron_address(DEPOSIT) == normalize_tron_address("0x" + DEPOSIT_HEX20)
    assert normalize_tron_address(SENDER) == normalize_tron_address("0x" + SENDER_HEX20)


# Case C / D: raw hex forms (with and without the "0x"/"41" TRON prefix)
# normalize to the same canonical value as each other and as Base58,
# regardless of which side is "history" vs "events" in a given response.
def test_normalize_hex_forms_agree_with_each_other_and_base58():
    canonical = normalize_tron_address(DEPOSIT)
    assert normalize_tron_address(DEPOSIT_HEX20) == canonical  # bare 40-hex
    assert normalize_tron_address("0x" + DEPOSIT_HEX20) == canonical  # 0x + 40-hex
    assert normalize_tron_address("41" + DEPOSIT_HEX20) == canonical  # 41 + 40-hex


# Case E: different addresses in different formats must never normalize
# to the same value.
def test_normalize_different_addresses_never_match():
    assert normalize_tron_address(DEPOSIT) != normalize_tron_address("0x" + SENDER_HEX20)
    assert normalize_tron_address(USDT) != normalize_tron_address(DEPOSIT_HEX20)


# Case F: invalid Base58Check (bad checksum / bad length) is rejected, not
# silently accepted or equated with anything.
@pytest.mark.parametrize(
    "bad",
    [
        "T" * 34,  # right length, wrong checksum
        DEPOSIT[:-1] + ("A" if DEPOSIT[-1] != "A" else "B"),  # corrupted checksum
        "TooShort",
        "",
    ],
)
def test_normalize_rejects_invalid_base58(bad):
    with pytest.raises(ValueError):
        normalize_tron_address(bad)


# Case G: invalid raw hex (wrong length, non-hex characters) is rejected.
@pytest.mark.parametrize(
    "bad",
    [
        "0x" + "g" * 40,  # not hex
        "0x" + "a" * 39,  # too short
        "41" + "a" * 39,  # too short with 41 prefix
        "a" * 41,  # ambiguous length, neither 40 nor 42
    ],
)
def test_normalize_rejects_invalid_hex(bad):
    with pytest.raises(ValueError):
        normalize_tron_address(bad)


def hex_event_row(
    tx_id: str, value: str, event_index: int, block_number: int, *, from_hex: str, to_hex: str
) -> dict:
    """Same shape as event_row(), but with result.from/result.to in the
    raw hex form TronGrid's real events endpoint actually returns."""
    return {
        "transaction_id": tx_id,
        "event_name": "Transfer",
        "event_index": event_index,
        "block_number": block_number,
        "contract_address": USDT,
        "result": {"from": from_hex, "to": to_hex, "value": value},
    }


@pytest.mark.asyncio
async def test_production_shaped_regression_history_base58_events_hex_matches():
    """The exact real-world shape captured during the production read-only
    smoke test: history endpoint gives Base58 from/to, events endpoint
    gives raw "0x" hex from/to for the SAME real transfer. Fails on the
    pre-fix code (raw string comparison never matches); must pass now."""
    handler = base_handler(
        [history_row(TX_A, "12345678")],
        {
            TX_A: [
                hex_event_row(
                    TX_A,
                    "12345678",
                    7,
                    1_000,
                    from_hex="0x" + SENDER_HEX20,
                    to_hex="0x" + DEPOSIT_HEX20,
                )
            ]
        },
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()

    assert len(transfers) == 1
    assert transfers[0].amount == Decimal("12.345678")
    assert transfers[0].to_address == DEPOSIT
    assert transfers[0].from_address == SENDER


@pytest.mark.asyncio
async def test_production_shaped_regression_41_prefixed_hex_also_matches():
    """Same real-world discrepancy, but with the events endpoint returning
    the TRON-style 41-prefixed 42-hex-char form instead of "0x" + 40."""
    handler = base_handler(
        [history_row(TX_A, "12345678")],
        {
            TX_A: [
                hex_event_row(
                    TX_A,
                    "12345678",
                    7,
                    1_000,
                    from_hex="41" + SENDER_HEX20,
                    to_hex="41" + DEPOSIT_HEX20,
                )
            ]
        },
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()
    assert len(transfers) == 1


# Case H: same transaction, but the event log's actual recipient is a
# DIFFERENT address than the history row claims - must be rejected, not
# matched just because the transaction id/value coincide.
@pytest.mark.asyncio
async def test_event_with_different_recipient_is_rejected_not_matched():
    handler = base_handler(
        [history_row(TX_A, "12345678")],
        {
            TX_A: [
                hex_event_row(
                    TX_A,
                    "12345678",
                    7,
                    1_000,
                    from_hex="0x" + SENDER_HEX20,
                    to_hex="0x" + USDT_HEX20,  # wrong recipient - not DEPOSIT
                )
            ]
        },
    )
    scanner, client = provider(handler)
    try:
        # fetch_recent_transactions isolates a single row's rejected
        # identity (see test_one_malformed_event_identity_does_not_abort_the_whole_scan)
        # rather than raising - the mismatched row is simply not matched.
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()
    assert transfers == []


# Case I: matching recipient (even across formats) but the event is on a
# different contract entirely - must still be rejected.
@pytest.mark.asyncio
async def test_event_with_different_contract_is_rejected():
    handler = base_handler(
        [history_row(TX_A, "12345678")],
        {
            TX_A: [
                {
                    "transaction_id": TX_A,
                    "event_name": "Transfer",
                    "event_index": 7,
                    "block_number": 1_000,
                    "contract_address": DEPOSIT,  # not the configured USDT contract
                    "result": {
                        "from": "0x" + SENDER_HEX20,
                        "to": "0x" + DEPOSIT_HEX20,
                        "value": "12345678",
                    },
                }
            ]
        },
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()
    assert transfers == []


# Case J: two Transfer events in one tx, mixed address formats - the
# event_index-based offset disambiguation (already-existing logic) must
# still correctly pick the right one in order after normalization, not
# just match the first arbitrary hex-equal row.
@pytest.mark.asyncio
async def test_multiple_events_same_tx_disambiguated_by_offset_after_normalization():
    handler = base_handler(
        [history_row(TX_A, "1000000"), history_row(TX_A, "1000000")],
        {
            TX_A: [
                hex_event_row(
                    TX_A, "1000000", 3, 190, from_hex="0x" + SENDER_HEX20, to_hex="0x" + DEPOSIT_HEX20
                ),
                event_row(TX_A, "1000000", 4, 190),  # second one in plain Base58 form
            ]
        },
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()
    assert [item.provider_event_id for item in transfers] == [
        f"trongrid:{TX_A}:3",
        f"trongrid:{TX_A}:4",
    ]


@pytest.mark.asyncio
async def test_one_malformed_event_identity_does_not_abort_the_whole_scan():
    """Scanner error isolation: a row whose event identity can't be
    resolved (e.g. genuinely missing from the event log, or an
    unrecognized address format) is skipped with a warning - it must not
    take down the rest of the scan cycle, and other valid rows in the
    same batch must still be processed and credited."""
    unmatched_row = history_row(TX_A, "1000000")
    good_row = history_row(TX_B, "2000000")
    handler = base_handler(
        [unmatched_row, good_row],
        {
            TX_A: [],  # no event log entry at all for this tx - identity missing
            TX_B: [event_row(TX_B, "2000000", 1, 500)],
        },
    )
    scanner, client = provider(handler)
    try:
        transfers = await scanner.fetch_recent_transactions(DEPOSIT, min_timestamp_ms=123)
    finally:
        await client.aclose()

    assert len(transfers) == 1
    assert transfers[0].provider_event_id == f"trongrid:{TX_B}:1"
