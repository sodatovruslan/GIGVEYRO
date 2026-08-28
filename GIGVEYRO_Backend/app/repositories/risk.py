import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.deal import DealStatus
from app.enums.withdrawal import WithdrawalStatus
from app.models.deal import Deal
from app.models.fees import OwnerProfitEntry
from app.models.merchant_wallet import MerchantWallet
from app.models.risk import RiskPolicy, TreasurySnapshotRecord
from app.models.wallet import UserWallet

ZERO = Decimal("0")
OPEN_DEAL_STATUSES = (DealStatus.ACCEPTED, DealStatus.PAYMENT_PENDING, DealStatus.DISPUTED)
OPEN_WITHDRAWAL_STATUSES = (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED)


class RiskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_policy(self, *, lock: bool = False) -> RiskPolicy:
        query = select(RiskPolicy).where(RiskPolicy.status == "active")
        if lock:
            query = query.with_for_update(key_share=True)
        return (await self.session.execute(query)).scalar_one()

    async def policy(self, policy_id: uuid.UUID) -> RiskPolicy | None:
        return await self.session.get(RiskPolicy, policy_id)

    async def lock_policies(self) -> list[RiskPolicy]:
        return list(
            (
                await self.session.execute(
                    select(RiskPolicy).order_by(RiskPolicy.version).with_for_update()
                )
            ).scalars()
        )

    async def save_policy(self, policy: RiskPolicy) -> RiskPolicy:
        self.session.add(policy)
        await self.session.flush()
        await self.session.refresh(policy)
        return policy

    async def serialize_enforcement(self) -> None:
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(748193221)"))

    async def liabilities(self) -> dict[str, Decimal]:
        user = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(
                        UserWallet.available_balance
                        + UserWallet.insurance_balance
                        + UserWallet.frozen_balance
                    ),
                    0,
                ),
                func.coalesce(func.sum(UserWallet.frozen_balance), 0),
            )
        )
        user_total, frozen = user.one()
        merchant_total = await self.session.scalar(
            select(
                func.coalesce(
                    func.sum(MerchantWallet.available_balance + MerchantWallet.held_balance), 0
                )
            )
        )
        pending = await self.session.scalar(
            select(func.coalesce(func.sum(MerchantWithdrawal.amount), 0)).where(
                MerchantWithdrawal.status.in_(OPEN_WITHDRAWAL_STATUSES)
            )
        )
        open_deals = await self.session.scalar(
            select(func.coalesce(func.sum(Deal.amount_usdt), 0)).where(
                Deal.status.in_(OPEN_DEAL_STATUSES)
            )
        )
        profit = await self.session.scalar(
            select(func.coalesce(func.sum(OwnerProfitEntry.fee_amount), 0)).where(
                OwnerProfitEntry.currency == "USDT"
            )
        )
        return {
            "user": Decimal(user_total),
            "merchant": Decimal(merchant_total or 0),
            "frozen": Decimal(frozen),
            "pending": Decimal(pending or 0),
            "open_deals": Decimal(open_deals or 0),
            "profit": Decimal(profit or 0),
        }

    async def user_frozen(self, account_id: uuid.UUID) -> Decimal:
        value = await self.session.scalar(
            select(UserWallet.frozen_balance).where(UserWallet.account_id == account_id)
        )
        return Decimal(value or 0)

    async def latest_snapshot(self) -> TreasurySnapshotRecord | None:
        return (
            await self.session.execute(
                select(TreasurySnapshotRecord)
                .order_by(TreasurySnapshotRecord.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def add_snapshot(self, snapshot: TreasurySnapshotRecord) -> TreasurySnapshotRecord:
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def history(self, limit: int, offset: int) -> tuple[list[TreasurySnapshotRecord], int]:
        items = list(
            (
                await self.session.execute(
                    select(TreasurySnapshotRecord)
                    .order_by(TreasurySnapshotRecord.generated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        total = await self.session.scalar(select(func.count()).select_from(TreasurySnapshotRecord))
        return items, int(total or 0)


from app.models.withdrawal import MerchantWithdrawal  # noqa: E402
