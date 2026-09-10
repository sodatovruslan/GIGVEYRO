import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deposit import CorrelationStatus, DepositStatus, ReconciliationStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.notification import NotificationRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deposit import (
    DepositCandidateRead,
    DepositListResponse,
    DepositRead,
    DepositReconciliationCommand,
    DepositReconciliationIgnore,
    DepositReconciliationLink,
    DepositReconciliationResultRead,
    UnmatchedTransferDetail,
    UnmatchedTransferListResponse,
    UnmatchedTransferRead,
)
from app.services.audit import AuditService
from app.services.deposit import DepositNotFoundError, DepositService
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.deposit_reconciliation import (
    DepositReconciliationError,
    DepositReconciliationService,
    ReconciliationResult,
)
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletService

router = APIRouter(
    prefix="/owner/deposits",
    tags=["Owner Deposits"],
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
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
        invoice_repository=InvoiceRepository(db),
    )


def _reconciliation_service(db: AsyncSession = Depends(get_db)) -> DepositReconciliationService:
    repository = DepositRepository(db)
    accounts = AccountRepository(db)
    deposit_service = DepositService(
        repository,
        accounts,
        WalletService(WalletRepository(db), LedgerRepository(db), accounts),
        MockTRC20DepositProvider(),
        notification_service=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
        audit_service=AuditService(AuditRepository(db)),
        realtime_service=RealtimeEventService(RealtimeOutboxRepository(db)),
        invoice_repository=InvoiceRepository(db),
    )
    return DepositReconciliationService(
        repository,
        deposit_service,
        AuditService(AuditRepository(db)),
        RealtimeEventService(RealtimeOutboxRepository(db)),
    )


def _error(exc: DepositReconciliationError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail={"code": exc.code})


def _detail_response(transfer, candidates, history) -> UnmatchedTransferDetail:  # noqa: ANN001
    values = UnmatchedTransferRead.model_validate(transfer).model_dump()
    return UnmatchedTransferDetail(
        **values,
        candidates=[
            DepositCandidateRead(
                id=item.id,
                public_id=item.public_id,
                account_id=item.account_id,
                expected_amount=item.expected_amount,
                network=item.network,
                asset=item.asset,
                status=item.status,
                expires_at=item.expires_at,
                amount_matches=item.expected_amount == transfer.amount,
                amount_difference=item.expected_amount - transfer.amount,
            )
            for item in candidates
        ],
        history=history,
    )


def _result_response(result: ReconciliationResult) -> DepositReconciliationResultRead:
    return DepositReconciliationResultRead(
        result_code=result.result_code,
        replayed=result.replayed,
        transfer=result.transfer,
        deposit=result.deposit,
    )


@router.get("", response_model=DepositListResponse)
async def list_all_deposits(
    status_filter: DepositStatus | None = Query(default=None, alias="status"),
    account_id: uuid.UUID | None = None,
    search: str | None = None,
    tx_hash: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: DepositService = Depends(_service),
) -> DepositListResponse:
    items, total = await service.list_for_owner(
        status=status_filter,
        account_id=account_id,
        search=search,
        tx_hash=tx_hash,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return DepositListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/unmatched", response_model=UnmatchedTransferListResponse)
async def list_unmatched_transfers(
    correlation_status: CorrelationStatus | None = Query(default=None, alias="status"),
    reconciliation_status: ReconciliationStatus | None = None,
    tx_hash: str | None = None,
    reason: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: DepositService = Depends(_service),
) -> UnmatchedTransferListResponse:
    items, total = await service.list_unmatched_for_owner(
        correlation_status=correlation_status,
        reconciliation_status=reconciliation_status,
        tx_hash=tx_hash,
        reason=reason,
        date_from=date_from,
        date_to=date_to,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset,
    )
    return UnmatchedTransferListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/unmatched/{transfer_id}", response_model=UnmatchedTransferDetail)
async def get_unmatched_transfer(
    transfer_id: uuid.UUID,
    service: DepositReconciliationService = Depends(_reconciliation_service),
) -> UnmatchedTransferDetail:
    try:
        return _detail_response(*(await service.detail(transfer_id)))
    except DepositReconciliationError as exc:
        raise _error(exc) from exc


@router.post("/unmatched/{transfer_id}/link", response_model=DepositReconciliationResultRead)
async def link_unmatched_transfer(
    transfer_id: uuid.UUID,
    payload: DepositReconciliationLink,
    actor: Account = Depends(get_current_account),
    service: DepositReconciliationService = Depends(_reconciliation_service),
) -> DepositReconciliationResultRead:
    try:
        return _result_response(
            await service.link(transfer_id, payload.deposit_id, actor, payload.idempotency_key)
        )
    except DepositReconciliationError as exc:
        await service.record_link_failure(
            transfer_id,
            payload.deposit_id,
            actor,
            payload.idempotency_key,
            exc,
        )
        return JSONResponse(status_code=exc.http_status, content={"detail": {"code": exc.code}})


@router.post("/unmatched/{transfer_id}/reprocess", response_model=DepositReconciliationResultRead)
async def reprocess_unmatched_transfer(
    transfer_id: uuid.UUID,
    payload: DepositReconciliationCommand,
    actor: Account = Depends(get_current_account),
    service: DepositReconciliationService = Depends(_reconciliation_service),
) -> DepositReconciliationResultRead:
    try:
        return _result_response(
            await service.reprocess(transfer_id, actor, payload.idempotency_key)
        )
    except DepositReconciliationError as exc:
        raise _error(exc) from exc


@router.post("/unmatched/{transfer_id}/ignore", response_model=DepositReconciliationResultRead)
async def ignore_unmatched_transfer(
    transfer_id: uuid.UUID,
    payload: DepositReconciliationIgnore,
    actor: Account = Depends(get_current_account),
    service: DepositReconciliationService = Depends(_reconciliation_service),
) -> DepositReconciliationResultRead:
    try:
        return _result_response(
            await service.ignore(transfer_id, actor, payload.reason, payload.idempotency_key)
        )
    except DepositReconciliationError as exc:
        raise _error(exc) from exc


@router.get("/{deposit_id}", response_model=DepositRead)
async def get_deposit(
    deposit_id: uuid.UUID, service: DepositService = Depends(_service)
) -> DepositRead:
    try:
        return await service.get_for_owner(deposit_id)
    except DepositNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="deposit not found"
        ) from exc
