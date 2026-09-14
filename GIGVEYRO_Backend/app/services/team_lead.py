import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.enums.deal import DealStatus
from app.models.account import Account
from app.models.deal import Deal
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.team_lead_withdrawal import TeamLeadWithdrawalRepository
from app.services.wallet import WalletNotFoundError, WalletService


@dataclass(frozen=True, slots=True)
class TeamLeadDashboard:
    profit_available: Decimal
    profit_pending_withdrawal: Decimal
    team_size: int
    deal_count: int
    deal_volume: Decimal


class TeamLeadService:
    """Read-only views for the Team Lead cabinet - team roster, team deal
    activity, and a dashboard summary. Every query is scoped by
    Account.team_lead_id == the calling Team Lead's own id, so one Team
    Lead can never see another's team, deals, or profit (IDOR-safe by
    construction: the caller always supplies their own id, never a
    client-controlled one, and every repository query filters on it)."""

    def __init__(
        self,
        account_repository: AccountRepository,
        deal_repository: DealRepository,
        withdrawal_repository: TeamLeadWithdrawalRepository,
        wallet_service: WalletService,
    ):
        self._accounts = account_repository
        self._deals = deal_repository
        self._withdrawals = withdrawal_repository
        self._wallet_service = wallet_service

    async def list_team(
        self,
        team_lead_id: uuid.UUID,
        *,
        is_active: bool | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Account], int]:
        items = await self._accounts.list_team_members(
            team_lead_id, is_active=is_active, search=search, limit=limit, offset=offset
        )
        total = await self._accounts.count_team_members(
            team_lead_id, is_active=is_active, search=search
        )
        return items, total

    async def list_team_deals(
        self,
        team_lead_id: uuid.UUID,
        *,
        status: DealStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Deal], int]:
        items = await self._deals.list_for_team_lead(
            team_lead_id, status=status, limit=limit, offset=offset
        )
        total = await self._deals.count_for_team_lead(team_lead_id, status=status)
        return items, total

    async def dashboard(self, team_lead_id: uuid.UUID) -> TeamLeadDashboard:
        deal_count, deal_volume, _profit_total = await self._deals.team_stats(team_lead_id)
        team_size = await self._accounts.count_team_members(
            team_lead_id, is_active=True, search=None
        )
        pending_withdrawal = await self._withdrawals.sum_pending_for_team_lead(team_lead_id)
        try:
            wallet = await self._wallet_service.get_wallet_for_account(team_lead_id)
            available = wallet.available_balance
        except WalletNotFoundError:
            available = Decimal("0")

        return TeamLeadDashboard(
            profit_available=available,
            profit_pending_withdrawal=pending_withdrawal,
            team_size=team_size,
            deal_count=deal_count,
            deal_volume=deal_volume,
        )
