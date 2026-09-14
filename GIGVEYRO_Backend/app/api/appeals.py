import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.appeal import AppealStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.appeal import AppealRepository
from app.repositories.audit import AuditRepository
from app.repositories.deal import DealRepository
from app.repositories.fees import FeeRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.notification import NotificationRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.schemas.appeal import AppealCreate, AppealListResponse, AppealRead
from app.services.appeal import (
    AppealNotAllowedError,
    AppealNotFoundError,
    AppealService,
    InvalidAppealTransitionError,
)
from app.services.audit import AuditService
from app.services.deal import DealNotFoundError
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/appeals",
    tags=["Appeals"],
    dependencies=[Depends(require_roles(UserRole.USER, UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> AppealService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(
        WalletRepository(db), LedgerRepository(db), account_repo, MerchantWalletRepository(db)
    )
    return AppealService(
        appeal_repository=AppealRepository(db),
        deal_repository=DealRepository(db),
        wallet_service=wallet_service,
        fee_repository=FeeRepository(db),
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
    )


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


@router.post(
    "/deals/{deal_id}/appeal", response_model=AppealRead, status_code=status.HTTP_201_CREATED
)
async def open_appeal(
    deal_id: uuid.UUID,
    payload: AppealCreate,
    actor: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AppealRead:
    try:
        appeal = await service.open_appeal(
            actor,
            deal_id=deal_id,
            reason_code=payload.reason_code,
            message=payload.message,
        )
        await audit.log_action(
            action="appeal.open",
            entity_type="appeal",
            entity_id=str(appeal.id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={"deal_id": str(deal_id)},
        )
        return appeal
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found") from exc
    except AppealNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=AppealListResponse)
async def list_appeals(
    status_filter: AppealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
) -> AppealListResponse:
    items, total = await service.list_for_participant(
        actor, status=status_filter, limit=limit, offset=offset
    )
    return AppealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{appeal_id}", response_model=AppealRead)
async def get_appeal(
    appeal_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
) -> AppealRead:
    try:
        return await service.get_for_participant(actor, appeal_id)
    except AppealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="appeal not found"
        ) from exc


@router.post("/{appeal_id}/cancel", response_model=AppealRead)
async def cancel_appeal(
    appeal_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AppealRead:
    try:
        appeal = await service.cancel_appeal(actor, appeal_id=appeal_id)
        await audit.log_action(
            action="appeal.cancel",
            entity_type="appeal",
            entity_id=str(appeal_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return appeal
    except AppealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="appeal not found"
        ) from exc
    except (AppealNotAllowedError, InvalidAppealTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
