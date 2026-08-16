import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_wallet import MerchantWallet


class MerchantWalletRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> MerchantWallet | None:
        result = await self._session.execute(
            select(MerchantWallet).where(MerchantWallet.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account_id_for_update(self, account_id: uuid.UUID) -> MerchantWallet | None:
        result = await self._session.execute(
            select(MerchantWallet)
            .where(MerchantWallet.account_id == account_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, wallet: MerchantWallet) -> MerchantWallet:
        self._session.add(wallet)
        await self._session.flush()
        await self._session.refresh(wallet)
        return wallet

    async def save(self, wallet: MerchantWallet) -> MerchantWallet:
        await self._session.flush()
        await self._session.refresh(wallet)
        return wallet
