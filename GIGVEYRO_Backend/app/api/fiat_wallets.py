from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_account, require_roles
from app.api.fiat_deps import get_fiat_wallet_service
from app.enums.account import UserRole
from app.models.account import Account
from app.schemas.fiat_wallet import (
    FiatBalanceListOut,
    FiatConversionHistoryOut,
    FiatLedgerListOut,
)
from app.services.fiat_wallet import FiatWalletService

router = APIRouter(
    prefix="/fiat-wallets",
    tags=["Fiat Wallets"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


@router.get("", response_model=FiatBalanceListOut)
async def my_balances(
    account: Account = Depends(get_current_account),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatBalanceListOut:
    return FiatBalanceListOut(items=await service.get_balances(account.id))


@router.get("/ledger", response_model=FiatLedgerListOut)
async def my_ledger(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Account = Depends(get_current_account),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatLedgerListOut:
    items, total = await service.ledger(account.id, limit=limit, offset=offset)
    return FiatLedgerListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/conversions", response_model=FiatConversionHistoryOut)
async def my_conversions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Account = Depends(get_current_account),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatConversionHistoryOut:
    items, total = await service.history(
        account_id=account.id,
        currency=None,
        date_from=None,
        date_to=None,
        limit=limit,
        offset=offset,
    )
    return FiatConversionHistoryOut(items=items, total=total, limit=limit, offset=offset)
