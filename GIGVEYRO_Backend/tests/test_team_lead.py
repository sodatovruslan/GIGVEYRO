from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- ACCOUNT CREATION / WALLET AUTO-PROVISIONING --------------------------


async def test_owner_creates_team_lead_account_with_wallet(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.post(
        "/owner/accounts",
        json={
            "username": "tl_created",
            "password": "TeamLead12345",
            "role": "team_lead",
            "full_name": "New Team Lead",
        },
        headers=_auth_headers(owner),
    )
    assert response.status_code == 201
    team_lead_id = response.json()["id"]

    wallet_response = await client.get(
        f"/owner/accounts/{team_lead_id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_response.status_code == 200
    assert wallet_response.json()["available_balance"] == "0.00000000"


# ---- OWNER ASSIGNS/REASSIGNS TEAM MEMBERSHIP ------------------------------


async def test_owner_assigns_user_to_team_lead(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(team_lead.id)},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["team_lead_id"] == str(team_lead.id)


async def test_owner_unassigns_user_from_team_lead(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    user = await make_account(role=UserRole.USER)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(team_lead.id)},
        headers=_auth_headers(owner),
    )

    response = await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": None},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["team_lead_id"] is None


async def test_cannot_assign_merchant_to_team_lead(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        f"/owner/accounts/{merchant.id}/team-lead",
        json={"team_lead_id": str(team_lead.id)},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 400


async def test_cannot_assign_user_to_non_team_lead_account(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    not_a_lead = await make_account(role=UserRole.USER)
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(not_a_lead.id)},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 400


async def test_non_owner_cannot_assign_team_lead(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(team_lead.id)},
        headers=_auth_headers(merchant),
    )
    assert response.status_code == 403


# ---- RBAC ------------------------------------------------------------------


async def test_team_lead_cannot_access_owner_endpoints(client, make_account):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    response = await client.get("/owner/accounts", headers=_auth_headers(team_lead))
    assert response.status_code == 403


async def test_team_lead_cannot_access_treasury(client, make_account):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    response = await client.get(
        "/api/v1/owner/treasury/summary", headers=_auth_headers(team_lead)
    )
    assert response.status_code == 403


async def test_user_cannot_access_team_lead_cabinet(client, make_account):
    user = await make_account(role=UserRole.USER)
    response = await client.get("/team-lead/dashboard", headers=_auth_headers(user))
    assert response.status_code == 403


async def test_merchant_cannot_access_team_lead_cabinet(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    response = await client.get("/team-lead/team", headers=_auth_headers(merchant))
    assert response.status_code == 403


# ---- TEAM VISIBILITY / ISOLATION -------------------------------------------


async def test_team_lead_sees_only_own_team(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await client.post(
        f"/owner/accounts/{user_a.id}/team-lead",
        json={"team_lead_id": str(lead_a.id)},
        headers=_auth_headers(owner),
    )
    await client.post(
        f"/owner/accounts/{user_b.id}/team-lead",
        json={"team_lead_id": str(lead_b.id)},
        headers=_auth_headers(owner),
    )

    response = await client.get("/team-lead/team", headers=_auth_headers(lead_a))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(user_a.id)


async def test_team_member_list_never_leaks_wallet_balance_fields(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    lead = await make_account(role=UserRole.TEAM_LEAD)
    user = await make_account(role=UserRole.USER)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(lead.id)},
        headers=_auth_headers(owner),
    )

    response = await client.get("/team-lead/team", headers=_auth_headers(lead))
    member = response.json()["items"][0]
    assert "available_balance" not in member
    assert "frozen_balance" not in member


# ---- DASHBOARD / PROFIT SUMMARY --------------------------------------------


async def test_team_lead_dashboard_reflects_completed_team_deals(
    client, make_account, make_wallet, make_merchant_wallet, make_requisite,
    make_traffic_settings, make_deal,
):
    owner = await make_account(role=UserRole.OWNER)
    lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead, available=Decimal("0"))

    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    await make_traffic_settings(user, is_enabled=True)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(lead.id)},
        headers=_auth_headers(owner),
    )

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )

    complete = await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    assert complete.status_code == 200
    assert complete.json()["team_lead_profit_amount"] == "1.50000000"

    dashboard = await client.get("/team-lead/dashboard", headers=_auth_headers(lead))
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert data["profit_available"] == "1.50000000"
    assert data["deal_count"] == 1
    assert data["deal_volume"] == "100.00000000"
    assert data["team_size"] == 1


async def test_unassigned_user_deal_does_not_credit_any_team_lead(
    client, make_account, make_wallet, make_merchant_wallet, make_traffic_settings, make_deal,
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("50"))
    await make_traffic_settings(user, is_enabled=True)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("50")
    )

    complete = await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    assert complete.status_code == 200
    assert complete.json()["team_lead_profit_amount"] is None


async def test_deal_split_unaffected_by_team_lead_assignment(
    client, make_account, make_wallet, make_merchant_wallet, make_traffic_settings, make_deal,
):
    """The confirmed rule: team lead profit is funded separately and must
    never change merchant/user/owner amounts."""
    owner = await make_account(role=UserRole.OWNER)
    lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead, available=Decimal("0"))
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    await make_traffic_settings(user, is_enabled=True)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(lead.id)},
        headers=_auth_headers(owner),
    )
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )

    complete = await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    body = complete.json()
    assert body["merchant_settlement_amount"] == "83.00000000"
    assert body["user_profit_amount"] == "10.00000000"
    assert body["owner_profit_amount"] == "7.00000000"
    assert body["team_lead_profit_amount"] == "1.50000000"


async def test_double_complete_does_not_double_credit_team_lead(
    client, make_account, make_wallet, make_merchant_wallet, make_traffic_settings, make_deal,
):
    owner = await make_account(role=UserRole.OWNER)
    lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead, available=Decimal("0"))
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    await make_traffic_settings(user, is_enabled=True)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(lead.id)},
        headers=_auth_headers(owner),
    )
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )

    await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))
    await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))

    dashboard = await client.get("/team-lead/dashboard", headers=_auth_headers(lead))
    assert dashboard.json()["profit_available"] == "1.50000000"


# ---- TEAM DEALS VIEW --------------------------------------------------------


async def test_team_lead_sees_team_deals_but_not_owner_profit_field(
    client, make_account, make_wallet, make_merchant_wallet, make_traffic_settings, make_deal,
):
    owner = await make_account(role=UserRole.OWNER)
    lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead, available=Decimal("0"))
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("0"), frozen=Decimal("100"))
    await make_traffic_settings(user, is_enabled=True)
    await client.post(
        f"/owner/accounts/{user.id}/team-lead",
        json={"team_lead_id": str(lead.id)},
        headers=_auth_headers(owner),
    )
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("100")
    )
    await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))

    response = await client.get("/team-lead/deals", headers=_auth_headers(lead))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["team_lead_profit_amount"] == "1.50000000"
    assert "owner_profit_amount" not in item


# ---- PROFIT LEDGER -----------------------------------------------------------


async def test_team_lead_profit_ledger_only_shows_own_entries(
    client, make_account, make_wallet, make_merchant_wallet, make_traffic_settings, make_deal,
):
    owner = await make_account(role=UserRole.OWNER)
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_a, available=Decimal("0"))
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_b, available=Decimal("0"))

    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("0"), frozen=Decimal("100"))
    await make_traffic_settings(user_a, is_enabled=True)
    await client.post(
        f"/owner/accounts/{user_a.id}/team-lead",
        json={"team_lead_id": str(lead_a.id)},
        headers=_auth_headers(owner),
    )

    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("0"))
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user_a, amount_usdt=Decimal("100")
    )
    await client.post(f"/owner/deals/{deal.id}/complete", headers=_auth_headers(owner))

    lead_a_ledger = await client.get("/team-lead/profit/ledger", headers=_auth_headers(lead_a))
    assert lead_a_ledger.json()["total"] == 1

    lead_b_ledger = await client.get("/team-lead/profit/ledger", headers=_auth_headers(lead_b))
    assert lead_b_ledger.json()["total"] == 0
