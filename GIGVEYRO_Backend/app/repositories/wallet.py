import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import UserWallet


class WalletRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> UserWallet | None:
        result = await self._session.execute(
            select(UserWallet).where(UserWallet.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account_id_for_update(self, account_id: uuid.UUID) -> UserWallet | None:
        """Row-locked read for financial mutations - prevents lost updates
        under concurrent operations on the same wallet."""
        result = await self._session.execute(
            select(UserWallet).where(UserWallet.account_id == account_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, wallet: UserWallet) -> UserWallet:
        self._session.add(wallet)
        await self._session.flush()
        await self._session.refresh(wallet)
        return wallet

    async def save(self, wallet: UserWallet) -> UserWallet:
        await self._session.flush()
        await self._session.refresh(wallet)
        return wallet
