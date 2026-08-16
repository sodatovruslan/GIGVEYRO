import uuid

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
    MerchantWithdrawalCreate,
    MerchantWithdrawalListResponse,
    MerchantWithdrawalRead,
)
from app.services.wallet import InsufficientBalanceError, WalletService
from app.services.withdrawal import (
    InvalidDestinationError,
    InvalidWithdrawalTransitionError,
    WithdrawalCreationNotAllowedError,
    WithdrawalNotFoundError,
    WithdrawalService,
)

router = APIRouter(
    prefix="/merchant/withdrawals",
    tags=["Merchant Withdrawals"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
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


@router.post("", response_model=MerchantWithdrawalRead, status_code=status.HTTP_201_CREATED)
async def create_withdrawal(
    payload: MerchantWithdrawalCreate,
    merchant: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    try:
        return await service.create_withdrawal(
            merchant,
            amount=payload.amount,
            destination_type=payload.destination_type,
            destination=payload.destination,
            comment=payload.comment,
        )
    except (
        WithdrawalCreationNotAllowedError,
        InvalidDestinationError,
        InsufficientBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=MerchantWithdrawalListResponse)
async def list_withdrawals(
    status_filter: WithdrawalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalListResponse:
    items, total = await service.list_for_merchant(
        merchant.id, status=status_filter, limit=limit, offset=offset
    )
    return MerchantWithdrawalListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{withdrawal_id}", response_model=MerchantWithdrawalRead)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    try:
        return await service.get_for_merchant(merchant.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc


@router.post("/{withdrawal_id}/cancel", response_model=MerchantWithdrawalRead)
async def cancel_withdrawal(
    withdrawal_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: WithdrawalService = Depends(_service),
) -> MerchantWithdrawalRead:
    try:
        return await service.cancel_by_merchant(merchant.id, withdrawal_id)
    except WithdrawalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="withdrawal not found"
        ) from exc
    except InvalidWithdrawalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
