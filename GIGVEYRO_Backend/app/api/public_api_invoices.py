import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_merchant_via_api_key
from app.db.session import get_db
from app.models.account import Account
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.schemas.invoice import InvoiceCreate, InvoiceRead
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.invoice import InvoiceNotFoundError, InvoiceService

router = APIRouter(prefix="/api/v1/public/invoices", tags=["Public API - Invoices"])


def _service(db: AsyncSession = Depends(get_db)) -> InvoiceService:
    return InvoiceService(
        InvoiceRepository(db), DepositRepository(db), MockTRC20DepositProvider()
    )


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def create_invoice_via_api(
    payload: InvoiceCreate,
    merchant: Account = Depends(get_merchant_via_api_key),
    service: InvoiceService = Depends(_service),
) -> InvoiceRead:
    return await service.create_invoice(
        merchant,
        amount=payload.amount,
        description=payload.description,
        external_reference=payload.external_reference,
    )


@router.get("/{invoice_id}", response_model=InvoiceRead)
async def get_invoice_via_api(
    invoice_id: uuid.UUID,
    merchant: Account = Depends(get_merchant_via_api_key),
    service: InvoiceService = Depends(_service),
) -> InvoiceRead:
    try:
        return await service.get_for_merchant(merchant.id, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found"
        ) from exc
