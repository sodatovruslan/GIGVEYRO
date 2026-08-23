import uuid
from decimal import Decimal

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.wallet import BalanceBucket, LedgerEntryType
from app.services.deal import calculate_amount_usdt


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _make_ready_user(make_account, make_wallet, make_requisite, make_traffic_settings, **kw):
    user = await make_account(role=UserRole.USER, **kw)
    await make_wallet(user, available=Decimal("500"))
    requisite = await make_requisite(user)
    await make_traffic_settings(user, is_enabled=True)
    return user, requisite


# ---- ROUNDING (pure function) --------------------------------------------


def test_calculate_amount_usdt_rounds_to_8_places():
    result = calculate_amount_usdt(Decimal("200"), Decimal("10.90"))
    assert result == Decimal("18.34862385")


# ---- AVAILABLE LIST -----------------------------------------------------


async def test_available_deals_lists_active_deal(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, _ = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant)

    response = await client.get("/deals/available", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(deal.id)


async def test_available_deals_excludes_expired(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, _ = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    await make_deal(merchant, expires_in_minutes=-1)

    response = await client.get("/deals/available", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_available_deals_excludes_already_accepted(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    other_user = await make_account(role=UserRole.USER)
    user, _ = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    await make_deal(merchant, status=DealStatus.ACCEPTED, user=other_user)

    response = await client.get("/deals/available", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_available_deals_rejected_when_traffic_disabled(
    client, make_account, make_wallet, make_requisite, make_traffic_settings
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    await make_requisite(user)
    await make_traffic_settings(user, is_enabled=False)

    response = await client.get("/deals/available", headers=_auth_headers(user))

    assert response.status_code == 409


async def test_merchant_cannot_access_available_deals(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/deals/available", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_deals_require_authentication(client):
    response = await client.get("/deals/available")
    assert response.status_code == 401


# ---- ACCEPT: SUCCESS + SNAPSHOTS ------------------------------------------


async def test_accept_deal_success_full_flow(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == DealStatus.ACCEPTED.value
    assert body["user_id"] == str(user.id)
    assert body["payment_requisite_id"] == str(requisite.id)
    assert body["exchange_rate"] == "10.90000000"
    assert body["rate_source"] == "FallbackExchangeRateProvider"
    assert body["rate_timestamp"] is not None
    assert body["rate_policy_version"] == "legacy-provider-v1"
    assert body["rate_mode"] == "configured"

    expected_usdt = calculate_amount_usdt(Decimal("200"), app_settings.DEMO_USDT_TJS_RATE)
    assert Decimal(body["amount_usdt"]) == expected_usdt
    assert body["accepted_at"] is not None

    # requisite snapshot
    assert body["requisite_type"] == "bank_card"
    assert body["requisite_bank_name"] == requisite.bank_name
    assert body["requisite_holder_name"] == requisite.holder_name
    assert body["requisite_masked_card_number"] == "**** **** **** 1234"
    assert "card_number" not in response.text.replace("masked_card_number", "")


async def test_accepted_deal_rate_snapshot_is_immutable_when_provider_rate_changes(
    client,
    make_account,
    make_wallet,
    make_requisite,
    make_traffic_settings,
    make_deal,
    monkeypatch,
):
    merchant = await make_account(role=UserRole.MERCHANT)
    first_user, first_requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    second_user, second_requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    first_deal = await make_deal(merchant, amount_tjs=Decimal("200"))
    second_deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    monkeypatch.setattr(app_settings, "DEMO_USDT_TJS_RATE", Decimal("10.50"))
    first_accept = await client.post(
        f"/deals/{first_deal.id}/accept",
        json={"payment_requisite_id": str(first_requisite.id)},
        headers=_auth_headers(first_user),
    )
    assert first_accept.status_code == 200
    assert first_accept.json()["exchange_rate"] == "10.50000000"

    monkeypatch.setattr(app_settings, "DEMO_USDT_TJS_RATE", Decimal("11.25"))
    second_accept = await client.post(
        f"/deals/{second_deal.id}/accept",
        json={"payment_requisite_id": str(second_requisite.id)},
        headers=_auth_headers(second_user),
    )
    assert second_accept.status_code == 200
    assert second_accept.json()["exchange_rate"] == "11.25000000"

    historical = await client.get(
        f"/deals/{first_deal.id}", headers=_auth_headers(first_user)
    )
    assert historical.status_code == 200
    assert historical.json()["exchange_rate"] == "10.50000000"


async def test_accept_deal_freezes_wallet_and_preserves_total(
    client,
    make_account,
    make_wallet,
    make_requisite,
    make_traffic_settings,
    make_deal,
    db_session,
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    wallet_body = wallet_resp.json()

    expected_usdt = calculate_amount_usdt(Decimal("200"), app_settings.DEMO_USDT_TJS_RATE)
    assert Decimal(wallet_body["available_balance"]) == Decimal("500") - expected_usdt
    assert Decimal(wallet_body["frozen_balance"]) == expected_usdt

    total = (
        Decimal(wallet_body["available_balance"])
        + Decimal(wallet_body["insurance_balance"])
        + Decimal(wallet_body["frozen_balance"])
    )
    assert total == Decimal("500")


async def test_accept_deal_creates_deal_freeze_ledger_entry(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    ledger_resp = await client.get("/wallet/ledger", headers=_auth_headers(user))
    items = ledger_resp.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["type"] == LedgerEntryType.DEAL_FREEZE.value
    assert entry["balance_bucket"] == BalanceBucket.FROZEN.value

    expected_usdt = calculate_amount_usdt(Decimal("200"), app_settings.DEMO_USDT_TJS_RATE)
    assert Decimal(entry["amount"]) == expected_usdt
    assert Decimal(entry["available_before"]) == Decimal("500")
    assert Decimal(entry["available_after"]) == Decimal("500") - expected_usdt
    assert Decimal(entry["frozen_before"]) == Decimal("0")
    assert Decimal(entry["frozen_after"]) == expected_usdt


# ---- ACCEPT: REJECTION PATHS ----------------------------------------------


async def test_accept_deal_insufficient_balance(
    client, make_account, make_requisite, make_traffic_settings, make_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("1"))
    requisite = await make_requisite(user)
    await make_traffic_settings(user, is_enabled=True)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_resp.json()["available_balance"] == "1.00000000"


async def test_accept_deal_with_another_users_requisite_rejected(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, _ = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    other_user = await make_account(role=UserRole.USER)
    other_requisite = await make_requisite(other_user, card_number="4222222222222222")
    deal = await make_deal(merchant)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(other_requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409


async def test_accept_deal_with_archived_requisite_rejected(
    client, make_account, make_wallet, make_traffic_settings, make_requisite, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("500"))
    requisite = await make_requisite(user, is_active=False, is_archived=True)
    await make_traffic_settings(user, is_enabled=True)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409


async def test_accept_deal_with_deactivated_requisite_rejected(
    client, make_account, make_wallet, make_traffic_settings, make_requisite, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("500"))
    requisite = await make_requisite(user, is_active=False)
    await make_traffic_settings(user, is_enabled=True)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409


async def test_accept_deal_with_traffic_disabled_rejected(
    client, make_account, make_wallet, make_requisite, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("500"))
    requisite = await make_requisite(user)
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409


async def test_accept_expired_deal_rejected(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, expires_in_minutes=-1)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 409

    merchant_view = await client.get(f"/merchant/deals/{deal.id}", headers=_auth_headers(merchant))
    assert merchant_view.json()["status"] == DealStatus.EXPIRED.value


async def test_accept_deal_twice_rejected_second_time(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))

    first = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )
    assert first.status_code == 200

    second = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )
    assert second.status_code == 409

    wallet_resp = await client.get("/wallet", headers=_auth_headers(user))
    expected_usdt = calculate_amount_usdt(Decimal("200"), app_settings.DEMO_USDT_TJS_RATE)
    assert Decimal(wallet_resp.json()["available_balance"]) == Decimal("500") - expected_usdt


async def test_accept_nonexistent_deal_returns_404(
    client, make_account, make_wallet, make_requisite, make_traffic_settings
):
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )

    response = await client.post(
        f"/deals/{uuid.uuid4()}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    assert response.status_code == 404


async def test_merchant_cannot_accept_deals(client, make_account, make_deal):
    merchant = await make_account(role=UserRole.MERCHANT)
    deal = await make_deal(merchant)

    response = await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(uuid.uuid4())},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 403


# ---- USER OWN DEALS -------------------------------------------------------


async def test_user_lists_own_accepted_deals(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, amount_tjs=Decimal("200"))
    await client.post(
        f"/deals/{deal.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth_headers(user),
    )

    response = await client.get("/deals", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(deal.id)


async def test_user_cannot_see_another_users_accepted_deal(
    client, make_account, make_wallet, make_requisite, make_traffic_settings, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    owner_user, requisite = await _make_ready_user(
        make_account, make_wallet, make_requisite, make_traffic_settings
    )
    deal = await make_deal(merchant, status=DealStatus.ACCEPTED, user=owner_user)

    other_user = await make_account(role=UserRole.USER)

    response = await client.get(f"/deals/{deal.id}", headers=_auth_headers(other_user))

    assert response.status_code == 404
