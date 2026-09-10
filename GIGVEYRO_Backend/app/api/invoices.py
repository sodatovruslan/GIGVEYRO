from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.schemas.invoice import PublicInvoiceRead
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.invoice import InvoiceNotFoundError, InvoiceService

router = APIRouter(prefix="/invoices", tags=["Public Invoices"])


def _service(db: AsyncSession = Depends(get_db)) -> InvoiceService:
    return InvoiceService(
        InvoiceRepository(db), DepositRepository(db), MockTRC20DepositProvider()
    )


@router.get("/{public_id}", response_model=PublicInvoiceRead)
async def get_public_invoice(
    public_id: str,
    request: Request,
    service: InvoiceService = Depends(_service),
) -> PublicInvoiceRead:
    """Unauthenticated, customer-facing invoice status - used by the payment page."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    await enforce_rate_limit(
        f"public_invoice:{client_ip}",
        settings.DEFAULT_RATE_LIMIT_REQUESTS,
        settings.DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    )
    try:
        return await service.get_by_public_id(public_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found"
        ) from exc
