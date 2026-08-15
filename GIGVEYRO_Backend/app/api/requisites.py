import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.schemas.payment_requisite import (
    PaymentRequisiteCreate,
    PaymentRequisiteRead,
    PaymentRequisiteUpdate,
)
from app.services.payment_requisite import (
    DuplicateRequisiteError,
    PaymentRequisiteService,
    RequisiteArchivedError,
    RequisiteLimitExceededError,
    RequisiteNotAllowedError,
    RequisiteNotFoundError,
)
from app.services.traffic import TrafficService

router = APIRouter(
    prefix="/requisites",
    tags=["Requisites"],
    dependencies=[Depends(require_roles(UserRole.USER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> PaymentRequisiteService:
    account_repository = AccountRepository(db)
    traffic_service = TrafficService(
        TrafficRepository(db), PaymentRequisiteRepository(db), account_repository
    )
    return PaymentRequisiteService(
        PaymentRequisiteRepository(db), traffic_service, account_repository
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="requisite not found")


@router.post("", response_model=PaymentRequisiteRead, status_code=status.HTTP_201_CREATED)
async def create_requisite(
    payload: PaymentRequisiteCreate,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    try:
        return await service.create(
            account,
            type_=payload.type,
            bank_name=payload.bank_name,
            holder_name=payload.holder_name,
            card_number=payload.card_number,
            phone_number=payload.phone_number,
        )
    except RequisiteNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (DuplicateRequisiteError, RequisiteLimitExceededError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[PaymentRequisiteRead])
async def list_requisites(
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> list[PaymentRequisiteRead]:
    return await service.list_own(account.id)


@router.get("/{requisite_id}", response_model=PaymentRequisiteRead)
async def get_requisite(
    requisite_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    try:
        return await service.get_own(account.id, requisite_id)
    except RequisiteNotFoundError as exc:
        raise _not_found() from exc


@router.patch("/{requisite_id}", response_model=PaymentRequisiteRead)
async def update_requisite(
    requisite_id: uuid.UUID,
    payload: PaymentRequisiteUpdate,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    changes = payload.model_dump(exclude_unset=True)
    try:
        return await service.update_own(account.id, requisite_id, changes)
    except RequisiteNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{requisite_id}/activate", response_model=PaymentRequisiteRead)
async def activate_requisite(
    requisite_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    try:
        return await service.activate(account.id, requisite_id)
    except RequisiteNotFoundError as exc:
        raise _not_found() from exc
    except RequisiteArchivedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{requisite_id}/deactivate", response_model=PaymentRequisiteRead)
async def deactivate_requisite(
    requisite_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    try:
        return await service.deactivate(account.id, requisite_id)
    except RequisiteNotFoundError as exc:
        raise _not_found() from exc
    except RequisiteArchivedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{requisite_id}/archive", response_model=PaymentRequisiteRead)
async def archive_requisite(
    requisite_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: PaymentRequisiteService = Depends(_service),
) -> PaymentRequisiteRead:
    try:
        return await service.archive(account.id, requisite_id)
    except RequisiteNotFoundError as exc:
        raise _not_found() from exc
