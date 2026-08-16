import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deal import DealListResponse, DealRead
from app.services.deal import DealNotFoundError, DealService
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/owner/deals",
    tags=["Owner Deals"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
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


@router.get("", response_model=DealListResponse)
async def list_all_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
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
        status=status_filter,
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
async def get_deal(
    deal_id: uuid.UUID, service: DealService = Depends(_service)
) -> DealRead:
    try:
        return await service.get_for_owner(deal_id)
    except DealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
        ) from exc
