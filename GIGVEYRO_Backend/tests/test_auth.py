import uuid

from app.core.security import create_access_token, create_refresh_token, hash_password
from app.enums.account import UserRole
from app.models.account import Account


async def _create_account(db_session, *, password: str, is_active: bool = True, role=UserRole.USER):
    account = Account(
        username=f"user_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(password),
        role=role,
        full_name="Test Account",
        is_active=is_active,
    )
    db_session.add(account)
    await db_session.flush()
    await db_session.refresh(account)
    return account


async def test_login_with_correct_credentials_returns_tokens(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123")

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


async def test_login_with_wrong_password_returns_401(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123")

    response = await client.post(
        "/auth/login", json={"username": account.username, "password": "WrongPassword123"}
    )

    assert response.status_code == 401


async def test_login_with_unknown_username_returns_401(client, db_session):
    response = await client.post(
        "/auth/login", json={"username": "no-such-user", "password": "WhateverPassword123"}
    )

    assert response.status_code == 401


async def test_login_messages_do_not_distinguish_unknown_user_from_wrong_password(
    client, db_session
):
    account = await _create_account(db_session, password="CorrectPassword123")

    wrong_password_response = await client.post(
        "/auth/login", json={"username": account.username, "password": "WrongPassword123"}
    )
    unknown_user_response = await client.post(
        "/auth/login", json={"username": "no-such-user", "password": "WhateverPassword123"}
    )

    assert wrong_password_response.status_code == unknown_user_response.status_code == 401
    assert wrong_password_response.json()["detail"] == unknown_user_response.json()["detail"]


async def test_login_with_inactive_account_returns_401(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123", is_active=False)

    response = await client.post(
        "/auth/login", json={"username": account.username, "password": "CorrectPassword123"}
    )

    assert response.status_code == 401


async def test_me_without_token_returns_401(client, db_session):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_with_valid_access_token_returns_account(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123", role=UserRole.OWNER)
    token = create_access_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(account.id)
    assert body["username"] == account.username
    assert "password_hash" not in body


async def test_me_with_invalid_token_returns_401(client, db_session):
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_me_with_refresh_token_returns_401(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123")
    token = create_refresh_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_me_with_inactive_account_returns_401(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123", is_active=False)
    token = create_access_token(account.id, account.role.value)

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_refresh_with_valid_refresh_token_returns_new_tokens(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123")
    refresh_token = create_refresh_token(account.id, account.role.value)

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body


async def test_refresh_with_access_token_returns_401(client, db_session):
    account = await _create_account(db_session, password="CorrectPassword123")
    access_token = create_access_token(account.id, account.role.value)

    response = await client.post("/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401
