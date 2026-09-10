from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_creates_webhook(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://example.com/hook"
    assert body["event_types"] == ["invoice.paid"]
    assert body["status"] == "active"
    assert len(body["secret"]) > 20
    assert "encrypted_secret" not in body


async def test_create_webhook_rejects_unknown_event_type(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["totally.made.up"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_create_webhook_rejects_bad_url(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "ftp://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 422


async def test_user_cannot_create_webhook(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(user),
    )

    assert response.status_code == 403


async def test_webhook_list_never_returns_secret(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )

    response = await client.get("/merchant/webhooks", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "secret" not in body["items"][0]
    assert "encrypted_secret" not in body["items"][0]


async def test_merchant_cannot_see_another_merchants_webhooks(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant_a),
    )
    webhook_id = create.json()["id"]

    get_response = await client.get(
        f"/merchant/webhooks/{webhook_id}", headers=_auth_headers(merchant_b)
    )
    list_response = await client.get("/merchant/webhooks", headers=_auth_headers(merchant_b))

    assert get_response.status_code == 404
    assert list_response.json()["total"] == 0


async def test_merchant_disables_webhook(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant),
    )
    webhook_id = create.json()["id"]

    response = await client.patch(
        f"/merchant/webhooks/{webhook_id}",
        json={"status": "disabled"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


async def test_deliveries_list_scoped_to_own_webhook(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/webhooks",
        json={"url": "https://example.com/hook", "event_types": ["invoice.paid"]},
        headers=_auth_headers(merchant_a),
    )
    webhook_id = create.json()["id"]

    own = await client.get(
        f"/merchant/webhooks/{webhook_id}/deliveries", headers=_auth_headers(merchant_a)
    )
    other = await client.get(
        f"/merchant/webhooks/{webhook_id}/deliveries", headers=_auth_headers(merchant_b)
    )

    assert own.status_code == 200
    assert own.json()["total"] == 0
    assert other.status_code == 404
