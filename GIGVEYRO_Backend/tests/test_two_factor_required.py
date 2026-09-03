import pyotp

from app.core.config import settings
from app.core.security import create_access_token, create_two_factor_setup_required_token
from app.enums.account import UserRole


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _secret_from_manual_key(manual_key: str) -> str:
    return manual_key.replace(" ", "")


async def test_owner_without_2fa_logs_in_normally_when_not_required(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", False)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    response = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_owner_without_2fa_gets_setup_required_when_enforced(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    response = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("two_factor_setup_required") is True
    assert "setup_token" in body
    assert "access_token" not in body
    assert "refresh_token" not in body


async def test_owner_with_2fa_already_enabled_ignores_enforcement_flag(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
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
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("two_factor_required") is True
    assert "setup_token" not in body


async def test_user_and_merchant_unaffected_by_owner_enforcement(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    user = await make_account(role=UserRole.USER, password="UserPass123")
    merchant = await make_account(role=UserRole.MERCHANT, password="MerchantPass123")

    for account, password in ((user, "UserPass123"), (merchant, "MerchantPass123")):
        response = await client.post(
            "/auth/login", json={"username": account.username, "password": password}
        )
        assert response.status_code == 200
        assert "access_token" in response.json()


async def test_setup_token_cannot_access_protected_endpoints(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {setup_token}"})
    assert response.status_code == 401

    realtime = await client.post(
        "/api/v1/realtime/ticket",
        headers={"Authorization": f"Bearer {setup_token}"},
    )
    assert realtime.status_code == 401


async def test_setup_token_authorizes_start_without_password(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]

    response = await client.post(
        "/auth/2fa/setup/start",
        json={},
        headers={"Authorization": f"Bearer {setup_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")


async def test_setup_confirm_via_setup_token_issues_session_and_recovery_codes(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]
    setup_headers = {"Authorization": f"Bearer {setup_token}"}

    start = await client.post("/auth/2fa/setup/start", json={}, headers=setup_headers)
    secret = _secret_from_manual_key(start.json()["manual_key"])

    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=setup_headers,
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert len(body["recovery_codes"]) == 10
    assert "access_token" in body
    assert "refresh_token" in body

    # The freshly-issued access token actually works against a protected endpoint.
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == owner.username

    realtime = await client.post(
        "/api/v1/realtime/ticket",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert realtime.status_code == 200


async def test_subsequent_login_after_forced_onboarding_requires_normal_2fa_challenge(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]
    setup_headers = {"Authorization": f"Bearer {setup_token}"}
    start = await client.post("/auth/2fa/setup/start", json={}, headers=setup_headers)
    secret = _secret_from_manual_key(start.json()["manual_key"])
    await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=setup_headers,
    )

    second_login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    assert second_login.status_code == 200
    body = second_login.json()
    assert body.get("two_factor_required") is True
    assert "setup_token" not in body


async def test_expired_setup_token_rejected(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    expired_token = create_two_factor_setup_required_token(owner.id, owner.role.value, -1)

    response = await client.post(
        "/auth/2fa/setup/start",
        json={},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401


async def test_setup_token_scoped_to_its_own_account(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner_a = await make_account(role=UserRole.OWNER, password="OwnerAPass123")
    owner_b = await make_account(role=UserRole.OWNER, password="OwnerBPass123")

    login_a = await client.post(
        "/auth/login", json={"username": owner_a.username, "password": "OwnerAPass123"}
    )
    setup_token_a = login_a.json()["setup_token"]

    start = await client.post(
        "/auth/2fa/setup/start",
        json={},
        headers={"Authorization": f"Bearer {setup_token_a}"},
    )
    assert start.status_code == 200

    # owner_b must remain untouched - no pending setup, no 2FA, unaffected.
    status_b = await client.get("/auth/2fa/status", headers=_auth_headers(owner_b))
    assert status_b.json() == {
        "enabled": False,
        "required": True,
        "enabled_at": None,
        "recovery_codes_remaining": 0,
    }


async def test_setup_token_cannot_restart_setup_after_successful_confirm(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]
    setup_headers = {"Authorization": f"Bearer {setup_token}"}
    start = await client.post("/auth/2fa/setup/start", json={}, headers=setup_headers)
    secret = _secret_from_manual_key(start.json()["manual_key"])
    confirm = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=setup_headers,
    )
    assert confirm.status_code == 200

    # Same still-unexpired setup_token, replayed against setup/start again.
    replay = await client.post("/auth/2fa/setup/start", json={}, headers=setup_headers)
    assert replay.status_code == 409


async def test_confirm_without_prior_start_returns_expired(client, make_account, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", True)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": "OwnerPass123"}
    )
    setup_token = login.json()["setup_token"]

    response = await client.post(
        "/auth/2fa/setup/confirm",
        json={"totp_code": "000000"},
        headers={"Authorization": f"Bearer {setup_token}"},
    )
    assert response.status_code == 410


async def test_normal_owner_access_token_still_requires_password_for_voluntary_enable(
    client, make_account, monkeypatch
):
    monkeypatch.setattr(settings, "OWNER_2FA_REQUIRED", False)
    owner = await make_account(role=UserRole.OWNER, password="OwnerPass123")

    response = await client.post("/auth/2fa/setup/start", json={}, headers=_auth_headers(owner))
    assert response.status_code == 401
