import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey


class ApiKeyRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        return await self._session.get(ApiKey, key_id)

    async def get_by_id_for_update(self, key_id: uuid.UUID) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.id == key_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def create(self, api_key: ApiKey) -> ApiKey:
        self._session.add(api_key)
        await self._session.flush()
        await self._session.refresh(api_key)
        return api_key

    async def save(self, api_key: ApiKey) -> ApiKey:
        await self._session.flush()
        await self._session.refresh(api_key)
        return api_key

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[ApiKey]:
        query = (
            select(ApiKey)
            .where(ApiKey.merchant_id == merchant_id)
            .order_by(ApiKey.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_for_merchant(self, merchant_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.merchant_id == merchant_id)
        )
        return result.scalar_one()
