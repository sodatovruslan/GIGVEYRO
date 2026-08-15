import uuid

from app.models.account import Account
from app.repositories.account import AccountRepository


class AccountService:
    def __init__(self, repository: AccountRepository):
        self._repository = repository

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._repository.get_by_id(account_id)

    async def get_by_username(self, username: str) -> Account | None:
        return await self._repository.get_by_username(username)
