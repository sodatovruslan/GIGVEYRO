from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.invoice import InvoiceRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.schemas.merchant_statistics import MerchantStatisticsRead
from app.services.merchant_statistics import MerchantStatisticsService

router = APIRouter(
    tags=["Merchant Statistics"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> MerchantStatisticsService:
    return MerchantStatisticsService(InvoiceRepository(db), WithdrawalRepository(db))


@router.get("/merchant/statistics", response_model=MerchantStatisticsRead)
async def get_statistics(
    merchant: Account = Depends(get_current_account),
    service: MerchantStatisticsService = Depends(_service),
) -> MerchantStatisticsRead:
    return await service.for_merchant(merchant.id)


@router.get("/merchant/reports/invoices")
async def export_invoices_csv(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    merchant: Account = Depends(get_current_account),
    service: MerchantStatisticsService = Depends(_service),
) -> Response:
    csv_body = await service.invoices_csv(merchant.id, date_from=date_from, date_to=date_to)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"},
    )
