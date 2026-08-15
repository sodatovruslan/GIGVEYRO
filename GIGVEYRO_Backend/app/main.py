from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.owner.accounts import router as owner_accounts_router
from app.api.owner.requisites import router as owner_requisites_router
from app.api.owner.traffic import router as owner_traffic_router
from app.api.owner.wallets import router as owner_wallets_router
from app.api.requisites import router as requisites_router
from app.api.traffic import router as traffic_router
from app.api.wallet import router as wallet_router

app = FastAPI(
    title="GIGVEYRO API",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(owner_accounts_router)
app.include_router(owner_wallets_router)
app.include_router(owner_requisites_router)
app.include_router(owner_traffic_router)
app.include_router(wallet_router)
app.include_router(requisites_router)
app.include_router(traffic_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
