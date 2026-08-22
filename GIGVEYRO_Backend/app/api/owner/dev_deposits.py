import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deposit import DepositRead, DepositSimulateTransaction
from app.services.audit import AuditService
from app.services.deposit import (
    DepositNotFoundError,
    DepositService,
    DuplicateTransactionError,
    InvalidTransactionError,
)
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/owner/dev/deposits",
    tags=["Dev Deposit Simulation"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> DepositService:
    account_repository = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repository)
    return DepositService(
        DepositRepository(db),
        account_repository,
        wallet_service,
        MockTRC20DepositProvider(),
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
        audit_service=AuditService(AuditRepository(db)),
    )


@router.post("/{deposit_id}/simulate", response_model=DepositRead)
async def simulate_deposit_transaction(
    deposit_id: uuid.UUID,
    payload: DepositSimulateTransaction,
    service: DepositService = Depends(_service),
) -> DepositRead:
    """DEV/TEST-only: stands in for what a real TRC20 listener would push
    into DepositService once one exists. Not mounted at all when
    APP_ENV=production (see app/main.py)."""
    try:
        return await service.ingest_transaction_event(
            deposit_id,
            tx_hash=payload.tx_hash,
            amount=payload.amount,
            confirmations=payload.confirmations,
            network=payload.network,
            asset=payload.asset,
            destination_address=payload.destination_address,
        )
    except DepositNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deposit not found"
        ) from exc
    except DuplicateTransactionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidTransactionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except WalletNotFoundError as exc:
        # Every USER account gets a wallet at creation time (Stage 5/6), so
        # this should never happen in practice - handled defensively rather
        # than letting it surface as a raw 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="wallet not found for this deposit"
        ) from exc
