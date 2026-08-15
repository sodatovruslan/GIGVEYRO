import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.schemas.traffic import TrafficRead
from app.services.traffic import TrafficService, TrafficSettingsNotFoundError

router = APIRouter(
    prefix="/owner/accounts",
    tags=["Owner Traffic"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> TrafficService:
    return TrafficService(
        TrafficRepository(db), PaymentRequisiteRepository(db), AccountRepository(db)
    )


@router.get("/{account_id}/traffic", response_model=TrafficRead)
async def get_user_traffic(
    account_id: uuid.UUID, service: TrafficService = Depends(_service)
) -> TrafficRead:
    try:
        return await service.get_settings(account_id)
    except TrafficSettingsNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="traffic settings not found"
        ) from exc
