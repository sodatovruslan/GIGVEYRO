from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.wallet import LedgerEntryType
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.team_lead_withdrawal import TeamLeadWithdrawalRepository
from app.repositories.wallet import WalletRepository
from app.schemas.deal import TeamLeadDealListResponse
from app.schemas.ledger import LedgerListResponse
from app.schemas.team_lead import TeamLeadDashboardRead, TeamMemberListResponse
from app.services.team_lead import TeamLeadService
from app.services.wallet import WalletNotFoundError, WalletService

router = APIRouter(
    prefix="/team-lead",
    tags=["Team Lead Cabinet"],
    dependencies=[Depends(require_roles(UserRole.TEAM_LEAD))],
)


def _service(db: AsyncSession = Depends(get_db)) -> TeamLeadService:
    account_repo = AccountRepository(db)
    wallet_service = WalletService(WalletRepository(db), LedgerRepository(db), account_repo)
    return TeamLeadService(
        account_repository=account_repo,
        deal_repository=DealRepository(db),
        withdrawal_repository=TeamLeadWithdrawalRepository(db),
        wallet_service=wallet_service,
    )


def _wallet_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(WalletRepository(db), LedgerRepository(db), AccountRepository(db))


@router.get("/dashboard", response_model=TeamLeadDashboardRead)
async def get_dashboard(
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadService = Depends(_service),
) -> TeamLeadDashboardRead:
    summary = await service.dashboard(team_lead.id)
    return TeamLeadDashboardRead(
        profit_available=summary.profit_available,
        profit_pending_withdrawal=summary.profit_pending_withdrawal,
        team_size=summary.team_size,
        deal_count=summary.deal_count,
        deal_volume=summary.deal_volume,
    )


@router.get("/team", response_model=TeamMemberListResponse)
async def list_team(
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadService = Depends(_service),
) -> TeamMemberListResponse:
    items, total = await service.list_team(
        team_lead.id, is_active=is_active, search=search, limit=limit, offset=offset
    )
    return TeamMemberListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/deals", response_model=TeamLeadDealListResponse)
async def list_team_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    team_lead: Account = Depends(get_current_account),
    service: TeamLeadService = Depends(_service),
) -> TeamLeadDealListResponse:
    items, total = await service.list_team_deals(
        team_lead.id, status=status_filter, limit=limit, offset=offset
    )
    return TeamLeadDealListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/profit/ledger", response_model=LedgerListResponse)
async def get_profit_ledger(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    team_lead: Account = Depends(get_current_account),
    wallet_service: WalletService = Depends(_wallet_service),
) -> LedgerListResponse:
    try:
        items, total = await wallet_service.get_ledger_for_account(
            team_lead.id,
            entry_type=LedgerEntryType.TEAM_LEAD_PROFIT,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except WalletNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="wallet not found"
        ) from exc
    return LedgerListResponse(items=items, total=total, limit=limit, offset=offset)
