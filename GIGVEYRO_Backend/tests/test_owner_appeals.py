import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_owner_lists_all_appeals(client, make_account, make_wallet, make_deal):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Money never arrived"},
        headers=_auth_headers(user),
    )

    response = await client.get("/owner/appeals", headers=_auth_headers(owner))
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_owner_filters_appeals_by_merchant_id(
    client, make_account, make_wallet, make_deal
):
    owner = await make_account(role=UserRole.OWNER)

    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a, frozen=Decimal("20"))
    merchant_a = await make_account(role=UserRole.MERCHANT)
    deal_a = await make_deal(
        merchant_a, status=DealStatus.ACCEPTED, user=user_a, amount_usdt=Decimal("20")
    )

    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_b, frozen=Decimal("15"))
    merchant_b = await make_account(role=UserRole.MERCHANT)
    deal_b = await make_deal(
        merchant_b, status=DealStatus.ACCEPTED, user=user_b, amount_usdt=Decimal("15")
    )

    await client.post(
        f"/appeals/deals/{deal_a.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Appeal on deal A"},
        headers=_auth_headers(user_a),
    )
    await client.post(
        f"/appeals/deals/{deal_b.id}/appeal",
        json={"reason_code": "wrong_amount", "message": "Appeal on deal B"},
        headers=_auth_headers(user_b),
    )

    response = await client.get(
        "/owner/appeals",
        params={"merchant_id": str(merchant_a.id)},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["deal_id"] == str(deal_a.id)


async def test_owner_filters_appeals_by_user_id(client, make_account, make_wallet, make_deal):
    owner = await make_account(role=UserRole.OWNER)

    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    deal_a = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user_a, amount_usdt=Decimal("20")
    )

    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_b, frozen=Decimal("15"))
    deal_b = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user_b, amount_usdt=Decimal("15")
    )

    await client.post(
        f"/appeals/deals/{deal_a.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Appeal on deal A"},
        headers=_auth_headers(user_a),
    )
    await client.post(
        f"/appeals/deals/{deal_b.id}/appeal",
        json={"reason_code": "wrong_amount", "message": "Appeal on deal B"},
        headers=_auth_headers(user_b),
    )

    response = await client.get(
        "/owner/appeals", params={"user_id": str(user_b.id)}, headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["deal_id"] == str(deal_b.id)


async def test_owner_filters_appeals_by_merchant_id_and_status_combined(
    client, make_account, make_wallet, make_deal
):
    owner = await make_account(role=UserRole.OWNER)

    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Appeal"},
        headers=_auth_headers(user),
    )

    other_merchant = await make_account(role=UserRole.MERCHANT)
    response = await client.get(
        "/owner/appeals",
        params={"merchant_id": str(other_merchant.id), "status": "open"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_owner_gets_nonexistent_appeal_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.get(f"/owner/appeals/{uuid.uuid4()}", headers=_auth_headers(owner))
    assert response.status_code == 404


async def test_merchant_forbidden_from_owner_appeals(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    response = await client.get("/owner/appeals", headers=_auth_headers(merchant))
    assert response.status_code == 403
