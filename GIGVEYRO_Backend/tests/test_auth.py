from app.core.security import TokenType, create_access_token, create_refresh_token, decode_token
from app.enums.account import UserRole


async def _login(client, account, password: str) -> dict:
    response = await client.post(
        "/auth/login", json={"username": account.username, "password": password}
    )
    assert response.status_code == 200
    return response.json()


async def test_login_with_correct_credentials_returns_tokens(client, make_account):
    account = await make_account(password="CorrectPassword123")

    response = await client.post(
        "/auth/login", json={"username": account.username, "password": "CorrectPassword123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert "refresh_token" in body
    assert "access_expires_in" in body
    assert "password_hash" not in response.text


async def test_login_with_wrong_password_returns_401(client, make_account):
    account = await make_account(password="CorrectPassword123")

    response = await client.post(
        "/auth/login", json={"username": account.username, "password": "WrongPassword123"}
    )

    assert response.status_code == 401


async def test_login_with_unknown_username_returns_401(client):
    response = await client.post(
        "/auth/login", json={"username": "no-such-user", "password": "WhateverPassword123"}
    )

    assert response.status_code == 401


async def test_login_messages_do_not_distinguish_unknown_user_from_wrong_password(
    client, make_account
):
    account = await make_account(password="CorrectPassword123")

    wrong_password_response = await client.post(
        "/auth/login", json={"username": account.username, "password": "WrongPassword123"}
    )
    unknown_user_response = await client.post(
        "/auth/login", json={"username": "no-such-user", "password": "WhateverPassword123"}
    )

    assert wrong_password_response.status_code == unknown_user_response.status_code == 401
    assert wrong_password_response.json()["detail"] == unknown_user_response.json()["detail"]


async def test_login_with_inactive_account_returns_401(client, make_account):
    account = await make_account(password="CorrectPassword123", is_active=False)

    response = await client.post(
        "/auth/login", json={"username": account.username, "password": "CorrectPassword123"}
    )

    assert response.status_code == 401


async def test_login_creates_server_side_session(client, make_account, db_session):
    from sqlalchemy import select

    from app.models.auth_session import AuthSession

    account = await make_account(password="CorrectPassword123")
    body = await _login(client, account, "CorrectPassword123")

    payload = decode_token(body["refresh_token"], TokenType.REFRESH)
    result = await db_session.execute(
        select(AuthSession).where(AuthSession.id == payload["session_id"])
    )
    session = result.scalar_one()
    assert session.account_id == account.id
    assert session.revoked_at is None
    assert session.refresh_token_hash != body["refresh_token"]


async def test_me_without_token_returns_401(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_with_valid_access_token_returns_account(client, make_account):
    account = await make_account(password="CorrectPassword123", role=UserRole.OWNER)
    token = create_access_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(account.id)
    assert body["username"] == account.username
    assert "password_hash" not in body


async def test_me_with_invalid_token_returns_401(client):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_me_with_refresh_token_returns_401(client, make_account):
    account = await make_account(password="CorrectPassword123")
    token = create_refresh_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_me_with_inactive_account_returns_401(client, make_account):
    account = await make_account(password="CorrectPassword123", is_active=False)
    token = create_access_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_refresh_with_valid_refresh_token_returns_new_tokens(client, make_account):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account, "CorrectPassword123")

    response = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"] != login_body["refresh_token"]


async def test_refresh_with_access_token_returns_401(client, make_account):
    account = await make_account(password="CorrectPassword123")
    access_token = create_access_token(account.id, account.role.value)

    response = await client.post("/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401


async def test_refresh_without_prior_login_returns_401(client, make_account):
    # A hand-crafted refresh token with no server-side session behind it
    # (e.g. minted outside the real login flow) must not be honoured.
    account = await make_account(password="CorrectPassword123")
    refresh_token = create_refresh_token(account.id, account.role.value)

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 401
