import uuid

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- CREATE -------------------------------------------------------------


async def test_user_adds_card(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/requisites",
        json={
            "bank_name": "Test Bank",
            "holder_name": "John Doe",
            "card_number": "4111 1111-1111 1234",
            "phone_number": "+15551234567",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["bank_name"] == "Test Bank"
    assert body["masked_card_number"] == "**** **** **** 1234"
    assert body["is_active"] is True
    assert body["is_archived"] is False
    assert "card_number" not in body
    assert "4111111111111234" not in response.text
    assert "1111-1111" not in response.text


async def test_merchant_cannot_add_card(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/requisites",
        json={"bank_name": "B", "holder_name": "H", "card_number": "4111111111111234"},
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 403


async def test_owner_cannot_use_user_requisites_router(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        "/requisites",
        json={"bank_name": "B", "holder_name": "H", "card_number": "4111111111111234"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 403


async def test_requisites_require_authentication(client):
    response = await client.get("/requisites")
    assert response.status_code == 401


async def test_duplicate_card_rejected(client, make_account):
    user = await make_account(role=UserRole.USER)
    payload = {
        "bank_name": "Test Bank",
        "holder_name": "John Doe",
        "card_number": "4111-1111-1111-1234",
    }

    first = await client.post("/requisites", json=payload, headers=_auth_headers(user))
    assert first.status_code == 201

    second = await client.post(
        "/requisites",
        json={**payload, "card_number": "4111 1111 1111 1234"},
        headers=_auth_headers(user),
    )
    assert second.status_code == 409


async def test_invalid_card_number_rejected(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/requisites",
        json={"bank_name": "B", "holder_name": "H", "card_number": "not-a-card"},
        headers=_auth_headers(user),
    )

    assert response.status_code == 422


async def test_requisite_limit_enforced(client, make_account):
    user = await make_account(role=UserRole.USER)

    for i in range(app_settings.MAX_ACTIVE_REQUISITES_PER_USER):
        response = await client.post(
            "/requisites",
            json={
                "bank_name": "Test Bank",
                "holder_name": "John Doe",
                "card_number": f"41111111{i:08d}",
            },
            headers=_auth_headers(user),
        )
        assert response.status_code == 201

    over_limit = await client.post(
        "/requisites",
        json={
            "bank_name": "Test Bank",
            "holder_name": "John Doe",
            "card_number": "4222222222222222",
        },
        headers=_auth_headers(user),
    )
    assert over_limit.status_code == 409


# ---- LIST / GET -----------------------------------------------------------


async def test_user_lists_own_cards(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    await make_requisite(user, card_number="4111111111111111")
    await make_requisite(user, card_number="4222222222222222")

    response = await client.get("/requisites", headers=_auth_headers(user))

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_user_cannot_access_another_users_card(client, make_account, make_requisite):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user_a)

    response = await client.get(f"/requisites/{requisite.id}", headers=_auth_headers(user_b))

    assert response.status_code == 404


async def test_get_nonexistent_requisite_returns_404(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get(f"/requisites/{uuid.uuid4()}", headers=_auth_headers(user))

    assert response.status_code == 404


# ---- UPDATE -----------------------------------------------------------


async def test_update_requisite_metadata(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user)

    response = await client.patch(
        f"/requisites/{requisite.id}",
        json={"bank_name": "New Bank", "holder_name": "New Holder"},
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bank_name"] == "New Bank"
    assert body["holder_name"] == "New Holder"


async def test_card_number_is_immutable(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user, card_number="4111111111111111")

    response = await client.patch(
        f"/requisites/{requisite.id}",
        json={"card_number": "9999999999999999", "bank_name": "New Bank"},
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["masked_card_number"] == "**** **** **** 1111"


# ---- ACTIVATE / DEACTIVATE / ARCHIVE ------------------------------------


async def test_deactivate_and_activate_requisite(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user)

    deactivate_resp = await client.post(
        f"/requisites/{requisite.id}/deactivate", headers=_auth_headers(user)
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["is_active"] is False

    activate_resp = await client.post(
        f"/requisites/{requisite.id}/activate", headers=_auth_headers(user)
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["is_active"] is True


async def test_archive_requisite(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user)

    response = await client.post(f"/requisites/{requisite.id}/archive", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["is_archived"] is True
    assert body["is_active"] is False


async def test_archived_requisite_cannot_be_activated(client, make_account, make_requisite):
    user = await make_account(role=UserRole.USER)
    requisite = await make_requisite(user)
    await client.post(f"/requisites/{requisite.id}/archive", headers=_auth_headers(user))

    response = await client.post(
        f"/requisites/{requisite.id}/activate", headers=_auth_headers(user)
    )

    assert response.status_code == 409


def test_no_hard_delete_route_exists():
    from app.main import app as fastapi_app

    schema = fastapi_app.openapi()
    for path, methods in schema["paths"].items():
        if "requisite" in path:
            assert "delete" not in methods


# ---- OWNER READ -----------------------------------------------------------


async def test_owner_reads_user_requisites(client, make_account, make_requisite):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_requisite(user)

    response = await client.get(
        f"/owner/accounts/{user.id}/requisites", headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert "card_number" not in body[0]
    assert body[0]["masked_card_number"].startswith("****")


async def test_owner_requisites_view_rejected_for_user(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.get(
        f"/owner/accounts/{user.id}/requisites", headers=_auth_headers(user)
    )

    assert response.status_code == 403


async def test_owner_requisites_view_rejected_for_merchant(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get(
        f"/owner/accounts/{merchant.id}/requisites", headers=_auth_headers(merchant)
    )

    assert response.status_code == 403


async def test_owner_requisites_for_merchant_target_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get(
        f"/owner/accounts/{merchant.id}/requisites", headers=_auth_headers(owner)
    )

    assert response.status_code == 404
