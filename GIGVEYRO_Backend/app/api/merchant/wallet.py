from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.wallet import WalletRepository
from app.schemas.ledger import LedgerListResponse
from app.schemas.merchant_wallet import MerchantWalletRead
from app.services.wallet import WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/merchant/wallet",
    tags=["Merchant Wallet"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _wallet_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(
        WalletRepository(db),
        LedgerRepository(db),
        AccountRepository(db),
        MerchantWalletRepository(db),
    )


@router.get("", response_model=MerchantWalletRead)
async def get_own_merchant_wallet(
    merchant: Account = Depends(get_current_account),
    service: WalletService = Depends(_wallet_service),
) -> MerchantWalletRead:
    try:
        return await service.get_merchant_wallet_for_account(merchant.id)
    except WalletNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="wallet not found"
        ) from exc


@router.get("/ledger", response_model=LedgerListResponse)
async def list_own_merchant_ledger(
    entry_type: LedgerEntryType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: WalletService = Depends(_wallet_service),
) -> LedgerListResponse:
    items, total = await service.get_ledger_for_account(
        merchant.id,
        entry_type=entry_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return LedgerListResponse(items=items, total=total, limit=limit, offset=offset)
