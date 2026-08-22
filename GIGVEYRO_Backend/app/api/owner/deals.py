import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deal import DealListResponse, DealRead
from app.services.audit import AuditService
from app.services.deal import (
    DealNotFoundError,
    DealService,
    InvalidDealTransitionError,
)
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.realtime import RealtimeEventService
from app.services.wallet import InsufficientBalanceError, WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/owner/deals",
    tags=["Owner Deals"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DealService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(
        WalletRepository(db), LedgerRepository(db), account_repo, MerchantWalletRepository(db)
    )
    return DealService(
        deal_repository=DealRepository(db),
        requisite_repository=PaymentRequisiteRepository(db),
        traffic_repository=TrafficRepository(db),
        account_repository=account_repo,
        wallet_service=wallet_service,
        rate_provider=ConfiguredExchangeRateProvider(),
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
    )


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


@router.get("", response_model=DealListResponse)
async def list_deals(
    status: DealStatus | None = None,
    merchant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: DealService = Depends(_service),
) -> DealListResponse:
    items, total = await service.list_for_owner(
        status=status,
        merchant_id=merchant_id,
        user_id=user_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal(deal_id: uuid.UUID, service: DealService = Depends(_service)) -> DealRead:
    try:
        return await service.get_for_owner(deal_id)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found") from exc


@router.post("/{deal_id}/complete", response_model=DealRead)
async def complete_deal(
    deal_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> DealRead:
    """Owner-controlled settlement: completes deal, moves frozen USDT to merchant available USDT."""
    try:
        deal = await service.complete_deal(deal_id, actor_id=actor.id)
        await audit.log_action(
            action="deal.complete",
            entity_type="deal",
            entity_id=str(deal_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return deal
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found") from exc
    except (InvalidDealTransitionError, InsufficientBalanceError, WalletNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{deal_id}/release", response_model=DealRead)
async def release_deal(
    deal_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> DealRead:
    """Owner-controlled release: cancels deal, releases frozen USDT back to user available USDT."""
    try:
        deal = await service.cancel_or_release_deal(deal_id, actor_id=actor.id)
        await audit.log_action(
            action="deal.release",
            entity_type="deal",
            entity_id=str(deal_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return deal
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found") from exc
    except (InvalidDealTransitionError, InsufficientBalanceError, WalletNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
