from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.schemas.traffic import TrafficRead
from app.services.traffic import (
    TrafficNotEligibleError,
    TrafficService,
    TrafficSettingsNotFoundError,
)

router = APIRouter(
    prefix="/traffic",
    tags=["Traffic"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> TrafficService:
    return TrafficService(
        TrafficRepository(db), PaymentRequisiteRepository(db), AccountRepository(db)
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="traffic settings not found")


@router.get("", response_model=TrafficRead)
async def get_my_traffic(
    account: Account = Depends(get_current_account),
    service: TrafficService = Depends(_service),
) -> TrafficRead:
    try:
        return await service.get_settings(account.id)
    except TrafficSettingsNotFoundError as exc:
        raise _not_found() from exc


@router.post("/enable", response_model=TrafficRead)
async def enable_traffic(
    account: Account = Depends(get_current_account),
    service: TrafficService = Depends(_service),
) -> TrafficRead:
    try:
        return await service.enable_traffic(account.id)
    except TrafficSettingsNotFoundError as exc:
        raise _not_found() from exc
    except TrafficNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/disable", response_model=TrafficRead)
async def disable_traffic(
    account: Account = Depends(get_current_account),
    service: TrafficService = Depends(_service),
) -> TrafficRead:
    try:
        return await service.disable_traffic(account.id)
    except TrafficSettingsNotFoundError as exc:
        raise _not_found() from exc
