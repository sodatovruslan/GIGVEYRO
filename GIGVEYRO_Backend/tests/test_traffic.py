import uuid

from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- CREATION FLOW INTEGRATION -------------------------------------------


async def test_creating_user_creates_traffic_settings_off(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newuser_{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "New User",
        },
        headers=_auth_headers(owner),
    )
    account_id = create_resp.json()["id"]

    traffic_resp = await client.get(
        f"/owner/accounts/{account_id}/traffic", headers=_auth_headers(owner)
    )

    assert traffic_resp.status_code == 200
    body = traffic_resp.json()
    assert body["is_enabled"] is False
    assert body["enabled_at"] is None
    assert body["disabled_at"] is None


async def test_creating_merchant_does_not_create_traffic_settings(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newmerchant_{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "merchant",
            "full_name": "New Merchant",
        },
        headers=_auth_headers(owner),
    )
    account_id = create_resp.json()["id"]

    traffic_resp = await client.get(
        f"/owner/accounts/{account_id}/traffic", headers=_auth_headers(owner)
    )

    assert traffic_resp.status_code == 404


# ---- ENABLE RULES -----------------------------------------------------


async def test_enable_traffic_without_any_card_rejected(
    client, make_account, make_traffic_settings
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user)

    response = await client.post("/traffic/enable", headers=_auth_headers(user))

    assert response.status_code == 409


async def test_enable_traffic_with_inactive_card_rejected(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user)
    await make_requisite(user, is_active=False)

    response = await client.post("/traffic/enable", headers=_auth_headers(user))

    assert response.status_code == 409


async def test_enable_traffic_with_archived_card_rejected(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user)
    await make_requisite(user, is_active=False, is_archived=True)

    response = await client.post("/traffic/enable", headers=_auth_headers(user))

    assert response.status_code == 409


async def test_enable_traffic_with_active_card_succeeds(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user)
    await make_requisite(user)

    response = await client.post("/traffic/enable", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["is_enabled"] is True
    assert body["enabled_at"] is not None
    assert body["disabled_at"] is None


async def test_enable_traffic_is_idempotent(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user)
    await make_requisite(user)

    first = await client.post("/traffic/enable", headers=_auth_headers(user))
    second = await client.post("/traffic/enable", headers=_auth_headers(user))

    assert first.status_code == second.status_code == 200
    assert second.json()["is_enabled"] is True


# ---- DISABLE ------------------------------------------------------------


async def test_disable_traffic(client, make_account, make_traffic_settings, make_requisite):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=True)
    await make_requisite(user)

    response = await client.post("/traffic/disable", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["is_enabled"] is False
    assert body["disabled_at"] is not None


async def test_disable_traffic_is_idempotent(client, make_account, make_traffic_settings):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=False)

    response = await client.post("/traffic/disable", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["is_enabled"] is False


# ---- AUTO DISABLE -------------------------------------------------------


async def test_deactivating_last_active_requisite_disables_traffic(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=True)
    requisite = await make_requisite(user)

    await client.post(f"/requisites/{requisite.id}/deactivate", headers=_auth_headers(user))

    traffic_resp = await client.get("/traffic", headers=_auth_headers(user))
    assert traffic_resp.json()["is_enabled"] is False


async def test_archiving_last_active_requisite_disables_traffic(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=True)
    requisite = await make_requisite(user)

    await client.post(f"/requisites/{requisite.id}/archive", headers=_auth_headers(user))

    traffic_resp = await client.get("/traffic", headers=_auth_headers(user))
    assert traffic_resp.json()["is_enabled"] is False


async def test_deactivating_one_of_two_requisites_keeps_traffic_on(
    client, make_account, make_traffic_settings, make_requisite
):
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=True)
    requisite_a = await make_requisite(user, card_number="4111111111111111")
    await make_requisite(user, card_number="4222222222222222")

    await client.post(f"/requisites/{requisite_a.id}/deactivate", headers=_auth_headers(user))

    traffic_resp = await client.get("/traffic", headers=_auth_headers(user))
    assert traffic_resp.json()["is_enabled"] is True


# ---- BLOCK / UNBLOCK INTEGRATION ------------------------------------------


async def test_blocking_user_disables_traffic(
    client, make_account, make_traffic_settings, make_requisite
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=True)
    await make_requisite(user)

    block_resp = await client.post(
        f"/owner/accounts/{user.id}/block", headers=_auth_headers(owner)
    )
    assert block_resp.status_code == 200

    traffic_resp = await client.get(
        f"/owner/accounts/{user.id}/traffic", headers=_auth_headers(owner)
    )
    assert traffic_resp.json()["is_enabled"] is False


async def test_unblocking_user_does_not_reenable_traffic(
    client, make_account, make_traffic_settings, make_requisite
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER, is_active=False)
    await make_traffic_settings(user, is_enabled=False)
    await make_requisite(user)

    unblock_resp = await client.post(
        f"/owner/accounts/{user.id}/unblock", headers=_auth_headers(owner)
    )
    assert unblock_resp.status_code == 200

    traffic_resp = await client.get(
        f"/owner/accounts/{user.id}/traffic", headers=_auth_headers(owner)
    )
    assert traffic_resp.json()["is_enabled"] is False


# ---- OWNER READ / RBAC -----------------------------------------------------


async def test_owner_reads_user_traffic(client, make_account, make_traffic_settings):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_traffic_settings(user, is_enabled=False)

    response = await client.get(
        f"/owner/accounts/{user.id}/traffic", headers=_auth_headers(owner)
    )

    assert response.status_code == 200


async def test_owner_traffic_view_rejected_for_user(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get(
        f"/owner/accounts/{user.id}/traffic", headers=_auth_headers(user)
    )

    assert response.status_code == 403


async def test_owner_traffic_view_rejected_for_merchant(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get(
        f"/owner/accounts/{merchant.id}/traffic", headers=_auth_headers(merchant)
    )

    assert response.status_code == 403


async def test_merchant_cannot_access_own_traffic_endpoint(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/traffic", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_traffic_requires_authentication(client):
    response = await client.get("/traffic")
    assert response.status_code == 401
