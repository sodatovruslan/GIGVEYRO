import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.appeal import AppealReason, AppealStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.appeal import AppealRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.wallet import WalletRepository
from app.schemas.appeal import (
    AppealListResponse,
    AppealRead,
    AppealResolveRequest,
    AppealReviewRequest,
)
from app.services.appeal import (
    AppealNotAllowedError,
    AppealNotFoundError,
    AppealService,
    InvalidAppealTransitionError,
)
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/owner/appeals",
    tags=["Owner Appeals"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
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
    )


@router.get("", response_model=AppealListResponse)
async def list_appeals(
    status_filter: AppealStatus | None = Query(default=None, alias="status"),
    reason_code: AppealReason | None = None,
    merchant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: AppealService = Depends(_service),
) -> AppealListResponse:
    items, total = await service.list_for_owner(
        status=status_filter,
        reason_code=reason_code,
        merchant_id=merchant_id,
        user_id=user_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AppealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{appeal_id}", response_model=AppealRead)
async def get_appeal(
    appeal_id: uuid.UUID,
    service: AppealService = Depends(_service),
) -> AppealRead:
    try:
        return await service.get_for_owner(appeal_id)
    except AppealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="appeal not found") from exc


@router.post("/{appeal_id}/review", response_model=AppealRead)
async def review_appeal(
    appeal_id: uuid.UUID,
    payload: AppealReviewRequest | None = None,
    owner: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
) -> AppealRead:
    owner_note = payload.note if payload else None
    try:
        return await service.take_under_review(owner.id, appeal_id, owner_note=owner_note)
    except AppealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="appeal not found") from exc
    except InvalidAppealTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{appeal_id}/resolve", response_model=AppealRead)
async def resolve_appeal(
    appeal_id: uuid.UUID,
    payload: AppealResolveRequest,
    owner: Account = Depends(get_current_account),
    service: AppealService = Depends(_service),
) -> AppealRead:
    try:
        return await service.resolve_appeal(
            owner.id,
            appeal_id,
            resolution=payload.resolution,
            owner_note=payload.owner_note,
        )
    except AppealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="appeal not found") from exc
    except (InvalidAppealTransitionError, AppealNotAllowedError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
