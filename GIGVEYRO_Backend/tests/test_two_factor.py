import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import delete, select

from app.core.security import create_access_token, hash_password
from app.core.totp_crypto import encrypt_totp_secret
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.two_factor import AccountTwoFactor, TwoFactorChallenge, TwoFactorRecoveryCode
from app.repositories.account import AccountRepository
from app.repositories.two_factor import (
    AccountTwoFactorRepository,
    PendingTwoFactorSetupRepository,
    TwoFactorChallengeRepository,
    TwoFactorRecoveryCodeRepository,
)
from app.services.two_factor import ChallengeInvalidError, TwoFactorService


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _secret_from_manual_key(manual_key: str) -> str:
    return manual_key.replace(" ", "")


async def _start_and_confirm_setup(
    client, owner, password: str = "OwnerPass123"
) -> tuple[str, list[str]]:
    start = await client.post(
        "/auth/2fa/setup/start", json={"password": password}, headers=_auth_headers(owner)
    )
    assert start.status_code == 200
    secret = _secret_from_manual_key(start.json()["manual_key"])

    code = pyotp.TOTP(secret).now()
    confirm = await client.post(
        "/auth/2fa/setup/confirm", json={"totp_code": code}, headers=_auth_headers(owner)
    )
    assert confirm.status_code == 200
    return secret, confirm.json()["recovery_codes"]


# ---- setup -------------------------------------------------------------


async def test_setup_start_requires_authentication(client):
    response = await client.post("/auth/2fa/setup/start", json={"password": "whatever"})
    assert response.status_code == 401


async def test_setup_start_supports_user_self_service(client, make_account):
    user = await make_account(role=UserRole.USER, password="UserPass123")
    response = await client.post(
        "/auth/2fa/setup/start", json={"password": "UserPass123"}, headers=_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json()["manual_key"]


async def test_setup_start_rejects_wrong_password(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    response = await client.post(
        "/auth/2fa/setup/start", json={"password": "WrongPassword123"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 401


async def test_setup_start_returns_otpauth_uri_and_manual_key(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    response = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "GIGVEYRO" in body["otpauth_uri"]
    assert body["manual_key"]


async def test_setup_confirm_rejects_wrong_code(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    response = await client.post(
        "/auth/2fa/setup/confirm", json={"totp_code": "000000"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 401


async def test_setup_confirm_enables_and_returns_recovery_codes(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    _, recovery_codes = await _start_and_confirm_setup(client, owner)
    assert len(recovery_codes) == 10
    assert len(set(recovery_codes)) == 10


async def test_setup_confirm_rejects_expired_pending(client, make_account, db_session):
    from app.models.two_factor import PendingTwoFactorSetup

    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    start = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    assert start.status_code == 200

    result = await db_session.execute(
        select(PendingTwoFactorSetup).where(PendingTwoFactorSetup.account_id == owner.id)
    )
    pending = result.scalar_one()
    pending.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()

    secret = _secret_from_manual_key(start.json()["manual_key"])
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert confirm.status_code == 410


async def test_setup_start_rejects_when_already_enabled(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 409


async def test_totp_secret_is_encrypted_at_rest(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    result = await db_session.execute(
        select(AccountTwoFactor).where(AccountTwoFactor.account_id == owner.id)
    )
    record = result.scalar_one()
    assert secret not in record.encrypted_secret
    assert record.encrypted_secret.startswith("1:")


async def test_recovery_codes_are_hashed_at_rest(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    _, recovery_codes = await _start_and_confirm_setup(client, owner)

    result = await db_session.execute(
        select(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.account_id == owner.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 10
    stored_hashes = {row.code_hash for row in rows}
    for code in recovery_codes:
        assert code not in stored_hashes
    for row in rows:
        assert len(row.code_hash) == 64


# ---- login challenge -----------------------------------------------------


async def test_login_without_two_factor_returns_tokens_directly(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    response = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_login_with_two_factor_returns_challenge(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["two_factor_required"] is True
    assert "challenge_token" in body
    assert "access_token" not in body


async def test_challenge_token_cannot_access_protected_endpoints(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {challenge_token}"})
    assert response.status_code == 401

    realtime = await client.post(
        "/api/v1/realtime/ticket",
        headers={"Authorization": f"Bearer {challenge_token}"},
    )
    assert realtime.status_code == 401


async def test_valid_totp_verify_creates_session(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    response = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body

    realtime = await client.post(
        "/api/v1/realtime/ticket",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert realtime.status_code == 200


async def test_wrong_totp_verify_rejected(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    response = await client.post(
        "/auth/2fa/verify", json={"challenge_token": challenge_token, "code": "000000"}
    )
    assert response.status_code == 401


async def test_expired_challenge_rejected(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    result = await db_session.execute(
        select(TwoFactorChallenge).where(TwoFactorChallenge.account_id == owner.id)
    )
    challenge = result.scalars().first()
    challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    response = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 410


async def test_challenge_replay_rejected(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    first = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
    )
    assert first.status_code == 200

    replay = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
    )
    assert replay.status_code == 410


# ---- recovery codes --------------------------------------------------------


async def test_recovery_code_login_succeeds(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    _, recovery_codes = await _start_and_confirm_setup(client, owner)

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    challenge_token = login.json()["challenge_token"]

    response = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": recovery_codes[0]},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_used_recovery_code_cannot_be_reused(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    _, recovery_codes = await _start_and_confirm_setup(client, owner)

    async def _attempt_login_with_code(code: str):
        login = await client.post(
            "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
        )
        return await client.post(
            "/auth/2fa/verify",
            json={"challenge_token": login.json()["challenge_token"], "code": code},
        )

    first = await _attempt_login_with_code(recovery_codes[0])
    assert first.status_code == 200

    second = await _attempt_login_with_code(recovery_codes[0])
    assert second.status_code == 401


async def test_regenerate_recovery_codes_invalidates_old(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, old_codes = await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/2fa/recovery/regenerate",
        json={"password": "OwnerPass123", "totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    new_codes = response.json()["recovery_codes"]
    assert set(new_codes).isdisjoint(set(old_codes))

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    old_code_attempt = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": login.json()["challenge_token"], "code": old_codes[0]},
    )
    assert old_code_attempt.status_code == 401


# ---- disable ----------------------------------------------------------------


async def test_disable_rejects_wrong_password(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/2fa/disable",
        json={"password": "WrongPassword123", "code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 401


async def test_disable_rejects_wrong_code(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/2fa/disable",
        json={"password": "OwnerPass123", "code": "000000"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 401


async def test_disable_succeeds_and_revokes_recovery_codes(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    response = await client.post(
        "/auth/2fa/disable",
        json={"password": "OwnerPass123", "code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 204

    result = await db_session.execute(
        select(AccountTwoFactor).where(AccountTwoFactor.account_id == owner.id)
    )
    assert result.scalar_one_or_none() is None

    result = await db_session.execute(
        select(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.account_id == owner.id)
    )
    assert result.scalars().all() == []

    # Login should no longer require 2FA.
    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert "access_token" in login.json()


# ---- session revocation on enable/disable -----------------------------------


async def test_enabling_two_factor_revokes_other_sessions(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    other_login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    other_refresh_token = other_login.json()["refresh_token"]

    current_login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    current_access_token = current_login.json()["access_token"]
    current_headers = {"Authorization": f"Bearer {current_access_token}"}

    start = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=current_headers
    )
    secret = _secret_from_manual_key(start.json()["manual_key"])
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=current_headers,
    )
    assert confirm.status_code == 200

    # The session used to perform the enable call is unaffected...
    me = await client.get("/auth/me", headers=current_headers)
    assert me.status_code == 200

    # ...but the other, pre-existing session's refresh token is revoked.
    refreshed = await client.post("/auth/refresh", json={"refresh_token": other_refresh_token})
    assert refreshed.status_code == 401


# ---- security: no secret leakage --------------------------------------------


async def test_status_endpoint_never_returns_secret(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    secret, _ = await _start_and_confirm_setup(client, owner)

    response = await client.get("/auth/2fa/status", headers=_auth_headers(owner))
    assert response.status_code == 200
    assert secret not in response.text
    assert "encrypted_secret" not in response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["recovery_codes_remaining"] == 10


async def test_disabled_status_reports_correctly(client, make_account):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    response = await client.get("/auth/2fa/status", headers=_auth_headers(owner))
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "required": False,
        "enabled_at": None,
        "recovery_codes_remaining": 0,
    }


# ---- concurrency --------------------------------------------------------


async def test_concurrent_challenge_verify_exactly_one_wins():
    """Two simultaneous verify attempts with the same valid TOTP code on the
    same challenge, each on its own real DB connection/transaction - mirrors
    the refresh-rotation concurrency test in test_auth_sessions.py.
    """
    async with AsyncSessionLocal() as setup_session:
        account = Account(
            username=f"conc_2fa_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.OWNER,
            full_name="Concurrency 2FA Test",
            is_active=True,
        )
        await AccountRepository(setup_session).create(account)

        secret = pyotp.random_base32()
        two_factor_repo = AccountTwoFactorRepository(setup_session)
        await two_factor_repo.create(
            AccountTwoFactor(
                account_id=account.id,
                method="totp",
                encrypted_secret=encrypt_totp_secret(secret),
            )
        )

        challenge_repo = TwoFactorChallengeRepository(setup_session)
        challenge = await challenge_repo.create(
            TwoFactorChallenge(
                account_id=account.id,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await setup_session.commit()
        account_id = account.id
        challenge_id = challenge.id

    code = pyotp.TOTP(secret).now()
    results: list[str] = []

    async def attempt_verify() -> None:
        async with AsyncSessionLocal() as session:
            service = TwoFactorService(
                AccountTwoFactorRepository(session),
                PendingTwoFactorSetupRepository(session),
                TwoFactorRecoveryCodeRepository(session),
                TwoFactorChallengeRepository(session),
            )
            account_repo = AccountRepository(session)
            fresh_account = await account_repo.get_by_id(account_id)
            try:
                await service.verify_challenge(challenge_id, fresh_account, code)
                await session.commit()
                results.append("success")
            except ChallengeInvalidError:
                await session.commit()
                results.append("invalid")

    try:
        await asyncio.gather(attempt_verify(), attempt_verify())

        assert results.count("success") == 1
        assert results.count("invalid") == 1
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(TwoFactorChallenge).where(TwoFactorChallenge.account_id == account_id)
            )
            await cleanup_session.execute(
                delete(AccountTwoFactor).where(AccountTwoFactor.account_id == account_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == account_id))
            await cleanup_session.commit()
