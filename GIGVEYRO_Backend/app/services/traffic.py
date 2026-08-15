import uuid
from datetime import UTC, datetime

from app.enums.account import UserRole
from app.models.traffic import UserTrafficSettings
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository


class TrafficSettingsNotFoundError(Exception):
    """No traffic settings reachable for the given account - covers a
    missing account, a non-USER account, and (defensively) a USER without
    settings yet. Collapsed into one safe error, same pattern as wallets."""


class TrafficNotEligibleError(Exception):
    """Raised when traffic cannot be enabled in the account's current state."""


class TrafficService:
    def __init__(
        self,
        traffic_repository: TrafficRepository,
        requisite_repository: PaymentRequisiteRepository,
        account_repository: AccountRepository,
    ):
        self._traffic = traffic_repository
        self._requisites = requisite_repository
        self._accounts = account_repository

    async def create_settings_for_user(self, account_id: uuid.UUID) -> UserTrafficSettings:
        settings = UserTrafficSettings(account_id=account_id, is_enabled=False)
        return await self._traffic.create(settings)

    async def get_settings(self, account_id: uuid.UUID) -> UserTrafficSettings:
        return await self._get_visible_or_raise(account_id)

    async def enable_traffic(self, account_id: uuid.UUID) -> UserTrafficSettings:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise TrafficSettingsNotFoundError()

        settings = await self._traffic.get_by_account_id_for_update(account_id)
        if settings is None:
            raise TrafficSettingsNotFoundError()

        if not account.is_active:
            raise TrafficNotEligibleError("account is inactive")

        eligible_count = await self._requisites.count_eligible(account_id)
        if eligible_count == 0:
            raise TrafficNotEligibleError("no active payment requisite")

        if not settings.is_enabled:
            settings.is_enabled = True
            settings.enabled_at = datetime.now(UTC)
            settings.disabled_at = None
            await self._traffic.save(settings)

        return settings

    async def disable_traffic(self, account_id: uuid.UUID) -> UserTrafficSettings:
        settings = await self._get_visible_or_raise(account_id, for_update=True)

        if settings.is_enabled:
            settings.is_enabled = False
            settings.disabled_at = datetime.now(UTC)
            await self._traffic.save(settings)

        return settings

    async def auto_disable_if_ineligible(self, account_id: uuid.UUID) -> None:
        """Called after a requisite mutation that could drop the active
        count to zero. Locks + rechecks fresh state, so it composes safely
        with a concurrent enable_traffic() on the same account."""
        settings = await self._traffic.get_by_account_id_for_update(account_id)
        if settings is None or not settings.is_enabled:
            return

        eligible_count = await self._requisites.count_eligible(account_id)
        if eligible_count == 0:
            settings.is_enabled = False
            settings.disabled_at = datetime.now(UTC)
            await self._traffic.save(settings)

    async def _get_visible_or_raise(
        self, account_id: uuid.UUID, *, for_update: bool = False
    ) -> UserTrafficSettings:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise TrafficSettingsNotFoundError()

        settings = (
            await self._traffic.get_by_account_id_for_update(account_id)
            if for_update
            else await self._traffic.get_by_account_id(account_id)
        )
        if settings is None:
            raise TrafficSettingsNotFoundError()
        return settings
