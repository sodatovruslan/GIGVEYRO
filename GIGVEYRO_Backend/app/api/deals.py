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
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.risk import RiskRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deal import DealAccept, DealListResponse, DealRead
from app.services.deal import (
    DealNotAvailableError,
    DealNotFoundError,
    DealService,
    RequisiteNotEligibleError,
    UserNotEligibleError,
)
from app.services.exchange_rate import ExchangeRateError
from app.services.provider_factory import get_exchange_rate_provider
from app.services.realtime import RealtimeEventService
from app.services.risk import RiskBlockedError, RiskGuard
from app.services.wallet import InsufficientBalanceError, WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/deals",
    tags=["Deals"],
    dependencies=[Depends(require_roles(UserRole.USER))],
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
        get_exchange_rate_provider(),
        RealtimeEventService(RealtimeOutboxRepository(db)),
        RiskGuard(RiskRepository(db)),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")


@router.get("/available", response_model=DealListResponse)
async def list_available_deals(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealListResponse:
    try:
        items, total = await service.list_available_for_user(account.id, limit=limit, offset=offset)
    except UserNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("", response_model=DealListResponse)
async def list_own_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealListResponse:
    items, total = await service.list_own_for_user(
        account.id, status=status_filter, limit=limit, offset=offset
    )
    return DealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{deal_id}", response_model=DealRead)
async def get_own_deal(
    deal_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.get_own_for_user(account.id, deal_id)
    except DealNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{deal_id}/accept", response_model=DealRead)
async def accept_deal(
    deal_id: uuid.UUID,
    payload: DealAccept,
    account: Account = Depends(get_current_account),
    service: DealService = Depends(_service),
) -> DealRead:
    try:
        return await service.accept_deal(
            account=account, deal_id=deal_id, requisite_id=payload.payment_requisite_id
        )
    except DealNotFoundError as exc:
        raise _not_found() from exc
    except DealNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UserNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RequisiteNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WalletNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="wallet not found"
        ) from exc
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ExchangeRateError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="exchange rate is temporarily unavailable",
        ) from exc
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
