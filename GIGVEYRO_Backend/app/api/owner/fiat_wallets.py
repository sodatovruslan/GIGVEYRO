import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.api.fiat_deps import get_fiat_wallet_service
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.enums.wallet import Currency
from app.models.account import Account
from app.realtime.contracts import RealtimeEventName
from app.repositories.audit import AuditRepository
from app.repositories.notification import NotificationRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.telegram import TelegramLinkRepository
from app.schemas.fiat_wallet import (
    FiatBalanceListOut,
    FiatConversionHistoryOut,
    FiatConversionOut,
    FiatConversionPreviewOut,
    FiatConversionPreviewRequest,
    FiatLedgerListOut,
    OwnerFiatAllocationOut,
    OwnerFiatAllocationRequest,
    OwnerFiatConversionRequest,
)
from app.services.audit import AuditService
from app.services.fiat_rate.errors import FiatProviderError
from app.services.fiat_wallet import (
    FiatIdempotencyConflictError,
    FiatInsufficientBalanceError,
    FiatWalletNotFoundError,
    FiatWalletPermissionError,
    FiatWalletService,
    FiatWalletValidationError,
)
from app.services.notification import NotificationService
from app.services.realtime import RealtimeEventService
from app.services.telegram_provider import MockTelegramProvider

router = APIRouter(
    prefix="/owner",
    tags=["Owner Fiat Wallets"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FiatWalletNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER not found")
    if isinstance(exc, FiatWalletPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OWNER required")
    if isinstance(exc, FiatIdempotencyConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, FiatProviderError | RuntimeError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative TJS/RUB rate is temporarily unavailable",
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/accounts/{account_id}/fiat-wallets", response_model=FiatBalanceListOut)
async def get_balances(
    account_id: uuid.UUID, service: FiatWalletService = Depends(get_fiat_wallet_service)
) -> FiatBalanceListOut:
    try:
        return FiatBalanceListOut(items=await service.get_balances(account_id))
    except FiatWalletNotFoundError as exc:
        raise _error(exc) from exc


@router.post(
    "/accounts/{account_id}/fiat-wallets/allocate",
    response_model=OwnerFiatAllocationOut,
)
async def allocate(
    account_id: uuid.UUID,
    payload: OwnerFiatAllocationRequest,
    actor: Account = Depends(get_current_account),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
    db: AsyncSession = Depends(get_db),
) -> OwnerFiatAllocationOut:
    try:
        entry, replayed = await service.allocate(
            actor=actor,
            target_account_id=account_id,
            currency=payload.currency,
            amount=payload.amount,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
        )
    except (
        FiatWalletNotFoundError,
        FiatWalletPermissionError,
        FiatWalletValidationError,
        FiatIdempotencyConflictError,
    ) as exc:
        raise _error(exc) from exc
    if not replayed:
        await AuditService(AuditRepository(db)).log_action(
            action="fiat.allocate",
            entity_type="fiat_wallet",
            entity_id=str(entry.reference_id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={
                "target_account_id": str(account_id),
                "currency": entry.currency.value,
                "amount": str(entry.amount),
            },
        )
        await _notify(db, account_id, entry.currency, entry.amount, entry.reference_id)
        await RealtimeEventService(RealtimeOutboxRepository(db)).enqueue_fiat(
            RealtimeEventName.FIAT_ALLOCATED,
            operation_id=entry.reference_id,
            target_account_id=account_id,
            owner_account_id=actor.id,
            currency=entry.currency.value,
        )
    return OwnerFiatAllocationOut(
        operation_id=entry.reference_id,
        account_id=account_id,
        currency=entry.currency,
        amount=entry.amount,
        balance_before=entry.balance_before,
        balance_after=entry.balance_after,
        created_at=entry.created_at,
    )


@router.post("/fiat-conversions/preview", response_model=FiatConversionPreviewOut)
async def preview(
    payload: FiatConversionPreviewRequest,
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatConversionPreviewOut:
    try:
        destination, quote = await service.preview(
            from_currency=payload.from_currency,
            to_currency=payload.to_currency,
            source_amount=payload.source_amount,
        )
    except (FiatWalletValidationError, FiatProviderError, RuntimeError) as exc:
        raise _error(exc) from exc
    return FiatConversionPreviewOut(
        from_currency=payload.from_currency,
        to_currency=payload.to_currency,
        source_amount=payload.source_amount,
        destination_amount=destination,
        exchange_rate=quote.rate,
        provider=quote.provider,
        published_at=quote.published_at,
        received_at=quote.received_at,
        provider_nominal=quote.provider_nominal,
        provider_rate=quote.provider_rate,
        policy_version=quote.policy_version,
        mode=quote.mode,
        is_stale=quote.is_stale,
    )


@router.post(
    "/accounts/{account_id}/fiat-conversions", response_model=FiatConversionOut
)
async def convert(
    account_id: uuid.UUID,
    payload: OwnerFiatConversionRequest,
    actor: Account = Depends(get_current_account),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
    db: AsyncSession = Depends(get_db),
) -> FiatConversionOut:
    try:
        conversion, replayed = await service.convert(
            actor=actor,
            target_account_id=account_id,
            from_currency=payload.from_currency,
            to_currency=payload.to_currency,
            source_amount=payload.source_amount,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
        )
    except (
        FiatWalletNotFoundError,
        FiatWalletPermissionError,
        FiatWalletValidationError,
        FiatInsufficientBalanceError,
        FiatIdempotencyConflictError,
        FiatProviderError,
        RuntimeError,
    ) as exc:
        raise _error(exc) from exc
    if not replayed:
        await AuditService(AuditRepository(db)).log_action(
            action="fiat.convert",
            entity_type="fiat_conversion",
            entity_id=str(conversion.id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={
                "target_account_id": str(account_id),
                "from_currency": conversion.from_currency.value,
                "to_currency": conversion.to_currency.value,
                "source_amount": str(conversion.source_amount),
                "rate_provider": conversion.rate_provider,
                "rate_mode": conversion.rate_mode,
            },
        )
        await _notify(
            db,
            account_id,
            conversion.to_currency,
            conversion.destination_amount,
            conversion.id,
        )
        await RealtimeEventService(RealtimeOutboxRepository(db)).enqueue_fiat(
            RealtimeEventName.FIAT_CONVERTED,
            operation_id=conversion.id,
            target_account_id=account_id,
            owner_account_id=actor.id,
            currency=conversion.to_currency.value,
        )
    return FiatConversionOut.model_validate(conversion)


@router.get("/fiat-conversions", response_model=FiatConversionHistoryOut)
async def history(
    account_id: uuid.UUID | None = None,
    currency: Currency | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatConversionHistoryOut:
    try:
        items, total = await service.history(
            account_id=account_id,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except (FiatWalletNotFoundError, FiatWalletValidationError) as exc:
        raise _error(exc) from exc
    return FiatConversionHistoryOut(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/accounts/{account_id}/fiat-wallets/ledger", response_model=FiatLedgerListOut
)
async def ledger(
    account_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: FiatWalletService = Depends(get_fiat_wallet_service),
) -> FiatLedgerListOut:
    try:
        items, total = await service.ledger(account_id, limit=limit, offset=offset)
    except FiatWalletNotFoundError as exc:
        raise _error(exc) from exc
    return FiatLedgerListOut(items=items, total=total, limit=limit, offset=offset)


async def _notify(
    db: AsyncSession,
    account_id: uuid.UUID,
    currency: Currency,
    amount,
    operation_id: uuid.UUID,
) -> None:
    service = NotificationService(
        NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
    )
    await service.emit_notification(
        account_id,
        NotificationType.FIAT_BALANCE_UPDATED,
        title="Баланс обновлён",
        message="Ваш баланс был обновлён администратором.",
        payload={"currency": currency.value, "amount": str(amount)},
        dedupe_key=f"fiat_balance:{operation_id}",
    )
