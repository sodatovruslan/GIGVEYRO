import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.auth_session import AuthSessionRepository
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


class InvalidTeamAssignmentError(Exception):
    """Raised when assigning a USER to a Team Lead fails validation."""


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        wallet_service: WalletService | None = None,
        traffic_service: TrafficService | None = None,
        auth_session_repository: AuthSessionRepository | None = None,
    ):
        self._repository = repository
        self._wallet_service = wallet_service
        self._traffic_service = traffic_service
        self._auth_sessions = auth_session_repository

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._repository.get_by_id(account_id)

    async def get_by_username(self, username: str) -> Account | None:
        return await self._repository.get_by_username(username)

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
            raise DuplicateAccountError("account data") from exc

        if role == UserRole.USER:
            if self._wallet_service is not None:
                await self._wallet_service.create_wallet_for_user(created)
            if self._traffic_service is not None:
                await self._traffic_service.create_settings_for_user(created.id)
        elif role == UserRole.MERCHANT:
            if self._wallet_service is not None:
                await self._wallet_service.create_wallet_for_merchant(created)
        elif role == UserRole.TEAM_LEAD:
            # Team Lead profit (see WalletService.credit_team_lead_profit)
            # lives in the same UserWallet shape as a USER's own balance.
            if self._wallet_service is not None:
                await self._wallet_service.create_wallet_for_user(created)

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

        if not is_active:
            if account.role == UserRole.USER and self._traffic_service is not None:
                try:
                    await self._traffic_service.disable_traffic(account_id)
                except TrafficSettingsNotFoundError:
                    pass
            if self._auth_sessions is not None:
                await self._auth_sessions.revoke_all_for_account(
                    account_id, reason="account_blocked"
                )

        return updated

    async def reset_password(self, account_id: uuid.UUID, new_password: str) -> None:
        account = await self._get_manageable_or_none(account_id)
        if account is None:
            raise AccountNotFoundError()

        account.password_hash = hash_password(new_password)
        await self._repository.update(account)

        if self._auth_sessions is not None:
            await self._auth_sessions.revoke_all_for_account(account_id, reason="password_reset")

    async def assign_team_lead(
        self, user_account_id: uuid.UUID, team_lead_id: uuid.UUID | None
    ) -> Account:
        """OWNER assigns/reassigns a USER to a TEAM_LEAD (None = unassign).
        Team membership is USER-only - a MERCHANT/TEAM_LEAD/OWNER account
        can never be a team member, and the target must be a real, active
        TEAM_LEAD account."""
        account = await self._repository.get_by_id(user_account_id)
        if account is None or account.role != UserRole.USER:
            raise InvalidTeamAssignmentError("only USER accounts can be assigned to a team")

        if team_lead_id is not None:
            lead = await self._repository.get_by_id(team_lead_id)
            if lead is None or lead.role != UserRole.TEAM_LEAD:
                raise InvalidTeamAssignmentError("target account is not a TEAM_LEAD")
            if not lead.is_active:
                raise InvalidTeamAssignmentError("target TEAM_LEAD account is not active")

        account.team_lead_id = team_lead_id
        return await self._repository.update(account)

    async def _get_manageable_or_none(self, account_id: uuid.UUID) -> Account | None:
        account = await self._repository.get_by_id(account_id)
        if account is None or account.role == UserRole.OWNER:
            return None
        return account
