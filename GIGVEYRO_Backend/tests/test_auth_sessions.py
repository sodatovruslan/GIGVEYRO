import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
)
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.auth_session import AuthSession
from app.repositories.account import AccountRepository
from app.repositories.auth_session import AuthSessionRepository
from app.services.auth import AuthenticationError, AuthService, TokenReuseError


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _login(client, account, password: str = "CorrectPassword123") -> dict:
    response = await client.post(
        "/auth/login", json={"username": account.username, "password": password}
    )
    assert response.status_code == 200
    return response.json()


# ---- rotation --------------------------------------------------------------


async def test_refresh_rotates_and_rejects_old_token(client, make_account):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)

    first_refresh = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert first_refresh.status_code == 200

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 409


async def test_reuse_detection_revokes_session(client, make_account, db_session):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)

    rotated = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert rotated.status_code == 200

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 409

    # The whole family is revoked as a reaction, so even the token issued by
    # the legitimate rotation above is now rejected too.
    followup = await client.post(
        "/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert followup.status_code == 401


async def test_expired_session_rejected(client, make_account, make_auth_session):
    account = await make_account(password="CorrectPassword123")
    token = uuid.uuid4().hex
    session = await make_auth_session(account, refresh_token=token, expires_in_days=-1)
    refresh_token = create_refresh_token(account.id, account.role.value, session.id)

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


async def test_blocked_account_refresh_rejected(client, make_account, db_session):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)

    account.is_active = False
    await db_session.flush()

    response = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert response.status_code == 401


# ---- logout / logout-all ---------------------------------------------------


async def test_logout_revokes_session(client, make_account, db_session):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)

    response = await client.post(
        "/auth/logout", json={"refresh_token": login_body["refresh_token"]}
    )
    assert response.status_code == 204

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_logout_is_idempotent(client, make_account):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)

    first = await client.post("/auth/logout", json={"refresh_token": login_body["refresh_token"]})
    second = await client.post("/auth/logout", json={"refresh_token": login_body["refresh_token"]})
    assert first.status_code == second.status_code == 204


async def test_logout_all_revokes_every_session(client, make_account):
    account = await make_account(password="CorrectPassword123")
    first_login = await _login(client, account)
    second_login = await _login(client, account)

    response = await client.post("/auth/logout-all", headers=_auth_headers(account))
    assert response.status_code == 200
    assert response.json()["revoked_count"] == 2

    for body in (first_login, second_login):
        replay = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
        assert replay.status_code == 401


# ---- session listing / revoke-one -----------------------------------------


async def test_list_sessions_returns_own_sessions_only(client, make_account):
    account = await make_account(password="CorrectPassword123")
    other = await make_account(password="CorrectPassword123")
    await _login(client, account)
    await _login(client, other)

    response = await client.get("/auth/sessions", headers=_auth_headers(account))
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    for field in ("refresh_token_hash", "refresh_token", "token"):
        assert field not in response.text


async def test_cannot_revoke_foreign_session(client, make_account):
    account = await make_account(password="CorrectPassword123")
    other = await make_account(password="CorrectPassword123")
    await _login(client, account)
    other_login = await _login(client, other)

    other_session_id = decode_token(other_login["refresh_token"], TokenType.REFRESH)["session_id"]

    response = await client.delete(
        f"/auth/sessions/{other_session_id}", headers=_auth_headers(account)
    )
    assert response.status_code == 404


async def test_revoke_own_session(client, make_account):
    account = await make_account(password="CorrectPassword123")
    login_body = await _login(client, account)
    session_id = decode_token(login_body["refresh_token"], TokenType.REFRESH)["session_id"]

    response = await client.delete(f"/auth/sessions/{session_id}", headers=_auth_headers(account))
    assert response.status_code == 204

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 401


# ---- password reset / block integration ------------------------------------


async def test_password_reset_revokes_sessions(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    target = await make_account(password="CorrectPassword123")
    login_body = await _login(client, target)

    response = await client.post(
        f"/owner/accounts/{target.id}/reset-password",
        json={"new_password": "BrandNewPassword123"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 204

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_block_revokes_sessions(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    target = await make_account(password="CorrectPassword123")
    login_body = await _login(client, target)

    response = await client.post(
        f"/owner/accounts/{target.id}/block", headers=_auth_headers(owner)
    )
    assert response.status_code == 200

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
    )
    assert replay.status_code == 401


# ---- storage hygiene --------------------------------------------------------


async def test_refresh_token_never_stored_as_plaintext(db_session, make_account):
    account = await make_account(password="CorrectPassword123")
    plaintext = "not-a-real-token-value"
    session = AuthSession(
        account_id=account.id,
        refresh_token_hash=hash_refresh_token(plaintext),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(session)
    await db_session.flush()

    result = await db_session.execute(select(AuthSession).where(AuthSession.id == session.id))
    stored = result.scalar_one()
    assert stored.refresh_token_hash != plaintext
    assert len(stored.refresh_token_hash) == 64


# ---- concurrency -------------------------------------------------------------


async def test_concurrent_refresh_exactly_one_wins_and_reuse_detected():
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        account = Account(
            username=f"conc_auth_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Concurrency Auth Test",
            is_active=True,
        )
        await account_repo.create(account)

        session_repo = AuthSessionRepository(setup_session)
        service = AuthService(account_repo, session_repo)
        token_pair = await service.login(account)
        await setup_session.commit()
        account_id = account.id
        refresh_token = token_pair.refresh_token

    results: list[str] = []

    async def attempt_refresh() -> None:
        async with AsyncSessionLocal() as session:
            service = AuthService(AccountRepository(session), AuthSessionRepository(session))
            try:
                await service.refresh(refresh_token)
                await session.commit()
                results.append("success")
            except TokenReuseError:
                await session.commit()
                results.append("reuse_detected")
            except AuthenticationError:
                await session.rollback()
                results.append("auth_error")

    try:
        await asyncio.gather(attempt_refresh(), attempt_refresh())

        assert results.count("success") == 1
        assert results.count("reuse_detected") == 1
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(AuthSession).where(AuthSession.account_id == account_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == account_id))
            await cleanup_session.commit()
