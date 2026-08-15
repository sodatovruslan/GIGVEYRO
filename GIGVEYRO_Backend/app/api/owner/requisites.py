import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.schemas.payment_requisite import PaymentRequisiteRead
from app.services.payment_requisite import PaymentRequisiteService, RequisiteNotFoundError
from app.services.traffic import TrafficService

router = APIRouter(
    prefix="/owner/accounts",
    tags=["Owner Requisites"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> PaymentRequisiteService:
    account_repository = AccountRepository(db)
    traffic_service = TrafficService(
        TrafficRepository(db), PaymentRequisiteRepository(db), account_repository
    )
    return PaymentRequisiteService(
        PaymentRequisiteRepository(db), traffic_service, account_repository
    )


@router.get("/{account_id}/requisites", response_model=list[PaymentRequisiteRead])
async def get_user_requisites(
    account_id: uuid.UUID, service: PaymentRequisiteService = Depends(_service)
) -> list[PaymentRequisiteRead]:
    try:
        return await service.list_for_owner(account_id)
    except RequisiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="account not found"
        ) from exc
