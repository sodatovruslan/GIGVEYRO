import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deal import DealCreate, DealListResponse, DealRead
from app.services.deal import DealCreationNotAllowedError, DealNotFoundError, DealService
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/merchant/deals",
    tags=["Merchant Deals"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DealService:
    account_repository = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repository)
    return DealService(
        DealRepository(db),
        PaymentRequisiteRepository(db),
        TrafficRepository(db),
        account_repository,
        wallet_service,
        ConfiguredExchangeRateProvider(),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    merchant: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.create_deal(merchant, amount_tjs=payload.amount_tjs)
    except DealCreationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("", response_model=DealListResponse)
async def list_own_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealListResponse:
    items, total = await service.list_for_merchant(
        merchant.id, status=status_filter, limit=limit, offset=offset
    )
    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deal_id}", response_model=DealRead)
async def get_own_deal(
    deal_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.get_for_merchant(merchant.id, deal_id)
    except DealNotFoundError as exc:
        raise _not_found() from exc
