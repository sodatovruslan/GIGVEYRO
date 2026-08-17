import uuid

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_merchant_creates_deal(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/deals", json={"amount_tjs": "200.00"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == DealStatus.AVAILABLE.value
    assert body["amount_tjs"] == "200.00000000"
    assert body["user_id"] is None
    assert body["payment_requisite_id"] is None
    assert body["exchange_rate"] is None
    assert body["amount_usdt"] is None
    assert body["public_id"].startswith("D-")


async def test_create_deal_rejects_zero_amount(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/deals", json={"amount_tjs": "0"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 422


async def test_create_deal_rejects_negative_amount(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/deals", json={"amount_tjs": "-5"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 422


async def test_user_cannot_create_deal(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/merchant/deals", json={"amount_tjs": "200"}, headers=_auth_headers(user)
    )

    assert response.status_code == 403


async def test_owner_cannot_use_merchant_endpoints(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        "/merchant/deals", json={"amount_tjs": "200"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 403


async def test_merchant_deals_require_authentication(client):
    response = await client.get("/merchant/deals")
    assert response.status_code == 401


async def test_merchant_lists_own_deals(client, make_account, make_deal):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_deal(merchant)
    await make_deal(merchant)

    response = await client.get("/merchant/deals", headers=_auth_headers(merchant))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


async def test_merchant_cannot_see_another_merchants_deal(client, make_account, make_deal):
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant_a)

    response = await client.get(f"/merchant/deals/{deal.id}", headers=_auth_headers(merchant_b))

    assert response.status_code == 404


async def test_merchant_gets_nonexistent_deal_returns_404(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get(f"/merchant/deals/{uuid.uuid4()}", headers=_auth_headers(merchant))

    assert response.status_code == 404


async def test_merchant_filters_deals_by_status(client, make_account, make_deal):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_deal(merchant, status=DealStatus.AVAILABLE)
    await make_deal(merchant, status=DealStatus.CANCELLED)

    response = await client.get(
        "/merchant/deals", params={"status": "cancelled"}, headers=_auth_headers(merchant)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == DealStatus.CANCELLED.value
