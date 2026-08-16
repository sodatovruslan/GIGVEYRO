import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_owner_lists_all_deals(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_deal(merchant_a)
    await make_deal(merchant_b)

    response = await client.get("/owner/deals", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_owner_gets_deal_by_id(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)

    response = await client.get(f"/owner/deals/{deal.id}", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["id"] == str(deal.id)


async def test_owner_gets_nonexistent_deal_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get(f"/owner/deals/{uuid.uuid4()}", headers=_auth_headers(owner))

    assert response.status_code == 404


async def test_owner_filters_deals_by_status(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_deal(merchant, status=DealStatus.AVAILABLE)
    await make_deal(merchant, status=DealStatus.CANCELLED)

    response = await client.get(
        "/owner/deals", params={"status": "cancelled"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == DealStatus.CANCELLED.value


async def test_owner_filters_deals_by_merchant_id(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_deal(merchant_a)
    await make_deal(merchant_b)

    response = await client.get(
        "/owner/deals", params={"merchant_id": str(merchant_a.id)}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["merchant_id"] == str(merchant_a.id)


async def test_owner_filters_deals_by_user_id(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_deal(merchant, status=DealStatus.ACCEPTED, user=user_a)
    await make_deal(merchant, status=DealStatus.ACCEPTED, user=user_b)

    response = await client.get(
        "/owner/deals", params={"user_id": str(user_a.id)}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["user_id"] == str(user_a.id)


async def test_owner_searches_deals_by_public_id(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)
    await make_deal(merchant)

    response = await client.get(
        "/owner/deals", params={"search": deal.public_id}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["public_id"] == deal.public_id


async def test_owner_deals_pagination(client, make_account, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    for _ in range(3):
        await make_deal(merchant, amount_tjs=Decimal("50"))

    response = await client.get(
        "/owner/deals", params={"limit": 2, "offset": 0}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_user_forbidden_from_owner_deals(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get("/owner/deals", headers=_auth_headers(user))

    assert response.status_code == 403


async def test_merchant_forbidden_from_owner_deals(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/owner/deals", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_owner_deals_require_authentication(client):
    response = await client.get("/owner/deals")
    assert response.status_code == 401
