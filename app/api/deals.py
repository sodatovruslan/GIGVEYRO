import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.appeal import AppealRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.appeal import AppealCreate, AppealRead
from app.schemas.deal import DealAccept, DealListResponse, DealRead
from app.services.appeal import AppealService
from app.services.deal import (
    DealNotAvailableError,
    DealNotFoundError,
    DealService,
    InvalidDealTransitionError,
    RequisiteNotEligibleError,
    UserNotEligibleError,
)
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import InsufficientBalanceError, WalletService

router = APIRouter(
    prefix="/deals",
    tags=["Deals"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DealService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(
        WalletRepository(db), LedgerRepository(db), account_repo, MerchantWalletRepository(db)
    )
    appeal_service = AppealService(
        AppealRepository(db), DealRepository(db), wallet_service
    )
    return DealService(
        deal_repository=DealRepository(db),
        requisite_repository=PaymentRequisiteRepository(db),
        traffic_repository=TrafficRepository(db),
        account_repository=account_repo,
        wallet_service=wallet_service,
        rate_provider=ConfiguredExchangeRateProvider(),
        appeal_service=appeal_service,
    )


@router.get("/available", response_model=DealListResponse)
async def list_available_deals(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealListResponse:
    try:
        items, total = await service.list_available_for_user(
            user.id, limit=limit, offset=offset
        )
    except UserNotEligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/my", response_model=DealListResponse)
async def list_own_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealListResponse:
    items, total = await service.list_own_for_user(
        user.id, status=status_filter, limit=limit, offset=offset
    )
    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal(
    deal_id: uuid.UUID,
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.get_own_for_user(user.id, deal_id)
    except DealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
        ) from exc


@router.post("/{deal_id}/accept", response_model=DealRead)
async def accept_deal(
    deal_id: uuid.UUID,
    payload: DealAccept,
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.accept_deal(
            account=user, deal_id=deal_id, requisite_id=payload.payment_requisite_id
        )
    except DealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
        ) from exc
    except (
        DealNotAvailableError,
        UserNotEligibleError,
        RequisiteNotEligibleError,
        InsufficientBalanceError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/{deal_id}/confirm-received", response_model=DealRead)
async def confirm_received(
    deal_id: uuid.UUID,
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.confirm_received_by_user(user, deal_id)
    except DealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
        ) from exc
    except InvalidDealTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{deal_id}/report-payment-problem", response_model=DealRead)
async def report_payment_problem(
    deal_id: uuid.UUID,
    payload: AppealCreate,
    user: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        deal, _ = await service.report_payment_problem_by_user(
            user, deal_id, reason_code=payload.reason_code, message=payload.message
        )
        return deal
    except DealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
        ) from exc
    except InvalidDealTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
