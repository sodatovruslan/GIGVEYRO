import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.schemas.account import AccountRead
from app.schemas.ledger import LedgerListResponse
from app.schemas.merchant_wallet import MerchantWalletRead
from app.schemas.owner_account import (
    AccountListResponse,
    OwnerAccountCreate,
    OwnerAccountUpdate,
    OwnerAssignTeamLead,
    OwnerPasswordReset,
)
from app.services.account import (
    AccountNotFoundError,
    AccountService,
    DuplicateAccountError,
    InvalidTeamAssignmentError,
    OwnerCreationNotAllowedError,
)
from app.services.audit import AuditService
from app.services.traffic import TrafficService
from app.services.wallet import WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/owner/accounts",
    tags=["Owner Accounts"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> AccountService:
    account_repository = AccountRepository(db)
    wallet_service = WalletService(
        WalletRepository(db),
        LedgerRepository(db),
        account_repository,
        MerchantWalletRepository(db),
    )
    traffic_service = TrafficService(
        TrafficRepository(db), PaymentRequisiteRepository(db), account_repository
    )
    return AccountService(
        account_repository, wallet_service, traffic_service, AuthSessionRepository(db)
    )


def _wallet_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(
        WalletRepository(db),
        LedgerRepository(db),
        AccountRepository(db),
        MerchantWalletRepository(db),
    )


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: OwnerAccountCreate,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AccountRead:
    try:
        account = await service.create_managed_account(
            username=payload.username,
            password=payload.password,
            role=payload.role,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
        )
        await audit.log_action(
            action="account.create",
            entity_type="account",
            entity_id=str(account.id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return account
    except OwnerCreationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    role: UserRole | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: AccountService = Depends(_service),
) -> AccountListResponse:
    items, total = await service.list_accounts(
        role=role, is_active=is_active, search=search, limit=limit, offset=offset
    )
    return AccountListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: uuid.UUID, service: AccountService = Depends(_service)
) -> AccountRead:
    account = await service.get_managed_account(account_id)
    if account is None:
        raise _not_found()
    return account


@router.get("/{merchant_id}/merchant-wallet", response_model=MerchantWalletRead)
async def get_merchant_wallet_for_owner(
    merchant_id: uuid.UUID, wallet_service: WalletService = Depends(_wallet_service)
) -> MerchantWalletRead:
    try:
        return await wallet_service.get_merchant_wallet_for_account(merchant_id)
    except WalletNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="merchant wallet not found"
        ) from exc


@router.get("/{merchant_id}/merchant-wallet/ledger", response_model=LedgerListResponse)
async def get_merchant_ledger_for_owner(
    merchant_id: uuid.UUID,
    entry_type: LedgerEntryType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    wallet_service: WalletService = Depends(_wallet_service),
) -> LedgerListResponse:
    try:
        items, total = await wallet_service.get_ledger_for_account(
            merchant_id,
            entry_type=entry_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return LedgerListResponse(items=items, total=total, limit=limit, offset=offset)
    except WalletNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="merchant ledger not found"
        ) from exc


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: uuid.UUID,
    payload: OwnerAccountUpdate,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AccountRead:
    changes = payload.model_dump(exclude_unset=True)
    try:
        account = await service.update_managed_account(account_id, changes)
        await audit.log_action(
            action="account.update",
            entity_type="account",
            entity_id=str(account_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={"fields": sorted(changes)},
        )
        return account
    except AccountNotFoundError as exc:
        raise _not_found() from exc
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{account_id}/block", response_model=AccountRead)
async def block_account(
    account_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AccountRead:
    try:
        account = await service.set_account_active(account_id, is_active=False)
        await audit.log_action(
            action="account.block",
            entity_type="account",
            entity_id=str(account_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return account
    except AccountNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{account_id}/unblock", response_model=AccountRead)
async def unblock_account(
    account_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AccountRead:
    try:
        account = await service.set_account_active(account_id, is_active=True)
        await audit.log_action(
            action="account.unblock",
            entity_type="account",
            entity_id=str(account_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
        return account
    except AccountNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{account_id}/team-lead", response_model=AccountRead)
async def assign_team_lead(
    account_id: uuid.UUID,
    payload: OwnerAssignTeamLead,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> AccountRead:
    """Assigns (or, with team_lead_id=null, unassigns) the USER at
    account_id to a TEAM_LEAD. Team Lead cabinet: this is the only way a
    USER ever enters a team - Team Lead itself has no self-service way to
    add members."""
    try:
        account = await service.assign_team_lead(account_id, payload.team_lead_id)
        await audit.log_action(
            action="account.assign_team_lead",
            entity_type="account",
            entity_id=str(account_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={"team_lead_id": str(payload.team_lead_id) if payload.team_lead_id else None},
        )
        return account
    except InvalidTeamAssignmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{account_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    account_id: uuid.UUID,
    payload: OwnerPasswordReset,
    actor: Account = Depends(get_current_account),
    service: AccountService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> None:
    try:
        await service.reset_password(account_id, payload.new_password)
        await audit.log_action(
            action="account.reset_password",
            entity_type="account",
            entity_id=str(account_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
        )
    except AccountNotFoundError as exc:
        raise _not_found() from exc
