import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.payment_requisite import PaymentRequisiteType
from app.models.account import Account
from app.models.payment_requisite import PaymentRequisite
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.services.traffic import TrafficService


class RequisiteNotFoundError(Exception):
    """Covers a missing requisite, one owned by someone else, and (for the
    OWNER read paths) a missing/non-USER target account - one safe error."""


class RequisiteNotAllowedError(Exception):
    """Raised when requisites are attempted for a non-USER account."""


class DuplicateRequisiteError(Exception):
    """Raised when the account already has this card among its
    non-archived requisites."""


class RequisiteLimitExceededError(Exception):
    """Raised when MAX_ACTIVE_REQUISITES_PER_USER would be exceeded."""


class RequisiteArchivedError(Exception):
    """Raised when trying to toggle an archived (terminal-state) requisite."""


class PaymentRequisiteService:
    def __init__(
        self,
        repository: PaymentRequisiteRepository,
        traffic_service: TrafficService,
        account_repository: AccountRepository,
    ):
        self._repository = repository
        self._traffic_service = traffic_service
        self._accounts = account_repository

    async def create(
        self,
        account: Account,
        *,
        type_: PaymentRequisiteType,
        bank_name: str,
        holder_name: str,
        card_number: str,
        phone_number: str | None,
    ) -> PaymentRequisite:
        if account.role != UserRole.USER:
            raise RequisiteNotAllowedError("payment requisites are only for USER accounts")

        non_archived_count = await self._repository.count_non_archived(account.id)
        if non_archived_count >= settings.MAX_ACTIVE_REQUISITES_PER_USER:
            raise RequisiteLimitExceededError("maximum number of requisites reached")

        if await self._repository.find_non_archived_duplicate(account.id, card_number) is not None:
            raise DuplicateRequisiteError("this card is already registered")

        requisite = PaymentRequisite(
            account_id=account.id,
            type=type_,
            bank_name=bank_name,
            holder_name=holder_name,
            card_number=card_number,
            phone_number=phone_number,
            is_active=True,
            is_archived=False,
        )
        try:
            return await self._repository.create(requisite)
        except IntegrityError as exc:
            # Backstop against a race between the checks above and the
            # insert - the DB unique index is the real guarantee.
            raise DuplicateRequisiteError("this card is already registered") from exc

    async def list_own(self, account_id: uuid.UUID) -> list[PaymentRequisite]:
        return await self._repository.list_for_account(account_id)

    async def get_own(self, account_id: uuid.UUID, requisite_id: uuid.UUID) -> PaymentRequisite:
        return await self._get_owned_or_raise(account_id, requisite_id)

    async def update_own(
        self, account_id: uuid.UUID, requisite_id: uuid.UUID, changes: dict[str, Any]
    ) -> PaymentRequisite:
        requisite = await self._get_owned_or_raise(account_id, requisite_id)
        for field, value in changes.items():
            setattr(requisite, field, value)
        return await self._repository.save(requisite)

    async def activate(self, account_id: uuid.UUID, requisite_id: uuid.UUID) -> PaymentRequisite:
        requisite = await self._get_owned_or_raise(account_id, requisite_id)
        if requisite.is_archived:
            raise RequisiteArchivedError("an archived requisite cannot be reactivated")
        requisite.is_active = True
        return await self._repository.save(requisite)

    async def deactivate(self, account_id: uuid.UUID, requisite_id: uuid.UUID) -> PaymentRequisite:
        requisite = await self._get_owned_or_raise(account_id, requisite_id)
        if requisite.is_archived:
            raise RequisiteArchivedError("an archived requisite is already inactive")
        requisite.is_active = False
        saved = await self._repository.save(requisite)
        await self._traffic_service.auto_disable_if_ineligible(account_id)
        return saved

    async def archive(self, account_id: uuid.UUID, requisite_id: uuid.UUID) -> PaymentRequisite:
        requisite = await self._get_owned_or_raise(account_id, requisite_id)
        requisite.is_archived = True
        requisite.is_active = False
        saved = await self._repository.save(requisite)
        await self._traffic_service.auto_disable_if_ineligible(account_id)
        return saved

    async def list_for_owner(self, account_id: uuid.UUID) -> list[PaymentRequisite]:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise RequisiteNotFoundError()
        return await self._repository.list_for_account(account_id)

    async def _get_owned_or_raise(
        self, account_id: uuid.UUID, requisite_id: uuid.UUID
    ) -> PaymentRequisite:
        requisite = await self._repository.get_by_id(requisite_id)
        if requisite is None or requisite.account_id != account_id:
            raise RequisiteNotFoundError()
        return requisite
