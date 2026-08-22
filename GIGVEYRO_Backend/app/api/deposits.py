import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deposit import DepositStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deposit import DepositCreate, DepositListResponse, DepositRead
from app.services.audit import AuditService
from app.services.deposit import DepositNotAllowedError, DepositNotFoundError, DepositService
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/deposits",
    tags=["Deposits"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DepositService:
    account_repository = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repository)
    return DepositService(
        DepositRepository(db),
        account_repository,
        wallet_service,
        MockTRC20DepositProvider(),
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
        audit_service=AuditService(AuditRepository(db)),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deposit not found")


@router.post("", response_model=DepositRead, status_code=status.HTTP_201_CREATED)
async def create_deposit(
    payload: DepositCreate,
    account: Account = Depends(get_current_account),
    service: DepositService = Depends(_service),
) -> DepositRead:
    try:
        return await service.create_deposit_intent(account, amount=payload.amount)
    except DepositNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("", response_model=DepositListResponse)
async def list_own_deposits(
    status_filter: DepositStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Account = Depends(get_current_account),
    service: DepositService = Depends(_service),
) -> DepositListResponse:
    items, total = await service.list_own(
        account.id, status=status_filter, limit=limit, offset=offset
    )
    return DepositListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deposit_id}", response_model=DepositRead)
async def get_own_deposit(
    deposit_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: DepositService = Depends(_service),
) -> DepositRead:
    try:
        return await service.get_own(account.id, deposit_id)
    except DepositNotFoundError as exc:
        raise _not_found() from exc
