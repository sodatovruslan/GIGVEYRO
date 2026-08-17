import uuid

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.repositories.account import AccountRepository


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


# ---- RBAC ----------------------------------------------------------------


async def test_owner_endpoints_require_authentication(client):
    response = await client.get("/owner/accounts")
    assert response.status_code == 401


async def test_create_account_rejects_user_role(client, make_account):
    user = await make_account(role=UserRole.USER)

    response = await client.post(
        "/owner/accounts",
        json={
            "username": f"new_{uuid.uuid4().hex[:8]}",
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "New Person",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 403


async def test_list_accounts_rejects_merchant_role(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.get("/owner/accounts", headers=_auth_headers(merchant))

    assert response.status_code == 403


async def test_owner_can_access_list(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get("/owner/accounts", headers=_auth_headers(owner))

    assert response.status_code == 200


# ---- CREATE ---------------------------------------------------------------


async def test_owner_creates_user_account(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newuser_{uuid.uuid4().hex[:8]}"

    response = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "New User",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == username
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "password" not in response.text
    assert "password_hash" not in response.text


async def test_owner_creates_merchant_account(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newmerchant_{uuid.uuid4().hex[:8]}"

    response = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "merchant",
            "full_name": "New Merchant",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 201
    assert response.json()["role"] == "merchant"


async def test_owner_cannot_create_owner_account(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        "/owner/accounts",
        json={
            "username": f"sneaky_{uuid.uuid4().hex[:8]}",
            "password": "NewAccountPass123",
            "role": "owner",
            "full_name": "Sneaky Owner",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422


async def test_create_account_stores_hashed_password(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER)
    username = f"newuser_{uuid.uuid4().hex[:8]}"

    response = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "New User",
        },
        headers=_auth_headers(owner),
    )
    account_id = uuid.UUID(response.json()["id"])

    stored = await AccountRepository(db_session).get_by_id(account_id)
    assert stored.password_hash != "NewAccountPass123"


async def test_create_account_duplicate_username_returns_409(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    existing = await make_account(role=UserRole.USER)

    response = await client.post(
        "/owner/accounts",
        json={
            "username": existing.username,
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "Someone Else",
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


async def test_create_account_duplicate_email_returns_409(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    await make_account(role=UserRole.USER, email=email)

    response = await client.post(
        "/owner/accounts",
        json={
            "username": f"new_{uuid.uuid4().hex[:8]}",
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "Someone Else",
            "email": email,
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


async def test_create_account_duplicate_phone_returns_409(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    await make_account(role=UserRole.USER, phone=phone)

    response = await client.post(
        "/owner/accounts",
        json={
            "username": f"new_{uuid.uuid4().hex[:8]}",
            "password": "NewAccountPass123",
            "role": "user",
            "full_name": "Someone Else",
            "phone": phone,
        },
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409


# ---- LIST / FILTER / SEARCH ------------------------------------------------


async def test_list_accounts_pagination(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    for i in range(3):
        await make_account(role=UserRole.USER, full_name=f"Pager {tag} {i}")

    response = await client.get(
        "/owner/accounts",
        params={"search": tag, "limit": 2, "offset": 0},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


async def test_list_accounts_filters_by_role(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    await make_account(role=UserRole.USER, full_name=f"RoleFilter {tag}")
    await make_account(role=UserRole.MERCHANT, full_name=f"RoleFilter {tag}")

    response = await client.get(
        "/owner/accounts",
        params={"search": tag, "role": "merchant"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["role"] == "merchant"


async def test_list_accounts_filters_by_is_active(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    await make_account(role=UserRole.USER, full_name=f"ActiveFilter {tag}", is_active=True)
    await make_account(role=UserRole.USER, full_name=f"ActiveFilter {tag}", is_active=False)

    response = await client.get(
        "/owner/accounts",
        params={"search": tag, "is_active": "false"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["is_active"] is False


async def test_list_accounts_search_by_username(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    target = await make_account(role=UserRole.USER, username=f"findme_{tag}")

    response = await client.get(
        "/owner/accounts", params={"search": f"findme_{tag}"}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_list_accounts_search_by_full_name(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    target = await make_account(role=UserRole.USER, full_name=f"Findable Person {tag}")

    response = await client.get(
        "/owner/accounts", params={"search": tag}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_list_accounts_never_exposes_password_hash(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    tag = uuid.uuid4().hex[:8]
    await make_account(role=UserRole.USER, full_name=f"NoLeak {tag}")

    response = await client.get(
        "/owner/accounts", params={"search": tag}, headers=_auth_headers(owner)
    )

    assert "password_hash" not in response.text


async def test_list_accounts_never_includes_owner_role(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get("/owner/accounts", headers=_auth_headers(owner))

    assert response.status_code == 200
    roles = {item["role"] for item in response.json()["items"]}
    assert "owner" not in roles


# ---- GET --------------------------------------------------------------


async def test_get_account_by_id(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER)

    response = await client.get(f"/owner/accounts/{target.id}", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["id"] == str(target.id)


async def test_get_nonexistent_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.get(f"/owner/accounts/{uuid.uuid4()}", headers=_auth_headers(owner))

    assert response.status_code == 404


async def test_get_owner_account_via_managed_endpoint_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    other_owner = await make_account(role=UserRole.OWNER)

    response = await client.get(f"/owner/accounts/{other_owner.id}", headers=_auth_headers(owner))

    assert response.status_code == 404


# ---- UPDATE -----------------------------------------------------------


async def test_update_account_full_name(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER)

    response = await client.patch(
        f"/owner/accounts/{target.id}",
        json={"full_name": "Updated Name"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Updated Name"


async def test_update_account_email(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER)
    new_email = f"updated_{uuid.uuid4().hex[:8]}@example.com"

    response = await client.patch(
        f"/owner/accounts/{target.id}", json={"email": new_email}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    assert response.json()["email"] == new_email


async def test_update_account_phone(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER)
    new_phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"

    response = await client.patch(
        f"/owner/accounts/{target.id}", json={"phone": new_phone}, headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    assert response.json()["phone"] == new_phone


async def test_update_account_duplicate_email_returns_409(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    email = f"taken_{uuid.uuid4().hex[:8]}@example.com"
    await make_account(role=UserRole.USER, email=email)
    target = await make_account(role=UserRole.USER)

    response = await client.patch(
        f"/owner/accounts/{target.id}", json={"email": email}, headers=_auth_headers(owner)
    )

    assert response.status_code == 409


async def test_update_nonexistent_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)

    response = await client.patch(
        f"/owner/accounts/{uuid.uuid4()}",
        json={"full_name": "Nobody"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404


async def test_update_owner_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    other_owner = await make_account(role=UserRole.OWNER)

    response = await client.patch(
        f"/owner/accounts/{other_owner.id}",
        json={"full_name": "Hacked Owner"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404


async def test_update_cannot_change_role(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER)

    response = await client.patch(
        f"/owner/accounts/{target.id}", json={"role": "merchant"}, headers=_auth_headers(owner)
    )

    # "role" is not a field on OwnerAccountUpdate, so it is ignored rather
    # than applied - the account keeps its original role.
    assert response.status_code == 200
    assert response.json()["role"] == "user"


# ---- BLOCK / UNBLOCK ----------------------------------------------------


async def test_block_user_prevents_login_and_invalidates_access(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER, password="OriginalPass123")
    target_token = create_access_token(target.id, target.role.value)

    block_response = await client.post(
        f"/owner/accounts/{target.id}/block", headers=_auth_headers(owner)
    )
    assert block_response.status_code == 200
    assert block_response.json()["is_active"] is False

    login_response = await client.post(
        "/auth/login", json={"username": target.username, "password": "OriginalPass123"}
    )
    assert login_response.status_code == 401

    me_response = await client.get("/auth/me", headers={"Authorization": f"Bearer {target_token}"})
    assert me_response.status_code == 401


async def test_unblock_user_restores_login(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER, password="OriginalPass123", is_active=False)

    unblock_response = await client.post(
        f"/owner/accounts/{target.id}/unblock", headers=_auth_headers(owner)
    )
    assert unblock_response.status_code == 200
    assert unblock_response.json()["is_active"] is True

    login_response = await client.post(
        "/auth/login", json={"username": target.username, "password": "OriginalPass123"}
    )
    assert login_response.status_code == 200


async def test_block_merchant_prevents_login(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.MERCHANT, password="OriginalPass123")

    await client.post(f"/owner/accounts/{target.id}/block", headers=_auth_headers(owner))

    login_response = await client.post(
        "/auth/login", json={"username": target.username, "password": "OriginalPass123"}
    )
    assert login_response.status_code == 401


async def test_block_owner_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    other_owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        f"/owner/accounts/{other_owner.id}/block", headers=_auth_headers(owner)
    )

    assert response.status_code == 404


# ---- PASSWORD RESET -----------------------------------------------------


async def test_reset_password_changes_login(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    target = await make_account(role=UserRole.USER, password="OldPassword123")

    reset_response = await client.post(
        f"/owner/accounts/{target.id}/reset-password",
        json={"new_password": "BrandNewPassword123"},
        headers=_auth_headers(owner),
    )
    assert reset_response.status_code == 204

    old_login = await client.post(
        "/auth/login", json={"username": target.username, "password": "OldPassword123"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/auth/login", json={"username": target.username, "password": "BrandNewPassword123"}
    )
    assert new_login.status_code == 200


async def test_reset_password_owner_account_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    other_owner = await make_account(role=UserRole.OWNER)

    response = await client.post(
        f"/owner/accounts/{other_owner.id}/reset-password",
        json={"new_password": "BrandNewPassword123"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 404
