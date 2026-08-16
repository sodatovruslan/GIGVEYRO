import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deposit import DepositStatus
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deposit import DepositListResponse, DepositRead
from app.services.deposit import DepositNotFoundError, DepositService
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/owner/deposits",
    tags=["Owner Deposits"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DepositService:
    account_repository = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repository)
    return DepositService(
        DepositRepository(db), account_repository, wallet_service, MockTRC20DepositProvider()
    )


@router.get("", response_model=DepositListResponse)
async def list_all_deposits(
    status_filter: DepositStatus | None = Query(default=None, alias="status"),
    account_id: uuid.UUID | None = None,
    search: str | None = None,
    tx_hash: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: DepositService = Depends(_service),
) -> DepositListResponse:
    items, total = await service.list_for_owner(
        status=status_filter,
        account_id=account_id,
        search=search,
        tx_hash=tx_hash,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return DepositListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deposit_id}", response_model=DepositRead)
async def get_deposit(
    deposit_id: uuid.UUID, service: DepositService = Depends(_service)
) -> DepositRead:
    try:
        return await service.get_for_owner(deposit_id)
    except DepositNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deposit not found"
        ) from exc
