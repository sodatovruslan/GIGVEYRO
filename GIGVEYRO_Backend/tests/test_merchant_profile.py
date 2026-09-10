from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_gets_default_empty_profile(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/merchant/profile", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == str(merchant.id)
    assert body["store_name"] is None


async def test_merchant_updates_profile(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.put(
        "/merchant/profile",
        json={
            "store_name": "GigaPay Test Store",
            "description": "We sell things",
            "support_contact": "support@example.com",
        },
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["store_name"] == "GigaPay Test Store"
    assert body["support_contact"] == "support@example.com"

    reread = await client.get("/merchant/profile", headers=_auth_headers(merchant))
    assert reread.json()["store_name"] == "GigaPay Test Store"


async def test_user_cannot_access_merchant_profile(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get("/merchant/profile", headers=_auth_headers(user))

    assert response.status_code == 403


async def test_public_invoice_shows_store_name(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    await client.put(
        "/merchant/profile",
        json={"store_name": "GigaPay Test Store", "description": None, "support_contact": None},
        headers=_auth_headers(merchant),
    )
    create = await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant)
    )
    public_id = create.json()["public_id"]

    response = await client.get(f"/invoices/{public_id}")

    assert response.status_code == 200
    assert response.json()["store_name"] == "GigaPay Test Store"


async def test_public_invoice_store_name_null_without_profile(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    create = await client.post(
        "/merchant/invoices", json={"amount": "10"}, headers=_auth_headers(merchant)
    )
    public_id = create.json()["public_id"]

    response = await client.get(f"/invoices/{public_id}")

    assert response.status_code == 200
    assert response.json()["store_name"] is None
