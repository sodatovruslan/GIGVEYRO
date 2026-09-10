import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_profile import MerchantProfile


class MerchantProfileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_merchant_id(self, merchant_id: uuid.UUID) -> MerchantProfile | None:
        result = await self._session.execute(
            select(MerchantProfile).where(MerchantProfile.merchant_id == merchant_id)
        )
        return result.scalar_one_or_none()

    async def create(self, profile: MerchantProfile) -> MerchantProfile:
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    async def save(self, profile: MerchantProfile) -> MerchantProfile:
        await self._session.flush()
        await self._session.refresh(profile)
        return profile
