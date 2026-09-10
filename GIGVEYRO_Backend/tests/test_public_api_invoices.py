from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _issue_api_key(client, merchant) -> str:
    response = await client.post(
        "/merchant/api-keys", json={"label": "Integration"}, headers=_auth_headers(merchant)
    )
    return response.json()["raw_key"]


def _api_headers(raw_key: str) -> dict:
    return {"Authorization": f"Bearer {raw_key}"}


async def test_create_invoice_via_api_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    raw_key = await _issue_api_key(client, merchant)

    response = await client.post(
        "/api/v1/public/invoices",
        json={"amount": "12.5", "description": "API order"},
        headers=_api_headers(raw_key),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["merchant_id"] == str(merchant.id)
    assert body["amount"] == "12.50000000"


async def test_get_invoice_via_api_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    raw_key = await _issue_api_key(client, merchant)
    create = await client.post(
        "/api/v1/public/invoices", json={"amount": "5"}, headers=_api_headers(raw_key)
    )
    invoice_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/public/invoices/{invoice_id}", headers=_api_headers(raw_key)
    )

    assert response.status_code == 200
    assert response.json()["id"] == invoice_id


async def test_invalid_api_key_rejected(client):
    response = await client.post(
        "/api/v1/public/invoices",
        json={"amount": "5"},
        headers=_api_headers("gk_live_totally_made_up"),
    )

    assert response.status_code == 401


async def test_revoked_api_key_rejected(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    raw_key = await _issue_api_key(client, merchant)
    list_response = await client.get("/merchant/api-keys", headers=_auth_headers(merchant))
    key_id = list_response.json()["items"][0]["id"]
    await client.post(f"/merchant/api-keys/{key_id}/revoke", headers=_auth_headers(merchant))

    response = await client.post(
        "/api/v1/public/invoices", json={"amount": "5"}, headers=_api_headers(raw_key)
    )

    assert response.status_code == 401


async def test_merchant_cannot_read_another_merchants_invoice_via_api_key(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    key_a = await _issue_api_key(client, merchant_a)
    key_b = await _issue_api_key(client, merchant_b)
    create = await client.post(
        "/api/v1/public/invoices", json={"amount": "9"}, headers=_api_headers(key_a)
    )
    invoice_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/public/invoices/{invoice_id}", headers=_api_headers(key_b)
    )

    assert response.status_code == 404
