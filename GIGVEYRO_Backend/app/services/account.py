import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.services.traffic import TrafficService, TrafficSettingsNotFoundError
from app.services.wallet import WalletService


class AccountNotFoundError(Exception):
    """Raised when a managed (non-OWNER) account cannot be found."""


class DuplicateAccountError(Exception):
    """Raised when username/email/phone uniqueness is violated."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{field} is already in use")


class OwnerCreationNotAllowedError(Exception):
    """Raised when attempting to create an OWNER through account management."""


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        wallet_service: WalletService | None = None,
        traffic_service: TrafficService | None = None,
    ):
        self._repository = repository
        self._wallet_service = wallet_service
        self._traffic_service = traffic_service

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._repository.get_by_id(account_id)

    async def get_by_username(self, username: str) -> Account | None:
        return await self._repository.get_by_username(username)

    # -- OWNER account management (USER/MERCHANT only) ----------------------

    async def create_managed_account(
        self,
        *,
        username: str,
        password: str,
        role: UserRole,
        full_name: str,
        email: str | None,
        phone: str | None,
    ) -> Account:
        if role == UserRole.OWNER:
            raise OwnerCreationNotAllowedError("cannot create an OWNER account this way")

        if await self._repository.exists_by_username(username):
            raise DuplicateAccountError("username")
        if email is not None and await self._repository.get_by_email(email) is not None:
            raise DuplicateAccountError("email")
        if phone is not None and await self._repository.get_by_phone(phone) is not None:
            raise DuplicateAccountError("phone")

        account = Account(
            username=username,
            password_hash=hash_password(password),
            role=role,
            full_name=full_name,
            email=email,
            phone=phone,
            is_active=True,
        )
        try:
            created = await self._repository.create(account)
        except IntegrityError as exc:
            # Last-resort guard against a race between the checks above and
            # the insert - the DB unique constraints are the real backstop.
            raise DuplicateAccountError("account data") from exc

        if role == UserRole.USER:
            # Same transaction as the account insert - if either of these
            # fails, the whole request rolls back and no orphan account or
            # half-initialized USER is left behind.
            if self._wallet_service is not None:
                await self._wallet_service.create_wallet_for_user(created)
            if self._traffic_service is not None:
                await self._traffic_service.create_settings_for_user(created.id)

        return created

    async def list_accounts(
        self,
        *,
        role: UserRole | None,
        is_active: bool | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Account], int]:
        items = await self._repository.list_accounts(
            role=role, is_active=is_active, search=search, limit=limit, offset=offset
        )
        total = await self._repository.count_accounts(role=role, is_active=is_active, search=search)
        return items, total

    async def get_managed_account(self, account_id: uuid.UUID) -> Account | None:
        return await self._get_manageable_or_none(account_id)

    async def update_managed_account(
        self, account_id: uuid.UUID, changes: dict[str, Any]
    ) -> Account:
        account = await self._get_manageable_or_none(account_id)
        if account is None:
            raise AccountNotFoundError()

        new_email = changes.get("email")
        if "email" in changes and new_email is not None:
            existing = await self._repository.get_by_email(new_email)
            if existing is not None and existing.id != account.id:
                raise DuplicateAccountError("email")

        new_phone = changes.get("phone")
        if "phone" in changes and new_phone is not None:
            existing = await self._repository.get_by_phone(new_phone)
            if existing is not None and existing.id != account.id:
                raise DuplicateAccountError("phone")

        for field, value in changes.items():
            setattr(account, field, value)

        try:
            return await self._repository.update(account)
        except IntegrityError as exc:
            raise DuplicateAccountError("account data") from exc

    async def set_account_active(self, account_id: uuid.UUID, *, is_active: bool) -> Account:
        account = await self._get_manageable_or_none(account_id)
        if account is None:
            raise AccountNotFoundError()

        account.is_active = is_active
        updated = await self._repository.update(account)

        # Blocking a USER must turn traffic off in the same transaction, so
        # a blocked account can never keep "assign me deals" set. Unblocking
        # deliberately does NOT re-enable it - the user opts back in.
        if not is_active and account.role == UserRole.USER and self._traffic_service is not None:
            try:
                await self._traffic_service.disable_traffic(account_id)
            except TrafficSettingsNotFoundError:
                # Best-effort: a USER without traffic settings yet (e.g. a
                # legacy account predating Stage 6) has nothing to disable.
                pass

        return updated

    async def reset_password(self, account_id: uuid.UUID, new_password: str) -> None:
        account = await self._get_manageable_or_none(account_id)
        if account is None:
            raise AccountNotFoundError()

        account.password_hash = hash_password(new_password)
        await self._repository.update(account)

    async def _get_manageable_or_none(self, account_id: uuid.UUID) -> Account | None:
        account = await self._repository.get_by_id(account_id)
        if account is None or account.role == UserRole.OWNER:
            return None
        return account
