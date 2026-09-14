import uuid

from sqlalchemy import Select, func, or_, select
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

    async def list_team_members(
        self, team_lead_id: uuid.UUID, *, is_active: bool | None, search: str | None,
        limit: int, offset: int,
    ) -> list[Account]:
        query = self._team_filtered(select(Account), team_lead_id, is_active=is_active, search=search)
        query = query.order_by(Account.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_team_members(
        self, team_lead_id: uuid.UUID, *, is_active: bool | None, search: str | None
    ) -> int:
        query = self._team_filtered(
            select(func.count()).select_from(Account), team_lead_id, is_active=is_active, search=search
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _team_filtered(
        query: Select, team_lead_id: uuid.UUID, *, is_active: bool | None, search: str | None
    ) -> Select:
        query = query.where(Account.role == UserRole.USER, Account.team_lead_id == team_lead_id)
        if is_active is not None:
            query = query.where(Account.is_active == is_active)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(Account.username.ilike(pattern), Account.full_name.ilike(pattern))
            )
        return query

    async def exists_by_username(self, username: str) -> bool:
        return await self.get_by_username(username) is not None

    async def create(self, account: Account) -> Account:
        self._session.add(account)
        await self._session.flush()
        await self._session.refresh(account)
        return account

    async def update(self, account: Account) -> Account:
        await self._session.flush()
        await self._session.refresh(account)
        return account

    async def list_accounts(
        self,
        *,
        role: UserRole | None,
        is_active: bool | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> list[Account]:
        query = self._filtered_query(select(Account), role=role, is_active=is_active, search=search)
        query = query.order_by(Account.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_accounts(
        self,
        *,
        role: UserRole | None,
        is_active: bool | None,
        search: str | None,
    ) -> int:
        query = self._filtered_query(
            select(func.count()).select_from(Account), role=role, is_active=is_active, search=search
        )
        result = await self._session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _filtered_query(
        query: Select,
        *,
        role: UserRole | None,
        is_active: bool | None,
        search: str | None,
    ) -> Select:
        # Managed (USER/MERCHANT) listing only - OWNER accounts are never
        # exposed through this admin listing/search.
        query = query.where(Account.role != UserRole.OWNER)
        if role is not None:
            query = query.where(Account.role == role)
        if is_active is not None:
            query = query.where(Account.is_active == is_active)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    Account.username.ilike(pattern),
                    Account.full_name.ilike(pattern),
                    Account.email.ilike(pattern),
                    Account.phone.ilike(pattern),
                )
            )
        return query
