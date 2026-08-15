import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.account import UserRole
from app.models.account import Account


class AccountRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_by_username(self, username: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.email == email))
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.phone == phone))
        return result.scalar_one_or_none()

    async def get_by_role(self, role: UserRole) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.role == role))
        return result.scalars().first()

    async def exists_by_username(self, username: str) -> bool:
        return await self.get_by_username(username) is not None

    async def create(self, account: Account) -> Account:
        self._session.add(account)
        await self._session.flush()
        await self._session.refresh(account)
        return account
