import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.withdrawal import WithdrawalStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.user_withdrawal import UserWithdrawalRepository
from app.repositories.wallet import WalletRepository
from app.schemas.user_withdrawal import (
    OwnerUserWithdrawalAction,
    UserWithdrawalListResponse,
    UserWithdrawalRead,
)
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider
from app.services.user_withdrawal import (
    InvalidWithdrawalTransitionError,
    UserWithdrawalService,
    WithdrawalNotFoundError,
)
from app.services.wallet import InsufficientBalanceError, WalletService

router = APIRouter(
    prefix="/owner/user-withdrawals",
    tags=["Owner User Withdrawals"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> UserWithdrawalService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repo)
    return UserWithdrawalService(
        withdrawal_repository=UserWithdrawalRepository(db),
        wallet_service=wallet_service,
        account_repository=account_repo,
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
    )


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


@router.get("", response_model=UserWithdrawalListResponse)
async def list_withdrawals(
    status_filter: WithdrawalStatus | None = Query(default=None, alias="status"),
    user_id: uuid.UUID | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalListResponse:
    items, total = await service.list_for_owner(
        status=status_filter,
        user_id=user_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return UserWithdrawalListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{withdrawal_id}", response_model=UserWithdrawalRead)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalRead:
    try:
        return await service.get_for_owner(withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc


@router.post("/{withdrawal_id}/approve", response_model=UserWithdrawalRead)
async def approve_withdrawal(
    withdrawal_id: uuid.UUID,
    payload: OwnerUserWithdrawalAction | None = None,
    owner: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> UserWithdrawalRead:
    comment = payload.comment if payload else None
    try:
        withdrawal = await service.approve_by_owner(owner.id, withdrawal_id, comment)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except InvalidWithdrawalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await audit.log_action(
        action="user_withdrawal.approve",
        entity_type="user_withdrawal",
        entity_id=str(withdrawal_id),
        actor_account_id=owner.id,
        actor_role=owner.role.value,
    )
    return withdrawal


@router.post("/{withdrawal_id}/reject", response_model=UserWithdrawalRead)
async def reject_withdrawal(
    withdrawal_id: uuid.UUID,
    payload: OwnerUserWithdrawalAction | None = None,
    owner: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> UserWithdrawalRead:
    comment = payload.comment if payload else None
    try:
        withdrawal = await service.reject_by_owner(owner.id, withdrawal_id, comment)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except (InvalidWithdrawalTransitionError, InsufficientBalanceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await audit.log_action(
        action="user_withdrawal.reject",
        entity_type="user_withdrawal",
        entity_id=str(withdrawal_id),
        actor_account_id=owner.id,
        actor_role=owner.role.value,
    )
    return withdrawal


@router.post("/{withdrawal_id}/mark-paid", response_model=UserWithdrawalRead)
async def mark_paid_withdrawal(
    withdrawal_id: uuid.UUID,
) -> UserWithdrawalRead:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "CONTROLLED_PAYOUT_REQUIRED"},
    )
