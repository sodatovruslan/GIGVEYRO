import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.services.exchange_private import runtime
from app.services.exchange_private.bybit import (
    BybitPrivateClient,
    canonical_query,
    sign_get,
)
from app.services.exchange_private.errors import (
    ExchangePrivateAuthenticationError,
    ExchangePrivateBadResponse,
    ExchangePrivatePermissionError,
    ExchangePrivateRateLimited,
    ExchangePrivateTimestampError,
)
from app.services.exchange_private.models import ExchangeApiKeyInfo

KEY = "dummy-key-1234"
SECRET = "dummy-secret-5678"
TIMESTAMP = 1_700_000_000_123


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"}


def _response(result=None, *, code=0, status=200, headers=None):
    return httpx.Response(
        status,
        json={"retCode": code, "retMsg": "safe", "result": result or {}},
        headers=headers,
    )


def _client(handler, *, retries=0):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BybitPrivateClient(
        base_url="https://api.bybit.test",
        api_key=KEY,
        api_secret=SECRET,
        recv_window_ms=5000,
        timeout_seconds=1,
        max_retries=retries,
        client=http,
        clock_ms=lambda: TIMESTAMP,
    )


def test_bybit_get_signature_and_canonical_query_are_deterministic():
    query = canonical_query({"coin": "USDT,USDC", "accountType": "UNIFIED"})
    assert query == "accountType=UNIFIED&coin=USDT%2CUSDC"
    assert canonical_query(None) == ""
    assert sign_get(
        timestamp_ms=TIMESTAMP,
        api_key=KEY,
        recv_window_ms=5000,
        query=query,
        secret=SECRET,
    ) == "f4e3dc648bf914534e84888c78341767ae9407f27481702b4c0976d4593a5e70"


async def test_signed_get_uses_official_headers_and_never_sends_body():
    captured = {}

    def handler(request):
        captured.update(
            headers=dict(request.headers), query=request.url.query, content=request.content
        )
        return _response(
            {
                "readOnly": 1,
                "permissions": {"Wallet": []},
                "ips": ["192.0.2.1"],
                "deadlineDay": -1,
                "expiredAt": "1970-01-01T00:00:00Z",
                "uta": 1,
            },
            headers={"X-Bapi-Limit-Status": "9"},
        )

    client = _client(handler)
    info = await client.get_api_key_info()
    assert info.permission_safety == "READ_ONLY_SAFE"
    assert info.masked_key == "****1234"
    assert info.ip_restricted is True
    assert info.expires_at is None
    assert captured["content"] == b""
    assert captured["headers"]["x-bapi-timestamp"] == str(TIMESTAMP)
    assert captured["headers"]["x-bapi-recv-window"] == "5000"
    assert captured["headers"]["x-bapi-api-key"] == KEY
    assert len(captured["headers"]["x-bapi-sign"]) == 64
    assert client.rate_limit_remaining == 9


@pytest.mark.parametrize(
    ("read_only", "wallet_permissions"),
    [(0, []), (1, ["Withdraw"])],
)
async def test_api_key_write_or_withdraw_capability_is_over_privileged(
    read_only, wallet_permissions
):
    client = _client(
        lambda request: _response(
            {
                "readOnly": read_only,
                "permissions": {"Wallet": wallet_permissions},
                "ips": [],
                "uta": 1,
            }
        )
    )
    assert (await client.get_api_key_info()).permission_safety == "OVER_PRIVILEGED"


async def test_account_and_whitelisted_balances_are_normalized_as_decimal():
    def handler(request):
        if request.url.path.endswith("/account/info"):
            return _response(
                {
                    "unifiedMarginStatus": 5,
                    "marginMode": "REGULAR_MARGIN",
                    "updatedTime": "1700000000000",
                }
            )
        return _response(
            {
                "list": [
                    {
                        "coin": [
                            {
                                "coin": "USDT",
                                "walletBalance": "12.34567890",
                                "availableToWithdraw": "10.1",
                                "equity": "12.4",
                            },
                            {"coin": "BTC", "walletBalance": "99"},
                        ]
                    }
                ]
            }
        )

    client = _client(handler)
    account = await client.get_account_info()
    balances = await client.get_balances()
    assert account.account_type == "uta2"
    assert account.margin_mode == "REGULAR_MARGIN"
    assert [item.asset for item in balances] == ["USDT"]
    assert balances[0].wallet_balance == Decimal("12.34567890")
    assert balances[0].available_balance == Decimal("10.1")
    assert all(isinstance(item.wallet_balance, Decimal) for item in balances)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (10003, ExchangePrivateAuthenticationError),
        (10005, ExchangePrivatePermissionError),
        (10002, ExchangePrivateTimestampError),
        (10006, ExchangePrivateRateLimited),
    ],
)
async def test_bybit_error_codes_are_safely_normalized(code, error):
    client = _client(lambda request: _response(code=code))
    with pytest.raises(error) as caught:
        await client.get_api_key_info()
    assert KEY not in str(caught.value)
    assert SECRET not in str(caught.value)


async def test_safe_get_retries_selected_5xx_only():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(status=503)
        return _response(
            {"readOnly": 1, "permissions": {"Wallet": []}, "ips": [], "uta": 1}
        )

    info = await _client(handler, retries=1).get_api_key_info()
    assert info.read_only is True
    assert calls == 2


async def test_timestamp_error_synchronizes_from_public_server_time_once():
    signed_timestamps = []
    private_calls = 0

    def handler(request):
        nonlocal private_calls
        if request.url.path.endswith("/market/time"):
            return httpx.Response(
                200,
                json={"retCode": 0, "time": str(TIMESTAMP + 7000), "result": {}},
            )
        private_calls += 1
        signed_timestamps.append(request.headers["X-BAPI-TIMESTAMP"])
        if private_calls == 1:
            return _response(code=10002)
        return _response(
            {"readOnly": 1, "permissions": {"Wallet": []}, "ips": [], "uta": 1}
        )

    info = await _client(handler, retries=1).get_api_key_info()
    assert info.read_only is True
    assert signed_timestamps == [str(TIMESTAMP), str(TIMESTAMP + 7000)]


@pytest.mark.parametrize(
    "result",
    [None, {"list": "bad"}, {"list": [{"coin": [{"coin": "USDT", "walletBalance": "NaN"}]}]}],
)
async def test_malformed_wallet_responses_fail_closed(result):
    client = _client(lambda request: _response(result))
    with pytest.raises(ExchangePrivateBadResponse):
        await client.get_balances()


async def test_secrets_never_appear_in_repr_logs_or_diagnostics(caplog, monkeypatch):
    client = _client(
        lambda request: _response(
            {"readOnly": 1, "permissions": {"Wallet": []}, "ips": [], "uta": 1}
        )
    )
    caplog.set_level(logging.INFO)
    info = await client.get_api_key_info()
    text = repr(client) + caplog.text + json.dumps(asdict(info))
    assert KEY not in text
    assert SECRET not in text
    assert settings.model_copy(
        update={"BYBIT_API_KEY": SecretStr(KEY), "BYBIT_API_SECRET": SecretStr(SECRET)}
    ).__repr__().find(SECRET) == -1

    monkeypatch.setattr(settings, "BYBIT_PRIVATE_ENABLED", True)
    monkeypatch.setattr(settings, "BYBIT_API_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "BYBIT_API_SECRET", SecretStr(SECRET))
    monkeypatch.setattr(runtime, "_client", client)
    diagnostics = await runtime.get_bybit_private_diagnostics()
    serialized = json.dumps(diagnostics)
    assert KEY not in serialized
    assert SECRET not in serialized


async def test_permission_gate_stops_before_account_and_balance_reads(monkeypatch):
    class OverPrivilegedClient:
        last_latency_ms = 1.0
        last_success_at = datetime.now(UTC)
        rate_limit_remaining = 9
        account_calls = 0
        balance_calls = 0

        async def get_api_key_info(self):
            return ExchangeApiKeyInfo(
                provider="bybit",
                masked_key="****1234",
                read_only=False,
                permission_safety="OVER_PRIVILEGED",
                ip_restricted=False,
                expires_at=None,
                deadline_days=7,
                account_type="unified",
            )

        async def get_account_info(self):
            self.account_calls += 1

        async def get_balances(self):
            self.balance_calls += 1

    fake = OverPrivilegedClient()
    monkeypatch.setattr(settings, "BYBIT_PRIVATE_ENABLED", True)
    monkeypatch.setattr(settings, "BYBIT_API_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "BYBIT_API_SECRET", SecretStr(SECRET))
    monkeypatch.setattr(runtime, "_client", fake)
    diagnostics = await runtime.get_bybit_private_diagnostics()
    assert diagnostics["status"] == "over_privileged"
    assert diagnostics["permission_safety"] == "OVER_PRIVILEGED"
    assert fake.account_calls == fake.balance_calls == 0


async def test_private_diagnostics_are_owner_only_and_secret_free(
    client, make_account, monkeypatch
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    monkeypatch.setattr(settings, "BYBIT_PRIVATE_ENABLED", False)
    monkeypatch.setattr(settings, "BYBIT_API_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "BYBIT_API_SECRET", SecretStr(SECRET))

    response = await client.get(
        "/api/v1/owner/integrations/diagnostics", headers=_headers(owner)
    )
    assert response.status_code == 200
    serialized = response.text
    assert KEY not in serialized
    assert SECRET not in serialized
    private = response.json()["exchange_private"]
    assert private["bybit"]["configured"] is True
    assert private["bybit"]["status"] == "disabled"
    assert private["binance"]["status"] == "not_configured"

    for actor in (user, merchant):
        denied = await client.get(
            "/api/v1/owner/integrations/diagnostics", headers=_headers(actor)
        )
        assert denied.status_code == 403
