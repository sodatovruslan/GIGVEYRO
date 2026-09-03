from unittest.mock import AsyncMock

import pyotp
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.models.notification import Notification, NotificationOutbox


def _auth_headers(account) -> dict[str, str]:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _secret(response) -> str:  # noqa: ANN001
    return response.json()["manual_key"].replace(" ", "")


async def _enable_two_factor(client, account, password: str) -> tuple[str, list[str]]:  # noqa: ANN001
    start = await client.post(
        "/auth/2fa/setup/start",
        json={"password": password},
        headers=_auth_headers(account),
    )
    assert start.status_code == 200
    secret = _secret(start)
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(account),
    )
    assert confirm.status_code == 200
    return secret, confirm.json()["recovery_codes"]


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MERCHANT])
async def test_optional_two_factor_complete_self_service_lifecycle(client, make_account, role):
    password = "SelfServicePass123"
    account = await make_account(role=role, password=password)

    initial = await client.get("/auth/2fa/status", headers=_auth_headers(account))
    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert initial.json()["required"] is False

    start = await client.post(
        "/auth/2fa/setup/start", json={"password": password}, headers=_auth_headers(account)
    )
    assert start.status_code == 200
    secret = _secret(start)

    invalid_confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": "000000"},
        headers=_auth_headers(account),
    )
    assert invalid_confirm.status_code == 401

    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(account),
    )
    assert confirm.status_code == 200
    old_codes = confirm.json()["recovery_codes"]
    assert len(old_codes) == settings.TWO_FACTOR_RECOVERY_CODE_COUNT

    login = await client.post(
        "/auth/login", json={"username": account.username, "password": password}
    )
    assert login.json()["two_factor_required"] is True
    invalid_verify = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": login.json()["challenge_token"], "code": "000000"},
    )
    assert invalid_verify.status_code == 401
    valid_verify = await client.post(
        "/auth/2fa/verify",
        json={
            "challenge_token": login.json()["challenge_token"],
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert valid_verify.status_code == 200

    regenerated = await client.post(
        "/auth/2fa/recovery/regenerate",
        json={"password": password, "totp_code": old_codes[0]},
        headers=_auth_headers(account),
    )
    assert regenerated.status_code == 200
    new_codes = regenerated.json()["recovery_codes"]
    assert set(new_codes).isdisjoint(old_codes)

    disable = await client.post(
        "/auth/2fa/disable",
        json={"password": password, "code": new_codes[0]},
        headers=_auth_headers(account),
    )
    assert disable.status_code == 204
    final = await client.get("/auth/2fa/status", headers=_auth_headers(account))
    assert final.json()["enabled"] is False


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MERCHANT])
async def test_sessions_are_strictly_self_service(client, make_account, role):
    password = "SessionSafetyPass123"
    account = await make_account(role=role, password=password)
    other = await make_account(role=role, password=password)
    first = await client.post(
        "/auth/login", json={"username": account.username, "password": password}
    )
    second = await client.post(
        "/auth/login", json={"username": account.username, "password": password}
    )
    foreign = await client.post(
        "/auth/login", json={"username": other.username, "password": password}
    )

    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    own_sessions = await client.get("/auth/sessions", headers=headers)
    assert own_sessions.status_code == 200
    assert len(own_sessions.json()["items"]) == 2
    assert sum(item["is_current"] for item in own_sessions.json()["items"]) == 1
    assert "refresh_token" not in own_sessions.text
    assert "ip_address" not in own_sessions.text

    foreign_sessions = await client.get(
        "/auth/sessions", headers={"Authorization": f"Bearer {foreign.json()['access_token']}"}
    )
    foreign_id = foreign_sessions.json()["items"][0]["id"]
    forbidden = await client.delete(f"/auth/sessions/{foreign_id}", headers=headers)
    assert forbidden.status_code == 404

    logout_others = await client.post("/auth/logout-all", headers=headers)
    assert logout_others.status_code == 200
    assert logout_others.json()["revoked_count"] == 1
    assert (await client.get("/auth/sessions", headers=headers)).status_code == 200
    assert (
        await client.post(
            "/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
        )
    ).status_code == 401


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MERCHANT])
async def test_password_change_preserves_two_factor_and_revokes_other_sessions(
    client, make_account, db_session, monkeypatch, role
):
    old_password = "OldSecurityPass123"
    new_password = "NewSecurityPass123"
    account = await make_account(role=role, password=old_password)
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    preference = await client.patch(
        "/notifications/preferences",
        json={"telegram_enabled": True},
        headers=_auth_headers(account),
    )
    assert preference.status_code == 200
    secret, recovery_codes = await _enable_two_factor(client, account, old_password)

    async def login_with_two_factor() -> dict:
        login = await client.post(
            "/auth/login", json={"username": account.username, "password": old_password}
        )
        verified = await client.post(
            "/auth/2fa/verify",
            json={
                "challenge_token": login.json()["challenge_token"],
                "code": pyotp.TOTP(secret).now(),
            },
        )
        assert verified.status_code == 200
        return verified.json()

    current = await login_with_two_factor()
    other = await login_with_two_factor()
    changed = await client.post(
        "/auth/password/change",
        json={
            "current_password": old_password,
            "new_password": new_password,
            "code": recovery_codes[0],
        },
        headers={"Authorization": f"Bearer {current['access_token']}"},
    )
    assert changed.status_code == 204
    assert (
        await client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/auth/refresh", json={"refresh_token": current["refresh_token"]})
    ).status_code == 200

    old_login = await client.post(
        "/auth/login", json={"username": account.username, "password": old_password}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/auth/login", json={"username": account.username, "password": new_password}
    )
    assert new_login.status_code == 200
    assert new_login.json()["two_factor_required"] is True

    status_response = await client.get(
        "/auth/2fa/status", headers={"Authorization": f"Bearer {current['access_token']}"}
    )
    assert status_response.json()["enabled"] is True

    result = await db_session.execute(
        select(Notification).where(
            Notification.account_id == account.id,
            Notification.type == NotificationType.SECURITY_EVENT,
        )
    )
    messages = " ".join(f"{item.title} {item.message}" for item in result.scalars().all())
    assert old_password not in messages
    assert new_password not in messages
    assert recovery_codes[0] not in messages
    assert secret not in messages
    outboxes = (
        await db_session.execute(
            select(NotificationOutbox).where(NotificationOutbox.account_id == account.id)
        )
    ).scalars().all()
    assert outboxes
    outbox_text = " ".join(f"{item.title} {item.message}" for item in outboxes)
    assert old_password not in outbox_text
    assert new_password not in outbox_text
    assert recovery_codes[0] not in outbox_text
    assert secret not in outbox_text


async def test_owner_required_policy_cannot_be_disabled(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", False)
    owner = await make_account(role=UserRole.OWNER, password="OwnerSecurityPass123")
    secret, _ = await _enable_two_factor(client, owner, "OwnerSecurityPass123")
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)

    status_response = await client.get("/auth/2fa/status", headers=_auth_headers(owner))
    assert status_response.json()["required"] is True
    disable = await client.post(
        "/auth/2fa/disable",
        json={
            "password": "OwnerSecurityPass123",
            "code": pyotp.TOTP(secret).now(),
        },
        headers=_auth_headers(owner),
    )
    assert disable.status_code == 409


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.USER, UserRole.MERCHANT])
async def test_blocked_account_cannot_use_security_endpoints(client, make_account, role):
    account = await make_account(role=role, password="BlockedSecurityPass123", is_active=False)
    for method, path, payload in (
        ("GET", "/auth/2fa/status", None),
        ("GET", "/auth/sessions", None),
        ("POST", "/auth/2fa/setup/start", {"password": "BlockedSecurityPass123"}),
        (
            "POST",
            "/auth/password/change",
            {
                "current_password": "BlockedSecurityPass123",
                "new_password": "BlockedSecurityPass456",
            },
        ),
    ):
        response = await client.request(method, path, json=payload, headers=_auth_headers(account))
        assert response.status_code == 401


async def test_sensitive_security_mutations_are_rate_limited(client, make_account, monkeypatch):
    account = await make_account(role=UserRole.USER, password="RateLimitedPass123")
    limited = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.auth._two_factor_rate_limiter.is_rate_limited",
        limited,
    )
    for path, payload in (
        ("/auth/2fa/setup/start", {"password": "RateLimitedPass123"}),
        ("/auth/2fa/setup/confirm", {"totp_code": "123456"}),
        (
            "/auth/2fa/disable",
            {"password": "RateLimitedPass123", "code": "123456"},
        ),
        (
            "/auth/2fa/recovery/regenerate",
            {"password": "RateLimitedPass123", "totp_code": "123456"},
        ),
        (
            "/auth/password/change",
            {
                "current_password": "RateLimitedPass123",
                "new_password": "RateLimitedPass456",
            },
        ),
    ):
        response = await client.post(path, json=payload, headers=_auth_headers(account))
        assert response.status_code == 429
    assert limited.await_count == 5
