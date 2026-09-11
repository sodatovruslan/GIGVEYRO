from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from httpx import ASGITransport, AsyncClient

from app.core.middleware import HealthCheckBypassMiddleware


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/other")
    async def other():
        return {"status": "ok"}

    # Same order as app.main: TrustedHostMiddleware added first (inner),
    # HealthCheckBypassMiddleware added last (outer, runs first).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["app.example.com"])
    app.add_middleware(HealthCheckBypassMiddleware)
    return app


async def test_health_live_bypasses_host_validation():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_other_routes_still_enforce_host_validation():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/other")

    assert response.status_code == 400
