from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.fees import FeeType
from app.repositories.fees import FeeRepository
from app.schemas.fees import FeeComponentOut
from app.services.fees import ENFORCED_FEE_TYPES, FeePolicyService

router = APIRouter(
    prefix="/merchant/fees",
    tags=["Merchant Fees"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> FeePolicyService:
    return FeePolicyService(FeeRepository(db))


@router.get("", response_model=FeeComponentOut)
async def get_my_fee(service: FeePolicyService = Depends(_service)) -> FeeComponentOut:
    component = await service.for_merchant()
    return FeeComponentOut(
        fee_type=component.fee_type,
        enabled=component.enabled,
        percent_bps=component.percent_bps,
        fixed_fee=component.fixed_fee,
        min_fee=component.min_fee,
        max_fee=component.max_fee,
        payer=component.payer,
        supported_for_charging=FeeType(component.fee_type) in ENFORCED_FEE_TYPES,
    )
