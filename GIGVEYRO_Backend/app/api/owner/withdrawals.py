import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.withdrawal import WithdrawalStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.schemas.withdrawal import (
    MerchantWithdrawalListResponse,
    MerchantWithdrawalRead,
    OwnerWithdrawalAction,
)
from app.services.wallet import InsufficientBalanceError, WalletService
from app.services.withdrawal import (
    InvalidWithdrawalTransitionError,
    WithdrawalNotFoundError,
    WithdrawalService,
)

router = APIRouter(
    prefix="/owner/withdrawals",
    tags=["Owner Withdrawals"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> WithdrawalService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(
        WalletRepository(db), LedgerRepository(db), account_repo, MerchantWalletRepository(db)
    )
    return WithdrawalService(
        withdrawal_repository=WithdrawalRepository(db),
        wallet_service=wallet_service,
        account_repository=account_repo,
    )


@router.get("", response_model=MerchantWithdrawalListResponse)
async def list_withdrawals(
    status_filter: WithdrawalStatus | None = Query(default=None, alias="status"),
    merchant_id: uuid.UUID | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalListResponse:
    items, total = await service.list_for_owner(
        status=status_filter,
        merchant_id=merchant_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return MerchantWithdrawalListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{withdrawal_id}", response_model=MerchantWithdrawalRead)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    try:
        return await service.get_for_owner(withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc


@router.post("/{withdrawal_id}/approve", response_model=MerchantWithdrawalRead)
async def approve_withdrawal(
    withdrawal_id: uuid.UUID,
    payload: OwnerWithdrawalAction | None = None,
    owner: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    comment = payload.comment if payload else None
    try:
        return await service.approve_by_owner(owner.id, withdrawal_id, comment=comment)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except InvalidWithdrawalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{withdrawal_id}/reject", response_model=MerchantWithdrawalRead)
async def reject_withdrawal(
    withdrawal_id: uuid.UUID,
    payload: OwnerWithdrawalAction | None = None,
    owner: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    comment = payload.comment if payload else None
    try:
        return await service.reject_by_owner(owner.id, withdrawal_id, comment=comment)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except (InvalidWithdrawalTransitionError, InsufficientBalanceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{withdrawal_id}/mark-paid", response_model=MerchantWithdrawalRead)
async def mark_paid_withdrawal(
    withdrawal_id: uuid.UUID,
    payload: OwnerWithdrawalAction | None = None,
    owner: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    comment = payload.comment if payload else None
    try:
        return await service.mark_paid_by_owner(owner.id, withdrawal_id, comment=comment)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except (InvalidWithdrawalTransitionError, InsufficientBalanceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
