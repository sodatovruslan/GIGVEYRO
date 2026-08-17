from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.enums.account import UserRole
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    AccountAnalyticsResponse,
    AppealAnalyticsResponse,
    BalanceIntegrityResponse,
    DashboardSummaryResponse,
    DealAnalyticsResponse,
    DealTimeSeriesPoint,
    DepositAnalyticsResponse,
    DepositTimeSeriesPoint,
    FinancialFlowResponse,
    RecentActivityItem,
    TopMerchantRead,
    TopUserRead,
    WithdrawalAnalyticsResponse,
    WithdrawalTimeSeriesPoint,
)
from app.services.analytics import OwnerAnalyticsService

router = APIRouter(prefix="/api/v1/owner", tags=["Owner Analytics"])


def _get_analytics_service(session: AsyncSession = Depends(get_db)) -> OwnerAnalyticsService:
    return OwnerAnalyticsService(AnalyticsRepository(session))


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    summary="Owner Dashboard Summary",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_dashboard_summary(
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    return await service.get_dashboard_summary()


@router.get(
    "/dashboard/activity",
    response_model=list[RecentActivityItem],
    summary="Owner Dashboard Activity Feed",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    return await service.get_recent_activity(limit)


@router.get(
    "/analytics/deals",
    response_model=DealAnalyticsResponse,
    summary="Deal Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_deal_analytics(
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_deal_analytics(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/deals/timeseries",
    response_model=list[DealTimeSeriesPoint],
    summary="Deal Time Series Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_deal_timeseries(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    granularity: Literal["day", "week", "month"] = Query("day"),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to"
        )
    return await service.get_deal_timeseries(date_from, date_to, granularity)


@router.get(
    "/analytics/deposits",
    response_model=DepositAnalyticsResponse,
    summary="Deposit Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_deposit_analytics(
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_deposit_analytics(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/deposits/timeseries",
    response_model=list[DepositTimeSeriesPoint],
    summary="Deposit Time Series Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_deposit_timeseries(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    granularity: Literal["day", "week", "month"] = Query("day"),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to"
        )
    return await service.get_deposit_timeseries(date_from, date_to, granularity)


@router.get(
    "/analytics/withdrawals",
    response_model=WithdrawalAnalyticsResponse,
    summary="Withdrawal Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_withdrawal_analytics(
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_withdrawal_analytics(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/withdrawals/timeseries",
    response_model=list[WithdrawalTimeSeriesPoint],
    summary="Withdrawal Time Series Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_withdrawal_timeseries(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    granularity: Literal["day", "week", "month"] = Query("day"),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to"
        )
    return await service.get_withdrawal_timeseries(date_from, date_to, granularity)


@router.get(
    "/analytics/appeals",
    response_model=AppealAnalyticsResponse,
    summary="Appeal Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_appeal_analytics(
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_appeal_analytics(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/accounts",
    response_model=AccountAnalyticsResponse,
    summary="Account Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_account_analytics(
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    return await service.get_account_analytics()


@router.get(
    "/analytics/top-merchants",
    response_model=list[TopMerchantRead],
    summary="Top Merchants by Completed Volume",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_top_merchants(
    limit: int = Query(10, ge=1, le=100),
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_top_merchants(limit, period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/top-users",
    response_model=list[TopUserRead],
    summary="Top Users by Completed Volume",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_top_users(
    limit: int = Query(10, ge=1, le=100),
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_top_users(limit, period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/financial-flow",
    response_model=FinancialFlowResponse,
    summary="Financial Flow Analytics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_financial_flow(
    period: Literal["today", "7d", "30d", "90d", "custom"] = Query("30d"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    try:
        return await service.get_financial_flow(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/analytics/balance-integrity",
    response_model=BalanceIntegrityResponse,
    summary="Balance Integrity Diagnostics",
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
async def get_balance_integrity(
    service: OwnerAnalyticsService = Depends(_get_analytics_service),
):
    return await service.get_balance_integrity()
