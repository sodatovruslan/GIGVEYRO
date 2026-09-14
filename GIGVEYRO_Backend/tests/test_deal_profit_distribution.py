from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- SPLIT MATH -----------------------------------------------------------


async def test_deal_200_splits_into_owner_14_user_profit_20_merchant_166(
    client, make_account, make_wallet, make_merchant_wallet, make_deal
):
    """A second, larger deal amount than the canonical 100/20 examples used
    elsewhere - confirms the split isn't hardcoded to one number and stays
    exact (no float drift) at a different scale. 200 * 7% = 14.00,
    200 * 10% = 20.00, merchant gets the residual: 200 - 14 - 20 = 166.00."""
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("200"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("200")
    )

    response = await client.post(
        f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["merchant_settlement_amount"] == "166.00000000"
    assert body["user_profit_amount"] == "20.00000000"
    assert body["owner_profit_amount"] == "14.00000000"

    merchant_wallet = await client.get("/merchant/wallet", headers=_auth_headers(merchant))
    assert merchant_wallet.json()["available_balance"] == "166.00000000"

    user_wallet = await client.get("/wallet", headers=_auth_headers(user))
    assert user_wallet.json()["available_balance"] == "20.00000000"
    assert user_wallet.json()["frozen_balance"] == "0.00000000"


# ---- RELEASE/CANCEL NEVER DISTRIBUTES PROFIT -------------------------------


async def test_released_deal_has_no_profit_distribution(
    client, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("50"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("50")
    )

    response = await client.post(f"/owner/deals/{deal.id}/release", headers=_auth_headers(owner))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["merchant_settlement_amount"] is None
    assert body["user_profit_amount"] is None
    assert body["owner_profit_amount"] is None

    user_wallet = await client.get("/wallet", headers=_auth_headers(user))
    assert user_wallet.json()["available_balance"] == "50.00000000"
    assert user_wallet.json()["frozen_balance"] == "0.00000000"

    merchant_wallet = await client.get("/merchant/wallet", headers=_auth_headers(merchant))
    assert merchant_wallet.json()["available_balance"] == "0.00000000"


async def test_pending_available_deal_has_no_profit_fields(
    client, make_account, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant, status=DealStatus.AVAILABLE)

    response = await client.get(f"/merchant/deals/{deal.id}", headers=_auth_headers(merchant))
    assert response.status_code == 200
    body = response.json()
    assert body["merchant_settlement_amount"] is None
    assert body["user_profit_amount"] is None


# ---- ROLE-SCOPED VISIBILITY OF OWNER PROFIT --------------------------------


async def test_owner_profit_amount_hidden_from_user_and_merchant_views(
    client, make_account, make_wallet, make_merchant_wallet, make_deal
):
    """USER and MERCHANT see their own settlement/profit figures but never
    the platform's own retained margin - only OWNER's endpoint exposes
    owner_profit_amount."""
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )
    await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))

    user_view = await client.get(f"/deals/{deal.id}", headers=_auth_headers(user))
    assert user_view.status_code == 200
    assert "owner_profit_amount" not in user_view.json()
    assert user_view.json()["user_profit_amount"] == "10.00000000"

    merchant_view = await client.get(f"/merchant/deals/{deal.id}", headers=_auth_headers(merchant))
    assert merchant_view.status_code == 200
    assert "owner_profit_amount" not in merchant_view.json()
    assert merchant_view.json()["merchant_settlement_amount"] == "83.00000000"

    owner_view = await client.get(f"/owner/deals/{deal.id}", headers=_auth_headers(owner))
    assert owner_view.status_code == 200
    assert owner_view.json()["owner_profit_amount"] == "7.00000000"


# ---- IDEMPOTENCY OF THE OWNER-PROFIT ACCOUNTING RECORD ---------------------


async def test_double_complete_via_api_does_not_duplicate_owner_profit(
    client, make_account, make_wallet, make_merchant_wallet, make_deal, db_session
):
    from sqlalchemy import select

    from app.models.fees import OwnerProfitEntry

    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    owner = await make_account(role=UserRole.OWNER)

    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )

    first = await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    second = await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    assert first.status_code == 200
    assert second.status_code == 200

    entries = (
        await db_session.execute(
            select(OwnerProfitEntry).where(OwnerProfitEntry.source_id == deal.id)
        )
    ).scalars().all()
    assert len(entries) == 1
    assert entries[0].fee_amount == Decimal("7.00000000")
