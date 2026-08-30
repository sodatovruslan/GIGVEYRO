import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.enums.account import UserRole
from app.main import app


@pytest.mark.asyncio
async def test_security_headers_and_request_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Permissions-Policy")
        assert "default-src 'none'" in response.headers.get("Content-Security-Policy", "")
        assert "X-Request-ID" in response.headers

        rejected = await client.get("/health", headers={"X-Request-ID": "bad/request"})
        assert rejected.headers["X-Request-ID"] != "bad/request"


@pytest.mark.asyncio
async def test_health_live_and_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res_live = await client.get("/health/live")
        assert res_live.status_code == 200
        assert res_live.json()["status"] == "alive"

        res_ready = await client.get("/health/ready")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_rate_limiting_login_brute_force():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            await client.post(
                "/auth/login", json={"username": "invalid", "password": "wrongpassword"}
            )

        res_limited = await client.post(
            "/auth/login", json={"username": "invalid", "password": "wrongpassword"}
        )
        assert res_limited.status_code == 429
        assert "Too many login attempts" in res_limited.json()["detail"]


@pytest.mark.asyncio
async def test_audit_logs_owner_only(client, make_account):
    owner = await make_account(role=UserRole.OWNER, username="audit_owner")
    user = await make_account(role=UserRole.USER, username="audit_user")

    from app.core.security import create_access_token

    owner_token = create_access_token(subject=owner.id, role=owner.role.value)
    user_token = create_access_token(subject=user.id, role=user.role.value)

    res_unauth = await client.get("/api/v1/owner/audit-logs")
    assert res_unauth.status_code == 401

    res_user = await client.get(
        "/api/v1/owner/audit-logs",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert res_user.status_code == 403

    res_owner = await client.get(
        "/api/v1/owner/audit-logs",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner.status_code == 200
    assert "items" in res_owner.json()


def test_production_settings_validation():
    with pytest.raises(ValueError, match="DEBUG must be False in production"):
        Settings(
            APP_ENV="production",
            DEBUG=True,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
            JWT_SECRET_KEY="a" * 32,
        )

    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be strong"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
            JWT_SECRET_KEY="CHANGE_ME",
        )
