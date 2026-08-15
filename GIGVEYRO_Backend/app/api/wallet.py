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
from app.repositories.wallet import WalletRepository
from app.schemas.ledger import LedgerListResponse
from app.schemas.wallet import WalletRead
from app.services.wallet import WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(WalletRepository(db), LedgerRepository(db), AccountRepository(db))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="wallet not found")


@router.get("", response_model=WalletRead)
async def get_my_wallet(
    account: Account = Depends(get_current_account),
    service: WalletService = Depends(_service),
) -> WalletRead:
    try:
        return await service.get_wallet_for_account(account.id)
    except WalletNotFoundError as exc:
        raise _not_found() from exc


@router.get("/ledger", response_model=LedgerListResponse)
async def get_my_ledger(
    account: Account = Depends(get_current_account),
    entry_type: LedgerEntryType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: WalletService = Depends(_service),
) -> LedgerListResponse:
    try:
        items, total = await service.get_ledger_for_account(
            account.id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except WalletNotFoundError as exc:
        raise _not_found() from exc

    return LedgerListResponse(items=items, total=total, limit=limit, offset=offset)
