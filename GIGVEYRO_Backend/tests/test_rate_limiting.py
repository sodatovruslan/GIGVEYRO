from unittest.mock import AsyncMock

from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _force_rate_limited(monkeypatch) -> AsyncMock:
    limited = AsyncMock(return_value=True)
    monkeypatch.setattr("app.core.rate_limit._limiter.is_rate_limited", limited)
    return limited


async def test_merchant_withdrawal_creation_is_rate_limited(
    client, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    limited = _force_rate_limited(monkeypatch)

    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 429
    assert limited.await_count == 1


async def test_merchant_invoice_creation_is_rate_limited(client, make_account, monkeypatch):
    merchant = await make_account(role=UserRole.MERCHANT)
    limited = _force_rate_limited(monkeypatch)

    response = await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 429
    assert limited.await_count == 1


async def test_public_invoice_read_is_rate_limited(client, make_account, monkeypatch):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant)
    )
    public_id = create.json()["public_id"]
    limited = _force_rate_limited(monkeypatch)

    response = await client.get(f"/invoices/{public_id}")

    assert response.status_code == 429
    assert limited.await_count == 1


async def test_api_key_authentication_is_rate_limited(client, monkeypatch):
    _force_rate_limited(monkeypatch)

    response = await client.post(
        "/api/v1/public/invoices",
        json={"amount": "5"},
        headers={"Authorization": "Bearer gk_live_whatever"},
    )

    assert response.status_code == 429


async def test_access_request_creation_is_rate_limited(client, monkeypatch):
    limited = _force_rate_limited(monkeypatch)

    response = await client.post(
        "/access-requests",
        json={"full_name": "Spammer", "contact": "@spammer"},
    )

    assert response.status_code == 429
    assert limited.await_count == 1
