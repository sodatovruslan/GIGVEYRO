from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.account import UserRole
from app.enums.appeal import AppealResolution, AppealStatus
from app.enums.deal import DealStatus
from app.enums.deposit import DepositStatus
from app.enums.withdrawal import WithdrawalStatus
from app.models.account import Account
from app.models.appeal import DealAppeal
from app.models.deal import Deal
from app.models.deposit import Deposit
from app.models.merchant_wallet import MerchantWallet
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.wallet import UserWallet
from app.models.withdrawal import MerchantWithdrawal


class AnalyticsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_accounts_kpi(self) -> dict[str, int]:
        stmt = select(
            func.count(case((Account.role == UserRole.USER, 1))).label("users_total"),
            func.count(
                case(((Account.role == UserRole.USER) & (Account.is_active.is_(True)), 1))
            ).label("users_active"),
            func.count(
                case(((Account.role == UserRole.USER) & (Account.is_active.is_(False)), 1))
            ).label("users_blocked"),
            func.count(case((Account.role == UserRole.MERCHANT, 1))).label("merchants_total"),
            func.count(
                case(((Account.role == UserRole.MERCHANT) & (Account.is_active.is_(True)), 1))
            ).label("merchants_active"),
            func.count(
                case(((Account.role == UserRole.MERCHANT) & (Account.is_active.is_(False)), 1))
            ).label("merchants_blocked"),
        )
        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "users_total": row.users_total or 0,
            "users_active": row.users_active or 0,
            "users_blocked": row.users_blocked or 0,
            "merchants_total": row.merchants_total or 0,
            "merchants_active": row.merchants_active or 0,
            "merchants_blocked": row.merchants_blocked or 0,
        }

    async def get_traffic_kpi(self) -> int:
        stmt = select(func.count(UserTrafficSettings.id)).where(
            UserTrafficSettings.is_enabled.is_(True)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one() or 0

    async def get_requisites_kpi(self) -> dict[str, int]:
        users_with_req_stmt = select(func.count(func.distinct(PaymentRequisite.account_id)))
        users_with_req = (await self.session.execute(users_with_req_stmt)).scalar_one() or 0

        total_users_stmt = select(func.count(Account.id)).where(Account.role == UserRole.USER)
        total_users = (await self.session.execute(total_users_stmt)).scalar_one() or 0

        return {
            "users_with_requisites": users_with_req,
            "users_without_requisites": max(0, total_users - users_with_req),
        }

    async def get_deals_kpi(
        self, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> dict[str, Any]:
        stmt = select(
            func.count(Deal.id).label("total"),
            func.count(case((Deal.status == DealStatus.AVAILABLE, 1))).label("available"),
            func.count(case((Deal.status == DealStatus.ACCEPTED, 1))).label("accepted"),
            func.count(case((Deal.status == DealStatus.PAYMENT_PENDING, 1))).label(
                "payment_pending"
            ),
            func.count(case((Deal.status == DealStatus.COMPLETED, 1))).label("completed"),
            func.count(case((Deal.status == DealStatus.DISPUTED, 1))).label("disputed"),
            func.count(case((Deal.status == DealStatus.CANCELLED, 1))).label("cancelled"),
            func.coalesce(
                func.sum(case((Deal.status == DealStatus.COMPLETED, Deal.amount_tjs))), 0
            ).label("volume_tjs"),
            func.coalesce(
                func.sum(case((Deal.status == DealStatus.COMPLETED, Deal.amount_usdt))), 0
            ).label("volume_usdt"),
            func.avg(
                case(
                    (
                        (Deal.status == DealStatus.COMPLETED) & (Deal.completed_at.is_not(None)),
                        func.extract("epoch", Deal.completed_at - Deal.created_at),
                    ),
                )
            ).label("avg_completion_time"),
        )
        if date_from:
            stmt = stmt.where(Deal.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Deal.created_at < date_to)

        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "available": row.available or 0,
            "accepted": row.accepted or 0,
            "payment_pending": row.payment_pending or 0,
            "completed": row.completed or 0,
            "disputed": row.disputed or 0,
            "cancelled": row.cancelled or 0,
            "volume_tjs": Decimal(str(row.volume_tjs or 0)),
            "volume_usdt": Decimal(str(row.volume_usdt or 0)),
            "avg_completion_time": float(row.avg_completion_time)
            if row.avg_completion_time is not None
            else None,
        }

    async def get_deals_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> Sequence[dict[str, Any]]:
        trunc = func.date_trunc(granularity, Deal.created_at)
        stmt = (
            select(
                cast(trunc, String).label("period"),
                func.count(Deal.id).label("deals"),
                func.count(case((Deal.status == DealStatus.COMPLETED, 1))).label("completed"),
                func.coalesce(
                    func.sum(case((Deal.status == DealStatus.COMPLETED, Deal.amount_tjs))), 0
                ).label("volume_tjs"),
                func.coalesce(
                    func.sum(case((Deal.status == DealStatus.COMPLETED, Deal.amount_usdt))), 0
                ).label("volume_usdt"),
            )
            .where(Deal.created_at >= date_from, Deal.created_at < date_to)
            .group_by(trunc)
            .order_by(trunc.asc())
        )
        res = await self.session.execute(stmt)
        return [
            {
                "period": r.period[:10] if granularity == "day" else r.period,
                "deals": r.deals or 0,
                "completed": r.completed or 0,
                "volume_tjs": Decimal(str(r.volume_tjs or 0)),
                "volume_usdt": Decimal(str(r.volume_usdt or 0)),
            }
            for r in res.all()
        ]

    async def get_deposits_kpi(
        self, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> dict[str, Any]:
        stmt = select(
            func.count(Deposit.id).label("total"),
            func.count(case((Deposit.status == DepositStatus.WAITING, 1))).label("waiting"),
            func.count(case((Deposit.status == DepositStatus.DETECTED, 1))).label("detected"),
            func.count(case((Deposit.status == DepositStatus.CONFIRMING, 1))).label("confirming"),
            func.count(case((Deposit.status == DepositStatus.CONFIRMED, 1))).label("confirmed"),
            func.count(case((Deposit.status == DepositStatus.CREDITED, 1))).label("credited"),
            func.count(case((Deposit.status == DepositStatus.EXPIRED, 1))).label("expired"),
            func.count(case((Deposit.status == DepositStatus.FAILED, 1))).label("failed"),
            func.coalesce(
                func.sum(case((Deposit.status == DepositStatus.CREDITED, Deposit.credited_amount))),
                0,
            ).label("amount_credited_usdt"),
            func.avg(
                case(
                    (
                        (Deposit.status == DepositStatus.CREDITED)
                        & (Deposit.credited_at.is_not(None)),
                        func.extract("epoch", Deposit.credited_at - Deposit.created_at),
                    ),
                )
            ).label("avg_confirmation_time"),
        )
        if date_from:
            stmt = stmt.where(Deposit.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Deposit.created_at < date_to)

        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "waiting": row.waiting or 0,
            "detected": row.detected or 0,
            "confirming": row.confirming or 0,
            "confirmed": row.confirmed or 0,
            "credited": row.credited or 0,
            "expired": row.expired or 0,
            "failed": row.failed or 0,
            "amount_credited_usdt": Decimal(str(row.amount_credited_usdt or 0)),
            "avg_confirmation_time": float(row.avg_confirmation_time)
            if row.avg_confirmation_time is not None
            else None,
        }

    async def get_deposits_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> Sequence[dict[str, Any]]:
        trunc = func.date_trunc(granularity, Deposit.created_at)
        stmt = (
            select(
                cast(trunc, String).label("period"),
                func.count(case((Deposit.status == DepositStatus.CREDITED, 1))).label(
                    "credited_count"
                ),
                func.coalesce(
                    func.sum(
                        case((Deposit.status == DepositStatus.CREDITED, Deposit.credited_amount))
                    ),
                    0,
                ).label("credited_amount_usdt"),
            )
            .where(Deposit.created_at >= date_from, Deposit.created_at < date_to)
            .group_by(trunc)
            .order_by(trunc.asc())
        )
        res = await self.session.execute(stmt)
        return [
            {
                "period": r.period[:10] if granularity == "day" else r.period,
                "credited_count": r.credited_count or 0,
                "credited_amount_usdt": Decimal(str(r.credited_amount_usdt or 0)),
            }
            for r in res.all()
        ]

    async def get_withdrawals_kpi(
        self, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> dict[str, Any]:
        stmt = select(
            func.count(MerchantWithdrawal.id).label("total"),
            func.count(case((MerchantWithdrawal.status == WithdrawalStatus.PENDING, 1))).label(
                "pending"
            ),
            func.count(case((MerchantWithdrawal.status == WithdrawalStatus.APPROVED, 1))).label(
                "approved"
            ),
            func.count(case((MerchantWithdrawal.status == WithdrawalStatus.PAID, 1))).label("paid"),
            func.count(case((MerchantWithdrawal.status == WithdrawalStatus.REJECTED, 1))).label(
                "rejected"
            ),
            func.count(case((MerchantWithdrawal.status == WithdrawalStatus.CANCELLED, 1))).label(
                "cancelled"
            ),
            func.coalesce(func.sum(MerchantWithdrawal.amount), 0).label("total_requested_usdt"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            MerchantWithdrawal.status == WithdrawalStatus.PAID,
                            MerchantWithdrawal.amount,
                        )
                    )
                ),
                0,
            ).label("total_paid_usdt"),
            func.avg(
                case(
                    (
                        (MerchantWithdrawal.status == WithdrawalStatus.PAID)
                        & (MerchantWithdrawal.paid_at.is_not(None)),
                        func.extract(
                            "epoch", MerchantWithdrawal.paid_at - MerchantWithdrawal.created_at
                        ),
                    ),
                )
            ).label("avg_processing_time"),
        )
        if date_from:
            stmt = stmt.where(MerchantWithdrawal.created_at >= date_from)
        if date_to:
            stmt = stmt.where(MerchantWithdrawal.created_at < date_to)

        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "pending": row.pending or 0,
            "approved": row.approved or 0,
            "paid": row.paid or 0,
            "rejected": row.rejected or 0,
            "cancelled": row.cancelled or 0,
            "total_requested_usdt": Decimal(str(row.total_requested_usdt or 0)),
            "total_paid_usdt": Decimal(str(row.total_paid_usdt or 0)),
            "avg_processing_time": float(row.avg_processing_time)
            if row.avg_processing_time is not None
            else None,
        }

    async def get_withdrawals_timeseries(
        self, date_from: datetime, date_to: datetime, granularity: str = "day"
    ) -> Sequence[dict[str, Any]]:
        trunc = func.date_trunc(granularity, MerchantWithdrawal.created_at)
        stmt = (
            select(
                cast(trunc, String).label("period"),
                func.count(MerchantWithdrawal.id).label("created_count"),
                func.count(case((MerchantWithdrawal.status == WithdrawalStatus.PAID, 1))).label(
                    "paid_count"
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                MerchantWithdrawal.status == WithdrawalStatus.PAID,
                                MerchantWithdrawal.amount,
                            )
                        )
                    ),
                    0,
                ).label("paid_amount_usdt"),
            )
            .where(
                MerchantWithdrawal.created_at >= date_from, MerchantWithdrawal.created_at < date_to
            )
            .group_by(trunc)
            .order_by(trunc.asc())
        )
        res = await self.session.execute(stmt)
        return [
            {
                "period": r.period[:10] if granularity == "day" else r.period,
                "created_count": r.created_count or 0,
                "paid_count": r.paid_count or 0,
                "paid_amount_usdt": Decimal(str(r.paid_amount_usdt or 0)),
            }
            for r in res.all()
        ]

    async def get_appeals_kpi(
        self, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> dict[str, Any]:
        stmt = select(
            func.count(DealAppeal.id).label("total"),
            func.count(case((DealAppeal.status == AppealStatus.OPEN, 1))).label("open"),
            func.count(case((DealAppeal.status == AppealStatus.UNDER_REVIEW, 1))).label(
                "under_review"
            ),
            func.count(case((DealAppeal.status == AppealStatus.RESOLVED, 1))).label("resolved"),
            func.count(case((DealAppeal.status == AppealStatus.CANCELLED, 1))).label("cancelled"),
            func.count(
                case((DealAppeal.resolution == AppealResolution.SETTLE_TO_MERCHANT, 1))
            ).label("merchant_wins"),
            func.count(case((DealAppeal.resolution == AppealResolution.RELEASE_TO_USER, 1))).label(
                "user_wins"
            ),
            func.avg(
                case(
                    (
                        (DealAppeal.status == AppealStatus.RESOLVED)
                        & (DealAppeal.resolved_at.is_not(None)),
                        func.extract("epoch", DealAppeal.resolved_at - DealAppeal.created_at),
                    ),
                )
            ).label("avg_resolution_time"),
        )
        if date_from:
            stmt = stmt.where(DealAppeal.created_at >= date_from)
        if date_to:
            stmt = stmt.where(DealAppeal.created_at < date_to)

        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "open": row.open or 0,
            "under_review": row.under_review or 0,
            "resolved": row.resolved or 0,
            "cancelled": row.cancelled or 0,
            "merchant_wins": row.merchant_wins or 0,
            "user_wins": row.user_wins or 0,
            "avg_resolution_time": float(row.avg_resolution_time)
            if row.avg_resolution_time is not None
            else None,
        }

    async def get_wallets_financial_totals(self) -> dict[str, Decimal]:
        user_stmt = select(
            func.coalesce(func.sum(UserWallet.available_balance), 0).label("user_avail"),
            func.coalesce(func.sum(UserWallet.insurance_balance), 0).label("user_ins"),
            func.coalesce(func.sum(UserWallet.frozen_balance), 0).label("user_froz"),
        )
        u_res = (await self.session.execute(user_stmt)).one()

        merch_stmt = select(
            func.coalesce(func.sum(MerchantWallet.available_balance), 0).label("merch_avail"),
            func.coalesce(func.sum(MerchantWallet.held_balance), 0).label("merch_held"),
        )
        m_res = (await self.session.execute(merch_stmt)).one()

        return {
            "user_available": Decimal(str(u_res.user_avail or 0)),
            "user_insurance": Decimal(str(u_res.user_ins or 0)),
            "user_frozen": Decimal(str(u_res.user_froz or 0)),
            "merchant_available": Decimal(str(m_res.merch_avail or 0)),
            "merchant_held": Decimal(str(m_res.merch_held or 0)),
        }

    async def get_top_merchants(
        self, limit: int = 10, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> Sequence[dict[str, Any]]:
        stmt = (
            select(
                Account.id.label("account_id"),
                Account.username,
                Account.full_name,
                func.count(Deal.id).label("completed_deals"),
                func.coalesce(func.sum(Deal.amount_tjs), 0).label("volume_tjs"),
                func.coalesce(func.sum(Deal.amount_usdt), 0).label("volume_usdt"),
                func.coalesce(MerchantWallet.available_balance, 0).label(
                    "merchant_available_balance"
                ),
            )
            .join(Deal, (Deal.merchant_id == Account.id) & (Deal.status == DealStatus.COMPLETED))
            .outerjoin(MerchantWallet, MerchantWallet.account_id == Account.id)
            .where(Account.role == UserRole.MERCHANT)
        )
        if date_from:
            stmt = stmt.where(Deal.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Deal.created_at < date_to)

        stmt = stmt.group_by(
            Account.id, Account.username, Account.full_name, MerchantWallet.available_balance
        )
        stmt = stmt.order_by(func.coalesce(func.sum(Deal.amount_usdt), 0).desc()).limit(limit)

        res = await self.session.execute(stmt)
        return [
            {
                "merchant_id": str(r.account_id),
                "username": r.username,
                "full_name": r.full_name,
                "completed_deals": r.completed_deals or 0,
                "volume_tjs": Decimal(str(r.volume_tjs or 0)),
                "volume_usdt": Decimal(str(r.volume_usdt or 0)),
                "merchant_available_balance": Decimal(str(r.merchant_available_balance or 0)),
            }
            for r in res.all()
        ]

    async def get_top_users(
        self, limit: int = 10, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> Sequence[dict[str, Any]]:
        stmt = (
            select(
                Account.id.label("account_id"),
                Account.username,
                Account.full_name,
                func.count(Deal.id).label("completed_deals"),
                func.coalesce(func.sum(Deal.amount_tjs), 0).label("volume_tjs"),
                func.coalesce(func.sum(Deal.amount_usdt), 0).label("volume_usdt"),
                func.coalesce(UserTrafficSettings.is_enabled, False).label("traffic_enabled"),
                func.coalesce(UserWallet.available_balance, 0).label("available_balance"),
                func.coalesce(UserWallet.frozen_balance, 0).label("frozen_balance"),
            )
            .join(Deal, (Deal.user_id == Account.id) & (Deal.status == DealStatus.COMPLETED))
            .outerjoin(UserTrafficSettings, UserTrafficSettings.account_id == Account.id)
            .outerjoin(UserWallet, UserWallet.account_id == Account.id)
            .where(Account.role == UserRole.USER)
        )
        if date_from:
            stmt = stmt.where(Deal.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Deal.created_at < date_to)

        stmt = stmt.group_by(
            Account.id,
            Account.username,
            Account.full_name,
            UserTrafficSettings.is_enabled,
            UserWallet.available_balance,
            UserWallet.frozen_balance,
        )
        stmt = stmt.order_by(func.coalesce(func.sum(Deal.amount_usdt), 0).desc()).limit(limit)

        res = await self.session.execute(stmt)
        return [
            {
                "account_id": str(r.account_id),
                "username": r.username,
                "full_name": r.full_name,
                "completed_deals": r.completed_deals or 0,
                "volume_tjs": Decimal(str(r.volume_tjs or 0)),
                "volume_usdt": Decimal(str(r.volume_usdt or 0)),
                "traffic_enabled": bool(r.traffic_enabled),
                "available_balance": Decimal(str(r.available_balance or 0)),
                "frozen_balance": Decimal(str(r.frozen_balance or 0)),
            }
            for r in res.all()
        ]

    async def get_recent_activity(self, limit: int = 20) -> Sequence[dict[str, Any]]:
        deals_stmt = select(
            cast("deal_" + cast(Deal.status, String), String).label("type"),
            cast(Deal.id, String).label("entity_id"),
            Deal.public_id,
            cast(
                "Deal " + Deal.public_id + " (" + cast(Deal.amount_tjs, String) + " TJS)", String
            ).label("description"),
            Deal.created_at,
        )

        deps_stmt = select(
            cast("deposit_" + cast(Deposit.status, String), String).label("type"),
            cast(Deposit.id, String).label("entity_id"),
            cast(None, String).label("public_id"),
            cast("Deposit " + cast(Deposit.expected_amount, String) + " USDT", String).label(
                "description"
            ),
            Deposit.created_at,
        )

        withs_stmt = select(
            cast("withdrawal_" + cast(MerchantWithdrawal.status, String), String).label("type"),
            cast(MerchantWithdrawal.id, String).label("entity_id"),
            cast(None, String).label("public_id"),
            cast("Withdrawal " + cast(MerchantWithdrawal.amount, String) + " USDT", String).label(
                "description"
            ),
            MerchantWithdrawal.created_at,
        )

        app_stmt = select(
            cast("appeal_" + cast(DealAppeal.status, String), String).label("type"),
            cast(DealAppeal.id, String).label("entity_id"),
            cast(None, String).label("public_id"),
            cast("Appeal " + cast(DealAppeal.reason_code, String), String).label("description"),
            DealAppeal.created_at,
        )

        # Execute union or simple list merge in python if compound dialect differs
        d_res = (
            await self.session.execute(deals_stmt.order_by(Deal.created_at.desc()).limit(limit))
        ).all()
        dp_res = (
            await self.session.execute(deps_stmt.order_by(Deposit.created_at.desc()).limit(limit))
        ).all()
        w_res = (
            await self.session.execute(
                withs_stmt.order_by(MerchantWithdrawal.created_at.desc()).limit(limit)
            )
        ).all()
        a_res = (
            await self.session.execute(app_stmt.order_by(DealAppeal.created_at.desc()).limit(limit))
        ).all()

        combined = []
        for r in d_res + dp_res + w_res + a_res:
            combined.append(
                {
                    "type": r.type.lower(),
                    "entity_id": r.entity_id,
                    "public_id": r.public_id,
                    "description": r.description,
                    "created_at": r.created_at,
                }
            )

        combined.sort(key=lambda x: x["created_at"], reverse=True)
        return combined[:limit]
