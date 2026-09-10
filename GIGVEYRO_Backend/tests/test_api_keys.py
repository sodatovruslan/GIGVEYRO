from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_creates_api_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/api-keys", json={"label": "Storefront"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_key"].startswith("gk_live_")
    assert body["key_prefix"] == body["raw_key"][:12]
    assert body["status"] == "active"
    assert "key_hash" not in body


async def test_user_cannot_create_api_key(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/merchant/api-keys", json={"label": "x"}, headers=_auth_headers(user)
    )

    assert response.status_code == 403


async def test_api_key_list_never_returns_raw_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.post("/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant))

    response = await client.get("/merchant/api-keys", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "raw_key" not in body["items"][0]
    assert "key_hash" not in body["items"][0]


async def test_merchant_cannot_see_another_merchants_keys(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await client.post("/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant_a))

    response = await client.get("/merchant/api-keys", headers=_auth_headers(merchant_b))

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_merchant_cannot_revoke_another_merchants_key(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant_a)
    )
    key_id = create.json()["id"]

    response = await client.post(
        f"/merchant/api-keys/{key_id}/revoke", headers=_auth_headers(merchant_b)
    )

    assert response.status_code == 404


async def test_revoke_api_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant)
    )
    key_id = create.json()["id"]

    response = await client.post(
        f"/merchant/api-keys/{key_id}/revoke", headers=_auth_headers(merchant)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


async def test_revoke_already_revoked_key_conflicts(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant)
    )
    key_id = create.json()["id"]
    await client.post(f"/merchant/api-keys/{key_id}/revoke", headers=_auth_headers(merchant))

    response = await client.post(
        f"/merchant/api-keys/{key_id}/revoke", headers=_auth_headers(merchant)
    )

    assert response.status_code == 409
