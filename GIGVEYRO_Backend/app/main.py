import logging

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  (register all ORM models before application startup)
from app.api.appeals import router as appeals_router
from app.api.auth import router as auth_router
from app.api.deals import router as deals_router
from app.api.deposits import router as deposits_router
from app.api.health import router as health_router
from app.api.merchant.deals import router as merchant_deals_router
from app.api.merchant.wallet import router as merchant_wallet_router
from app.api.merchant.withdrawals import router as merchant_withdrawals_router
from app.api.notifications import router as notifications_router
from app.api.owner.accounts import router as owner_accounts_router
from app.api.owner.analytics import router as owner_analytics_router
from app.api.owner.appeals import router as owner_appeals_router
from app.api.owner.audit import router as owner_audit_router
from app.api.owner.deals import router as owner_deals_router
from app.api.owner.deposits import router as owner_deposits_router
from app.api.owner.integrations import router as owner_integrations_router
from app.api.owner.requisites import router as owner_requisites_router
from app.api.owner.traffic import router as owner_traffic_router
from app.api.owner.wallets import router as owner_wallets_router
from app.api.owner.withdrawals import router as owner_withdrawals_router
from app.api.requisites import router as requisites_router
from app.api.telegram import router as telegram_router
from app.api.traffic import router as traffic_router
from app.api.wallet import router as wallet_router
from app.core.config import settings
from app.core.middleware import RateLimitMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware
from app.db.session import get_db

logger = logging.getLogger(__name__)

app = FastAPI(
    title="GIGVEYRO API",
    version="0.1.0",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
)

# Security Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(owner_accounts_router)
app.include_router(owner_wallets_router)
app.include_router(owner_requisites_router)
app.include_router(owner_traffic_router)
app.include_router(owner_deals_router)
app.include_router(owner_deposits_router)
app.include_router(owner_withdrawals_router)
app.include_router(owner_appeals_router)
app.include_router(owner_analytics_router)
app.include_router(owner_integrations_router)
app.include_router(owner_audit_router)
app.include_router(wallet_router)
app.include_router(merchant_wallet_router)
app.include_router(merchant_withdrawals_router)
app.include_router(requisites_router)
app.include_router(traffic_router)
app.include_router(merchant_deals_router)
app.include_router(deals_router)
app.include_router(appeals_router)
app.include_router(deposits_router)
app.include_router(notifications_router)
app.include_router(telegram_router)

if settings.APP_ENV != "production":
    from app.api.owner.dev_deposits import router as dev_deposits_router

    app.include_router(dev_deposits_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        logger.error("Health check DB failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
