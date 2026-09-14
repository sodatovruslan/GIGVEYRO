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
from app.repositories.team_lead_withdrawal import TeamLeadWithdrawalRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.schemas.team_lead_withdrawal import (
    TeamLeadWithdrawalCreate,
    TeamLeadWithdrawalListResponse,
    TeamLeadWithdrawalRead,
)
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.team_lead_withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    TeamLeadWithdrawalService,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
)
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import InsufficientBalanceError, WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/team-lead/withdrawals",
    tags=["Team Lead Withdrawals"],
    dependencies=[Depends(require_roles(UserRole.TEAM_LEAD))],
)


def _service(db: AsyncSession = Depends(get_db)) -> TeamLeadWithdrawalService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repo)
    return TeamLeadWithdrawalService(
        withdrawal_repository=TeamLeadWithdrawalRepository(db),
        wallet_service=wallet_service,
        account_repository=account_repo,
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
    )


@router.post("", response_model=TeamLeadWithdrawalRead, status_code=status.HTTP_201_CREATED)
async def create_withdrawal(
    payload: TeamLeadWithdrawalCreate,
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadWithdrawalService = Depends(_service),
) -> TeamLeadWithdrawalRead:
    await enforce_rate_limit(
        f"team_lead_withdrawal_create:{team_lead.id}",
        settings.FINANCIAL_MUTATION_RATE_LIMIT_REQUESTS,
        settings.FINANCIAL_MUTATION_RATE_LIMIT_WINDOW_SECONDS,
    )
    try:
        return await service.create_withdrawal(
            team_lead,
            amount=payload.amount,
            destination_type=payload.destination_type,
            destination=payload.destination,
            comment=payload.comment,
        )
    except (
        WithdrawalCreationNotAllowedError,
        InvalidDestinationError,
        InsufficientBalanceError,
        WalletNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=TeamLeadWithdrawalListResponse)
async def list_withdrawals(
    status_filter: WithdrawalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadWithdrawalService = Depends(_service),
) -> TeamLeadWithdrawalListResponse:
    items, total = await service.list_for_team_lead(
        team_lead.id, status=status_filter, limit=limit, offset=offset
    )
    return TeamLeadWithdrawalListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{withdrawal_id}", response_model=TeamLeadWithdrawalRead)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadWithdrawalService = Depends(_service),
) -> TeamLeadWithdrawalRead:
    try:
        return await service.get_for_team_lead(team_lead.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc


@router.post("/{withdrawal_id}/cancel", response_model=TeamLeadWithdrawalRead)
async def cancel_withdrawal(
    withdrawal_id: uuid.UUID,
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadWithdrawalService = Depends(_service),
) -> TeamLeadWithdrawalRead:
    try:
        return await service.cancel_by_team_lead(team_lead.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except InvalidWithdrawalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
