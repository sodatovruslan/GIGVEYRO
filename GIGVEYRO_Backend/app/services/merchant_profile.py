import uuid

from app.models.merchant_profile import MerchantProfile
from app.repositories.merchant_profile import MerchantProfileRepository


class MerchantProfileService:
    def __init__(self, repository: MerchantProfileRepository):
        self._profiles = repository

    async def get_or_create(self, merchant_id: uuid.UUID) -> MerchantProfile:
        profile = await self._profiles.get_by_merchant_id(merchant_id)
        if profile is not None:
            return profile
        return await self._profiles.create(MerchantProfile(merchant_id=merchant_id))

    async def update(
        self,
        merchant_id: uuid.UUID,
        *,
        store_name: str | None,
        description: str | None,
        support_contact: str | None,
    ) -> MerchantProfile:
        profile = await self.get_or_create(merchant_id)
        profile.store_name = store_name
        profile.description = description
        profile.support_contact = support_contact
        return await self._profiles.save(profile)
