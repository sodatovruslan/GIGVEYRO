from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.merchant_profile import MerchantProfileRepository
from app.schemas.merchant_profile import MerchantProfileRead, MerchantProfileUpdate
from app.services.merchant_profile import MerchantProfileService

router = APIRouter(
    prefix="/merchant/profile",
    tags=["Merchant Store Settings"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> MerchantProfileService:
    return MerchantProfileService(MerchantProfileRepository(db))


@router.get("", response_model=MerchantProfileRead)
async def get_profile(
    merchant: Account = Depends(get_current_account),
    service: MerchantProfileService = Depends(_service),
) -> MerchantProfileRead:
    return await service.get_or_create(merchant.id)


@router.put("", response_model=MerchantProfileRead)
async def update_profile(
    payload: MerchantProfileUpdate,
    merchant: Account = Depends(get_current_account),
    service: MerchantProfileService = Depends(_service),
) -> MerchantProfileRead:
    return await service.update(
        merchant.id,
        store_name=payload.store_name,
        description=payload.description,
        support_contact=payload.support_contact,
    )
