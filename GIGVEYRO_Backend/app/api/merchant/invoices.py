import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.invoice import InvoiceStatus
from app.models.account import Account
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.schemas.invoice import InvoiceCreate, InvoiceListResponse, InvoiceRead
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.invoice import (
    InvoiceNotAllowedError,
    InvoiceNotCancellableError,
    InvoiceNotFoundError,
    InvoiceService,
)

router = APIRouter(
    prefix="/merchant/invoices",
    tags=["Merchant Invoices"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> InvoiceService:
    return InvoiceService(
        InvoiceRepository(db), DepositRepository(db), MockTRC20DepositProvider()
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    merchant: Account = Depends(get_current_account),
    service: InvoiceService = Depends(_service),
) -> InvoiceRead:
    await enforce_rate_limit(
        f"invoice_create:{merchant.id}",
        settings.FINANCIAL_MUTATION_RATE_LIMIT_REQUESTS,
        settings.FINANCIAL_MUTATION_RATE_LIMIT_WINDOW_SECONDS,
    )
    try:
        return await service.create_invoice(
            merchant,
            amount=payload.amount,
            description=payload.description,
            external_reference=payload.external_reference,
        )
    except InvoiceNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    status_filter: InvoiceStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: InvoiceService = Depends(_service),
) -> InvoiceListResponse:
    items, total = await service.list_for_merchant(
        merchant.id, status=status_filter, limit=limit, offset=offset
    )
    return InvoiceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{invoice_id}", response_model=InvoiceRead)
async def get_invoice(
    invoice_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: InvoiceService = Depends(_service),
) -> InvoiceRead:
    try:
        return await service.get_for_merchant(merchant.id, invoice_id)
    except InvoiceNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{invoice_id}/cancel", response_model=InvoiceRead)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: InvoiceService = Depends(_service),
) -> InvoiceRead:
    try:
        return await service.cancel_invoice(merchant.id, invoice_id)
    except InvoiceNotFoundError as exc:
        raise _not_found() from exc
    except InvoiceNotCancellableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
