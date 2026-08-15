import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffic import UserTrafficSettings


class TrafficRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> UserTrafficSettings | None:
        result = await self._session.execute(
            select(UserTrafficSettings).where(UserTrafficSettings.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account_id_for_update(
        self, account_id: uuid.UUID
    ) -> UserTrafficSettings | None:
        """Row-locked read - the serialization point for the "traffic=true
        implies an active requisite exists" invariant under concurrency."""
        result = await self._session.execute(
            select(UserTrafficSettings)
            .where(UserTrafficSettings.account_id == account_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, settings: UserTrafficSettings) -> UserTrafficSettings:
        self._session.add(settings)
        await self._session.flush()
        await self._session.refresh(settings)
        return settings

    async def save(self, settings: UserTrafficSettings) -> UserTrafficSettings:
        await self._session.flush()
        await self._session.refresh(settings)
        return settings
