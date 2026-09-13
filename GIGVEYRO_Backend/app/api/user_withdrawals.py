import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.withdrawal import WithdrawalStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.risk import RiskRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.user_withdrawal import UserWithdrawalRepository
from app.repositories.wallet import WalletRepository
from app.schemas.user_withdrawal import (
    UserWithdrawalCreate,
    UserWithdrawalListResponse,
    UserWithdrawalRead,
)
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.risk import RiskBlockedError, RiskGuard
from app.services.telegram_provider import MockTelegramProvider
from app.services.user_withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    UserWithdrawalService,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
)
from app.services.wallet import InsufficientBalanceError, WalletService

router = APIRouter(
    prefix="/withdrawals",
    tags=["User Withdrawals"],
    dependencies=[Depends(require_roles(UserRole.USER))],
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
        risk_guard=RiskGuard(RiskRepository(db)),
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
    )


@router.post("", response_model=UserWithdrawalRead, status_code=status.HTTP_201_CREATED)
async def create_withdrawal(
    payload: UserWithdrawalCreate,
    user: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalRead:
    await enforce_rate_limit(
        f"user_withdrawal_create:{user.id}",
        settings.FINANCIAL_MUTATION_RATE_LIMIT_REQUESTS,
        settings.FINANCIAL_MUTATION_RATE_LIMIT_WINDOW_SECONDS,
    )
    try:
        return await service.create_withdrawal(
            user,
            amount=payload.amount,
            destination_type=payload.destination_type,
            destination=payload.destination,
            comment=payload.comment,
        )
    except RiskBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.reason.value,
                "current": str(exc.current),
                "threshold": str(exc.threshold),
                "policy_version": exc.policy_version,
            },
        ) from exc
    except (
        WithdrawalCreationNotAllowedError,
        InvalidDestinationError,
        InsufficientBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=UserWithdrawalListResponse)
async def list_withdrawals(
    status_filter: WithdrawalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalListResponse:
    items, total = await service.list_for_user(
        user.id, status=status_filter, limit=limit, offset=offset
    )
    return UserWithdrawalListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{withdrawal_id}", response_model=UserWithdrawalRead)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    user: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalRead:
    try:
        return await service.get_for_user(user.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc


@router.post("/{withdrawal_id}/cancel", response_model=UserWithdrawalRead)
async def cancel_withdrawal(
    withdrawal_id: uuid.UUID,
    user: Account = Depends(get_current_account),
    service: UserWithdrawalService = Depends(_service),
) -> UserWithdrawalRead:
    try:
        return await service.cancel_by_user(user.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except InvalidWithdrawalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
