import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.schemas.ledger import LedgerListResponse
from app.schemas.wallet import (
    AllocateRequest,
    InsuranceAdjustRequest,
    ManualAdjustRequest,
    WalletRead,
)
from app.services.audit import AuditService
from app.services.wallet import (
    InactiveAccountError,
    InsufficientBalanceError,
    InvalidAmountError,
    WalletNotFoundError,
    WalletService,
)

router = APIRouter(
    prefix="/owner/accounts",
    tags=["Owner Wallets"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(WalletRepository(db), LedgerRepository(db), AccountRepository(db))


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


def _wallet_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, WalletNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="wallet not found")
    if isinstance(exc, InvalidAmountError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    # InactiveAccountError / InsufficientBalanceError: the account/wallet is
    # a valid target, but its current state blocks this operation.
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _wallet_response(entry: LedgerEntry) -> WalletRead:
    return WalletRead(
        currency=entry.currency,
        available_balance=entry.available_after,
        insurance_balance=entry.insurance_after,
        frozen_balance=entry.frozen_after,
    )


@router.get("/{account_id}/wallet", response_model=WalletRead)
async def get_user_wallet(
    account_id: uuid.UUID, service: WalletService = Depends(_service)
) -> WalletRead:
    try:
        return await service.get_wallet_for_account(account_id)
    except WalletNotFoundError as exc:
        raise _wallet_error_response(exc) from exc


@router.get("/{account_id}/wallet/ledger", response_model=LedgerListResponse)
async def get_user_ledger(
    account_id: uuid.UUID,
    entry_type: LedgerEntryType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: WalletService = Depends(_service),
) -> LedgerListResponse:
    try:
        items, total = await service.get_ledger_for_account(
            account_id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except WalletNotFoundError as exc:
        raise _wallet_error_response(exc) from exc

    return LedgerListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/{account_id}/wallet/allocate", response_model=WalletRead)
async def allocate(
    account_id: uuid.UUID,
    payload: AllocateRequest,
    actor: Account = Depends(get_current_account),
    service: WalletService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> WalletRead:
    try:
        entry = await service.allocate(
            actor=actor,
            target_account_id=account_id,
            amount=payload.amount,
            description=payload.description,
            idempotency_key=payload.idempotency_key,
        )
    except (WalletNotFoundError, InactiveAccountError, InvalidAmountError) as exc:
        raise _wallet_error_response(exc) from exc

    await audit.log_action(
        action="wallet.allocate",
        entity_type="wallet",
        entity_id=str(account_id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"ledger_entry_id": str(entry.id)},
    )
    return _wallet_response(entry)


@router.post("/{account_id}/wallet/insurance", response_model=WalletRead)
async def adjust_insurance(
    account_id: uuid.UUID,
    payload: InsuranceAdjustRequest,
    actor: Account = Depends(get_current_account),
    service: WalletService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> WalletRead:
    try:
        entry = await service.adjust_insurance(
            actor=actor,
            target_account_id=account_id,
            amount=payload.amount,
            description=payload.description,
            idempotency_key=payload.idempotency_key,
        )
    except (
        WalletNotFoundError,
        InactiveAccountError,
        InvalidAmountError,
        InsufficientBalanceError,
    ) as exc:
        raise _wallet_error_response(exc) from exc

    await audit.log_action(
        action="wallet.adjust_insurance",
        entity_type="wallet",
        entity_id=str(account_id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"ledger_entry_id": str(entry.id)},
    )
    return _wallet_response(entry)


@router.post("/{account_id}/wallet/adjust", response_model=WalletRead)
async def manual_adjust(
    account_id: uuid.UUID,
    payload: ManualAdjustRequest,
    actor: Account = Depends(get_current_account),
    service: WalletService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> WalletRead:
    try:
        entry = await service.manual_adjust(
            actor=actor,
            target_account_id=account_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except (
        WalletNotFoundError,
        InactiveAccountError,
        InvalidAmountError,
        InsufficientBalanceError,
    ) as exc:
        raise _wallet_error_response(exc) from exc

    await audit.log_action(
        action="wallet.manual_adjust",
        entity_type="wallet",
        entity_id=str(account_id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"ledger_entry_id": str(entry.id)},
    )
    return _wallet_response(entry)
