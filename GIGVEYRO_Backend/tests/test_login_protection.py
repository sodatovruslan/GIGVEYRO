import asyncio
import uuid

import pytest

from app.enums.account import UserRole
from app.services.login_protection import AccountLoginGuard


@pytest.fixture
def guard():
    return AccountLoginGuard()


def _username() -> str:
    return f"guard_{uuid.uuid4().hex[:10]}"


async def test_not_locked_before_any_failures(guard):
    assert await guard.is_locked(_username()) is None


async def test_locks_after_threshold_failures(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 3)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_BASE_SECONDS", 30)
    username = _username()

    for _ in range(3):
        await guard.record_failure(username)

    locked_for = await guard.is_locked(username)
    assert locked_for is not None
    assert 0 < locked_for <= 30


async def test_not_locked_below_threshold(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 5)
    username = _username()

    for _ in range(4):
        await guard.record_failure(username)

    assert await guard.is_locked(username) is None


async def test_lock_duration_escalates_with_repeated_failures(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 2)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_BASE_SECONDS", 10)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_MAX_SECONDS", 10_000)
    username = _username()

    await guard.record_failure(username)
    first_lock = await guard.is_locked(username)
    assert first_lock is None  # below threshold=2 yet

    await guard.record_failure(username)
    second_lock = await guard.is_locked(username)
    assert second_lock is not None

    await guard.record_failure(username)
    third_lock = await guard.is_locked(username)
    assert third_lock is not None
    # Each additional failure beyond the threshold roughly doubles the lock.
    assert third_lock > second_lock


async def test_lock_duration_is_capped(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 1)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_BASE_SECONDS", 100)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_MAX_SECONDS", 120)
    username = _username()

    for _ in range(6):
        await guard.record_failure(username)

    locked_for = await guard.is_locked(username)
    assert locked_for is not None
    assert locked_for <= 120


async def test_lock_expires_automatically(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 1)
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_BASE_SECONDS", 1)
    username = _username()

    await guard.record_failure(username)
    assert await guard.is_locked(username) is not None

    await asyncio.sleep(1.5)

    assert await guard.is_locked(username) is None


async def test_reset_clears_failures_and_lock(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 2)
    username = _username()

    await guard.record_failure(username)
    await guard.record_failure(username)
    assert await guard.is_locked(username) is not None

    await guard.reset(username)

    assert await guard.is_locked(username) is None
    # The failure counter itself must also be cleared, not just the lock -
    # otherwise a single failure right after reset would immediately
    # re-trigger the lock from residual count.
    await guard.record_failure(username)
    assert await guard.is_locked(username) is None


async def test_different_usernames_are_independent(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 2)
    victim = _username()
    other = _username()

    await guard.record_failure(victim)
    await guard.record_failure(victim)
    assert await guard.is_locked(victim) is not None
    assert await guard.is_locked(other) is None


async def test_concurrent_failures_all_count_towards_the_lock(guard, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 5)
    username = _username()

    await asyncio.gather(*(guard.record_failure(username) for _ in range(5)))

    # All 5 concurrent increments must have been counted atomically - if any
    # were lost to a race, this would still be unlocked.
    assert await guard.is_locked(username) is not None


# ---- HTTP-level integration -----------------------------------------------


async def test_login_locks_account_after_repeated_wrong_passwords(
    client, make_account, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 3)
    account = await make_account(password="CorrectPassword123")

    for _ in range(3):
        response = await client.post(
            "/auth/login",
            json={"username": account.username, "password": "WrongPassword123"},
        )
        assert response.status_code == 401

    locked_response = await client.post(
        "/auth/login",
        json={"username": account.username, "password": "CorrectPassword123"},
    )

    assert locked_response.status_code == 429
    assert "Retry-After" in locked_response.headers


async def test_login_lockout_does_not_reveal_username_existence(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 2)
    ghost_username = f"ghost_{uuid.uuid4().hex[:10]}"

    for _ in range(2):
        response = await client.post(
            "/auth/login",
            json={"username": ghost_username, "password": "WhateverPassword123"},
        )
        assert response.status_code == 401

    locked_response = await client.post(
        "/auth/login",
        json={"username": ghost_username, "password": "WhateverPassword123"},
    )

    assert locked_response.status_code == 429


async def test_successful_login_resets_the_failure_counter(client, make_account, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_LOCK_THRESHOLD", 3)
    # This test issues 6 sequential requests from the same test-client IP -
    # raise the unrelated per-IP limiter's ceiling so only the per-account
    # guard under test can produce a 429 here.
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_REQUESTS", 100)
    account = await make_account(password="CorrectPassword123")

    for _ in range(2):
        response = await client.post(
            "/auth/login",
            json={"username": account.username, "password": "WrongPassword123"},
        )
        assert response.status_code == 401

    success = await client.post(
        "/auth/login",
        json={"username": account.username, "password": "CorrectPassword123"},
    )
    assert success.status_code == 200

    # Two more wrong attempts after a successful login must not immediately
    # relock the account - the earlier near-threshold failures were cleared.
    for _ in range(2):
        response = await client.post(
            "/auth/login",
            json={"username": account.username, "password": "WrongPassword123"},
        )
        assert response.status_code == 401

    still_open = await client.post(
        "/auth/login",
        json={"username": account.username, "password": "CorrectPassword123"},
    )
    assert still_open.status_code == 200


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.USER, UserRole.MERCHANT])
async def test_login_still_works_for_every_role(client, make_account, role):
    account = await make_account(password="CorrectPassword123", role=role)

    response = await client.post(
        "/auth/login",
        json={"username": account.username, "password": "CorrectPassword123"},
    )

    assert response.status_code == 200
