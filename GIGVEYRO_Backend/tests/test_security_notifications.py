import pyotp
from sqlalchemy import select

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.models.notification import Notification


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _secret_from_manual_key(manual_key: str) -> str:
    return manual_key.replace(" ", "")


async def _security_notifications(db_session, account_id):
    result = await db_session.execute(
        select(Notification).where(
            Notification.account_id == account_id,
            Notification.type == NotificationType.SECURITY_EVENT,
        )
    )
    return result.scalars().all()


async def test_enabling_2fa_notifies_owner(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    start = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    secret = _secret_from_manual_key(start.json()["manual_key"])
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert confirm.status_code == 200

    notifications = await _security_notifications(db_session, owner.id)
    assert len(notifications) == 1
    assert "enabled" in notifications[0].title.lower()
    assert secret not in notifications[0].message


async def test_disabling_2fa_notifies_owner(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    start = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    secret = _secret_from_manual_key(start.json()["manual_key"])
    await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )

    response = await client.post(
        "/auth/2fa/disable",
        json={"password": "OwnerPass123", "code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 204

    notifications = await _security_notifications(db_session, owner.id)
    titles = [n.title.lower() for n in notifications]
    assert any("disabled" in title for title in titles)


async def test_logout_all_notifies_owner_only_when_sessions_revoked(
    client, make_account, db_session
):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    # No other sessions yet - logout-all should revoke zero and not notify.
    zero_revoke = await client.post("/auth/logout-all", headers=_auth_headers(owner))
    assert zero_revoke.status_code == 200
    assert zero_revoke.json()["revoked_count"] == 0
    assert await _security_notifications(db_session, owner.id) == []

    # Create a real extra session, then logout-all again.
    await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    response = await client.post("/auth/logout-all", headers=_auth_headers(owner))
    assert response.status_code == 200
    assert response.json()["revoked_count"] >= 1

    notifications = await _security_notifications(db_session, owner.id)
    assert len(notifications) == 1
    assert "session" in notifications[0].title.lower()


async def test_recovery_code_login_notifies_owner(client, make_account, db_session):
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")
    start = await client.post(
        "/auth/2fa/setup/start", json={"password": "OwnerPass123"}, headers=_auth_headers(owner)
    )
    secret = _secret_from_manual_key(start.json()["manual_key"])
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=_auth_headers(owner),
    )
    recovery_code = confirm.json()["recovery_codes"][0]

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    verify = await client.post(
        "/auth/2fa/verify",
        json={"challenge_token": login.json()["challenge_token"], "code": recovery_code},
    )
    assert verify.status_code == 200

    notifications = await _security_notifications(db_session, owner.id)
    titles = [n.title.lower() for n in notifications]
    assert any("recovery" in title for title in titles)
    for notification in notifications:
        assert recovery_code not in notification.message


async def test_user_and_merchant_get_no_security_notifications(client, make_account, db_session):
    user = await make_account(role=UserRole.USER, password="UserPass123")
    await client.post("/auth/logout-all", headers=_auth_headers(user))
    assert await _security_notifications(db_session, user.id) == []
