from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.core.config import settings
from app.enums.account import UserRole
from app.models.account import Account

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
            "usdt_contract_address": settings.USDT_TRC20_CONTRACT_ADDRESS,
            "required_confirmations": settings.TRC20_REQUIRED_CONFIRMATIONS,
        },
    }
