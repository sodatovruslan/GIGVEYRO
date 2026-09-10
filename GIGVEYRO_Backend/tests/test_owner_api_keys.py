from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_owner_lists_all_merchant_api_keys(client, make_account):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await client.post("/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant_a))
    await client.post("/merchant/api-keys", json={"label": "B"}, headers=_auth_headers(merchant_b))

    response = await client.get("/owner/api-keys", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_merchant_cannot_list_owner_api_keys_view(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/owner/api-keys", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_owner_force_revokes_api_key(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant)
    )
    key_id = create.json()["id"]

    response = await client.post(
        f"/owner/api-keys/{key_id}/revoke", headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "revoked"

    # Key no longer authenticates the public API.
    api_response = await client.post(
        "/api/v1/public/invoices",
        json={"amount": "5"},
        headers={"Authorization": f"Bearer {create.json()['raw_key']}"},
    )
    assert api_response.status_code == 401


async def test_owner_revoke_already_revoked_key_conflicts(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/merchant/api-keys", json={"label": "A"}, headers=_auth_headers(merchant)
    )
    key_id = create.json()["id"]
    await client.post(f"/owner/api-keys/{key_id}/revoke", headers=_auth_headers(owner))

    response = await client.post(
        f"/owner/api-keys/{key_id}/revoke", headers=_auth_headers(owner)
    )

    assert response.status_code == 409
