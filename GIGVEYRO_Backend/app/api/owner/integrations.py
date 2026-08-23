from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_roles
from app.core.config import settings
from app.enums.account import UserRole
from app.models.account import Account
from app.services.market_data.errors import ProviderError
from app.services.market_data.runtime import (
    get_market_data_aggregator,
    get_market_diagnostics,
)

router = APIRouter(prefix="/api/v1/owner/integrations", tags=["Owner Integrations"])


@router.get("/diagnostics")
async def get_integrations_diagnostics(
    current_account: Annotated[Account, Depends(require_roles(UserRole.OWNER))],
):
    """Integration diagnostics endpoint restricted strictly to OWNER.
    NO secrets, private keys, or credentials are leaked in response.
    """
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
        "providers": {
            "deposit_provider": settings.DEPOSIT_PROVIDER_TYPE,
            "exchange_rate_provider": settings.EXCHANGE_RATE_PROVIDER_TYPE,
            "payout_provider": settings.PAYOUT_PROVIDER_TYPE,
        },
        "safety": {
            "payout_enabled": settings.PAYOUT_ENABLED,
            "trading_enabled": False,
            "usdt_contract_address": settings.USDT_TRC20_CONTRACT_ADDRESS,
            "required_confirmations": settings.TRC20_REQUIRED_CONFIRMATIONS,
        },
        "market_data": await get_market_diagnostics(),
    }


@router.get("/market/quote")
async def get_market_quote(
    current_account: Annotated[Account, Depends(require_roles(UserRole.OWNER))],
    symbol: str = Query(default="BTCUSDT", min_length=6, max_length=20),
):
    """Return a normalized whitelisted public quote for OWNER diagnostics."""
    try:
        quote = await get_market_data_aggregator().get_quote(symbol)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public market data runtime is unavailable",
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public market data providers are unavailable",
        ) from exc
    return quote.to_dict()
