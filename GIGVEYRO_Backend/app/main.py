from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.owner.accounts import router as owner_accounts_router

app = FastAPI(
    title="GIGVEYRO API",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(owner_accounts_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
