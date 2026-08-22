from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_db_success():
    class FakeSession:
        async def execute(self, *args, **kwargs):
            return None

    async def override_get_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/db")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


async def test_health_db_failure():
    class FailingSession:
        async def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def override_get_db():
        yield FailingSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/db")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
    assert "gigveyro_user" not in response.text
    assert "CHANGE_ME" not in response.text
    assert "Traceback" not in response.text


async def test_lifespan_startup_and_health_endpoints():
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res_live = await client.get("/health/live")
            res_ready = await client.get("/health/ready")

    assert res_live.status_code == 200
    assert res_live.json() == {"status": "alive"}
    assert res_ready.status_code in (200, 503)


async def test_health_diagnostics():
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/health/diagnostics")

    assert res.status_code == 200
    data = res.json()
    assert "rate_limiting" in data
    assert "realtime" in data
    assert "workers" in data
    assert "providers" in data
    assert "redis" in data


