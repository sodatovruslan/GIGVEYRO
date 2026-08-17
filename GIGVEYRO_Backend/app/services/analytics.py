from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    AccountAnalyticsResponse,
    AccountSummaryKPI,
    AppealAnalyticsResponse,
    AppealSummaryKPI,
    BalanceIntegrityResponse,
    DashboardSummaryResponse,
    DealAnalyticsResponse,
    DealSummaryKPI,
    DealTimeSeriesPoint,
    DepositAnalyticsResponse,
    DepositSummaryKPI,
    DepositTimeSeriesPoint,
    FinancialFlowResponse,
    FinancialTotalsKPI,
    RecentActivityItem,
    TopMerchantRead,
    TopUserRead,
    TrafficSummaryKPI,
    WithdrawalAnalyticsResponse,
    WithdrawalSummaryKPI,
    WithdrawalTimeSeriesPoint,
)


class OwnerAnalyticsService:
    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo

    @staticmethod
    def parse_period_dates(
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[datetime | None, datetime | None]:
        now = datetime.now(UTC)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now
        elif period == "7d":
            return now - timedelta(days=7), now
        elif period == "30d":
            return now - timedelta(days=30), now
        elif period == "90d":
            return now - timedelta(days=90), now
        elif period == "custom":
            if date_from and date_to and date_from > date_to:
                raise ValueError("date_from must be less than or equal to date_to")
            return date_from, date_to
        return None, None

    async def get_dashboard_summary(self) -> DashboardSummaryResponse:
        acc_kpi = await self.repo.get_accounts_kpi()
        trf_kpi = await self.repo.get_traffic_kpi()
        dl_kpi = await self.repo.get_deals_kpi()
        dp_kpi = await self.repo.get_deposits_kpi()
        wd_kpi = await self.repo.get_withdrawals_kpi()
        ap_kpi = await self.repo.get_appeals_kpi()
        fin_totals = await self.repo.get_wallets_financial_totals()

        return DashboardSummaryResponse(
            accounts=AccountSummaryKPI(**acc_kpi),
            traffic=TrafficSummaryKPI(users_enabled=trf_kpi),
            deals=DealSummaryKPI(**dl_kpi),
            deposits=DepositSummaryKPI(
                total=dp_kpi["total"],
                credited=dp_kpi["credited"],
                pending=dp_kpi["waiting"] + dp_kpi["detected"] + dp_kpi["confirming"],
                amount_credited_usdt=dp_kpi["amount_credited_usdt"],
            ),
            withdrawals=WithdrawalSummaryKPI(
                total=wd_kpi["total"],
                pending=wd_kpi["pending"],
                approved=wd_kpi["approved"],
                paid=wd_kpi["paid"],
                rejected=wd_kpi["rejected"],
                amount_paid_usdt=wd_kpi["total_paid_usdt"],
            ),
            appeals=AppealSummaryKPI(
                open=ap_kpi["open"],
                under_review=ap_kpi["under_review"],
                resolved=ap_kpi["resolved"],
            ),
            financials=FinancialTotalsKPI(
                total_user_available_usdt=fin_totals["user_available"],
                total_user_insurance_usdt=fin_totals["user_insurance"],
                total_user_frozen_usdt=fin_totals["user_frozen"],
                total_merchant_available_usdt=fin_totals["merchant_available"],
                total_merchant_held_usdt=fin_totals["merchant_held"],
                total_credited_deposits_usdt=dp_kpi["amount_credited_usdt"],
                total_paid_withdrawals_usdt=wd_kpi["total_paid_usdt"],
                total_completed_deal_volume_tjs=dl_kpi["volume_tjs"],
                total_completed_deal_volume_usdt=dl_kpi["volume_usdt"],
            ),
        )

    async def get_deal_analytics(
        self,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> DealAnalyticsResponse:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        kpi = await self.repo.get_deals_kpi(d_from, d_to)

        total = kpi["total"]
        completed = kpi["completed"]
        disputed = kpi["disputed"]

        comp_rate = Decimal(f"{completed / total * 100:.2f}") if total > 0 else Decimal("0.00")
        disp_rate = Decimal(f"{disputed / total * 100:.2f}") if total > 0 else Decimal("0.00")

        avg_tjs = (kpi["volume_tjs"] / completed) if completed > 0 else Decimal("0.00000000")
        avg_usdt = (kpi["volume_usdt"] / completed) if completed > 0 else Decimal("0.00000000")

        return DealAnalyticsResponse(
            total_deals=total,
            completed_deals=completed,
            cancelled_deals=kpi["cancelled"],
            disputed_deals=disputed,
            total_volume_tjs=kpi["volume_tjs"],
            total_volume_usdt=kpi["volume_usdt"],
            average_deal_tjs=avg_tjs,
            average_deal_usdt=avg_usdt,
            completion_rate=comp_rate,
            dispute_rate=disp_rate,
            average_completion_time_seconds=kpi["avg_completion_time"],
        )

    async def get_deal_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> list[DealTimeSeriesPoint]:
        points = await self.repo.get_deals_timeseries(date_from, date_to, granularity)
        return [DealTimeSeriesPoint(**p) for p in points]

    async def get_deposit_analytics(
        self,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> DepositAnalyticsResponse:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        kpi = await self.repo.get_deposits_kpi(d_from, d_to)
        return DepositAnalyticsResponse(
            total=kpi["total"],
            waiting=kpi["waiting"],
            detected=kpi["detected"],
            confirming=kpi["confirming"],
            confirmed=kpi["confirmed"],
            credited=kpi["credited"],
            expired=kpi["expired"],
            failed=kpi["failed"],
            amount_credited_usdt=kpi["amount_credited_usdt"],
            average_confirmation_time_seconds=kpi["avg_confirmation_time"],
        )

    async def get_deposit_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> list[DepositTimeSeriesPoint]:
        points = await self.repo.get_deposits_timeseries(date_from, date_to, granularity)
        return [DepositTimeSeriesPoint(**p) for p in points]

    async def get_withdrawal_analytics(
        self,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> WithdrawalAnalyticsResponse:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        kpi = await self.repo.get_withdrawals_kpi(d_from, d_to)
        paid = kpi["paid"]
        avg_usdt = (kpi["total_paid_usdt"] / paid) if paid > 0 else Decimal("0.00000000")

        return WithdrawalAnalyticsResponse(
            total=kpi["total"],
            pending=kpi["pending"],
            approved=kpi["approved"],
            paid=paid,
            rejected=kpi["rejected"],
            cancelled=kpi["cancelled"],
            total_requested_usdt=kpi["total_requested_usdt"],
            total_paid_usdt=kpi["total_paid_usdt"],
            average_withdrawal_usdt=avg_usdt,
            average_processing_time_seconds=kpi["avg_processing_time"],
        )

    async def get_withdrawal_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> list[WithdrawalTimeSeriesPoint]:
        points = await self.repo.get_withdrawals_timeseries(date_from, date_to, granularity)
        return [WithdrawalTimeSeriesPoint(**p) for p in points]

    async def get_appeal_analytics(
        self,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> AppealAnalyticsResponse:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        kpi = await self.repo.get_appeals_kpi(d_from, d_to)
        return AppealAnalyticsResponse(**kpi)

    async def get_account_analytics(self) -> AccountAnalyticsResponse:
        acc_kpi = await self.repo.get_accounts_kpi()
        trf_kpi = await self.repo.get_traffic_kpi()
        req_kpi = await self.repo.get_requisites_kpi()
        return AccountAnalyticsResponse(
            **acc_kpi,
            traffic_enabled_users=trf_kpi,
            **req_kpi,
        )

    async def get_top_merchants(
        self,
        limit: int = 10,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[TopMerchantRead]:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        rows = await self.repo.get_top_merchants(limit, d_from, d_to)
        return [TopMerchantRead(**r) for r in rows]

    async def get_top_users(
        self,
        limit: int = 10,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[TopUserRead]:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        rows = await self.repo.get_top_users(limit, d_from, d_to)
        return [TopUserRead(**r) for r in rows]

    async def get_recent_activity(self, limit: int = 20) -> list[RecentActivityItem]:
        items = await self.repo.get_recent_activity(limit)
        return [RecentActivityItem(**i) for i in items]

    async def get_financial_flow(
        self,
        period: str = "30d",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> FinancialFlowResponse:
        d_from, d_to = self.parse_period_dates(period, date_from, date_to)
        dp_kpi = await self.repo.get_deposits_kpi(d_from, d_to)
        wd_kpi = await self.repo.get_withdrawals_kpi(d_from, d_to)
        dl_kpi = await self.repo.get_deals_kpi(d_from, d_to)
        fin_totals = await self.repo.get_wallets_financial_totals()

        return FinancialFlowResponse(
            deposits_credited_usdt=dp_kpi["amount_credited_usdt"],
            deal_settlements_usdt=dl_kpi["volume_usdt"],
            withdrawals_paid_usdt=wd_kpi["total_paid_usdt"],
            merchant_balances_usdt=fin_totals["merchant_available"] + fin_totals["merchant_held"],
        )

    async def get_balance_integrity(self) -> BalanceIntegrityResponse:
        fin_totals = await self.repo.get_wallets_financial_totals()
        dp_kpi = await self.repo.get_deposits_kpi()
        wd_kpi = await self.repo.get_withdrawals_kpi()

        u_tot = (
            fin_totals["user_available"] + fin_totals["user_insurance"] + fin_totals["user_frozen"]
        )
        m_tot = fin_totals["merchant_available"] + fin_totals["merchant_held"]

        return BalanceIntegrityResponse(
            user_wallet_total_usdt=u_tot,
            merchant_wallet_total_usdt=m_tot,
            credited_deposits_usdt=dp_kpi["amount_credited_usdt"],
            paid_withdrawals_usdt=wd_kpi["total_paid_usdt"],
            status="ok",
        )
