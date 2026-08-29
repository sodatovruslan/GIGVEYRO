import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.payout import PayoutApprovalDecision, PayoutStatus
from app.enums.wallet import Currency, LedgerEntryType
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.ledger import LedgerEntry
from app.models.merchant_wallet import MerchantWallet
from app.models.payout import PayoutApproval, PayoutEvent, PayoutIntent
from app.models.realtime import RealtimeOutbox
from app.models.risk import TreasurySnapshotRecord
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.payout import PayoutRepository
from app.repositories.risk import RiskRepository
from app.services.payout import PayoutTransitionError, intent_hash
from app.services.payout_runtime import build_controlled_payout_service


async def _setup_queued_payout() -> dict[str, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        owner = Account(
            username=f"payout_race_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("PayoutRaceOwner123"),
            role=UserRole.OWNER,
            full_name="Payout Race Owner",
            is_active=True,
        )
        merchant = Account(
            username=f"payout_race_merchant_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("PayoutRaceMerchant123"),
            role=UserRole.MERCHANT,
            full_name="Payout Race Merchant",
            is_active=True,
        )
        session.add_all([owner, merchant])
        await session.flush()

        wallet = MerchantWallet(
            account_id=merchant.id,
            currency=Currency.USDT,
            available_balance=Decimal("0"),
            held_balance=Decimal("25"),
        )
        session.add(wallet)
        await session.flush()
        withdrawal = MerchantWithdrawal(
            public_id=f"PW{uuid.uuid4().hex[:12].upper()}",
            merchant_id=merchant.id,
            merchant_wallet_id=wallet.id,
            amount=Decimal("25"),
            currency=Currency.USDT,
            destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
            destination="T" * 34,
            status=WithdrawalStatus.APPROVED,
            created_by_account_id=merchant.id,
            actioned_by_account_id=owner.id,
            approved_at=datetime.now(UTC),
        )
        session.add(withdrawal)
        await session.flush()

        payout_policy = await PayoutRepository(session).active_policy()
        payout_policy.payouts_enabled = True
        risk_policy = await RiskRepository(session).active_policy()
        snapshot = TreasurySnapshotRecord(
            external_observed_at=datetime.now(UTC),
            provider_status="connected",
            external_bybit_usdt=Decimal("100000"),
            external_bybit_usdc=Decimal("0"),
            internal_user_liability_usdt=Decimal("0"),
            merchant_liability_usdt=Decimal("25"),
            frozen_usdt=Decimal("0"),
            pending_withdrawal_usdt=Decimal("25"),
            open_deal_exposure_usdt=Decimal("0"),
            owner_profit_usdt=Decimal("0"),
            required_reserve_usdt=Decimal("25"),
            reserve_surplus_usdt=Decimal("99975"),
            reserve_deficit_usdt=Decimal("0"),
            coverage_ratio_bps=40000000,
            risk_status="healthy",
            policy_version=risk_policy.version,
        )
        session.add(snapshot)
        await session.flush()

        intent = PayoutIntent(
            withdrawal_id=withdrawal.id,
            requester_account_id=merchant.id,
            beneficiary_account_id=merchant.id,
            asset="USDT",
            amount=Decimal("25"),
            network="TRC20",
            destination=withdrawal.destination,
            masked_destination="TTTT…TTTT",
            fee_amount=Decimal("0"),
            risk_policy_version=risk_policy.version,
            risk_decision="allow",
            treasury_generated_at=datetime.now(UTC),
            approval_policy_version=payout_policy.version,
            required_approvals=1,
            provider_mode="simulated",
            status=PayoutStatus.QUEUED.value,
            idempotency_key=f"withdrawal:{withdrawal.id}",
            intent_hash="pending",
            simulation_outcome="succeeded",
            queued_at=datetime.now(UTC),
        )
        intent.intent_hash = intent_hash(intent)
        session.add(intent)
        await session.flush()
        session.add(
            PayoutApproval(
                payout_intent_id=intent.id,
                approver_account_id=owner.id,
                decision=PayoutApprovalDecision.APPROVED.value,
                intent_hash=intent.intent_hash,
            )
        )
        await session.commit()
        return {
            "owner": owner.id,
            "merchant": merchant.id,
            "wallet": wallet.id,
            "withdrawal": withdrawal.id,
            "intent": intent.id,
            "snapshot": snapshot.id,
        }


async def _cleanup(ids: dict[str, uuid.UUID]) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(RealtimeOutbox).where(
                RealtimeOutbox.entity_id.in_((ids["intent"], ids["withdrawal"]))
            )
        )
        await session.execute(
            delete(AuditLog).where(AuditLog.entity_id == str(ids["intent"]))
        )
        await session.execute(
            delete(PayoutEvent).where(PayoutEvent.payout_intent_id == ids["intent"])
        )
        await session.execute(
            delete(PayoutApproval).where(PayoutApproval.payout_intent_id == ids["intent"])
        )
        await session.execute(delete(PayoutIntent).where(PayoutIntent.id == ids["intent"]))
        await session.execute(
            delete(LedgerEntry).where(LedgerEntry.reference_id == ids["withdrawal"])
        )
        await session.execute(
            delete(MerchantWithdrawal).where(MerchantWithdrawal.id == ids["withdrawal"])
        )
        await session.execute(delete(MerchantWallet).where(MerchantWallet.id == ids["wallet"]))
        await session.execute(
            delete(TreasurySnapshotRecord).where(TreasurySnapshotRecord.id == ids["snapshot"])
        )
        await session.execute(
            delete(Account).where(Account.id.in_((ids["owner"], ids["merchant"])))
        )
        policy = await PayoutRepository(session).active_policy()
        policy.payouts_enabled = False
        await session.commit()


async def test_two_workers_execute_one_payout_exactly_once(monkeypatch):
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "simulated")
    monkeypatch.setattr(settings, "PAYOUT_SIMULATION_ENABLED", True)
    ids = await _setup_queued_payout()

    async def execute() -> str:
        async with AsyncSessionLocal() as session:
            result = await build_controlled_payout_service(session).execute(
                ids["intent"], ids["owner"]
            )
            await session.commit()
            return result.status

    try:
        assert await asyncio.gather(execute(), execute()) == ["succeeded", "succeeded"]
        async with AsyncSessionLocal() as session:
            wallet = await session.get(MerchantWallet, ids["wallet"])
            assert wallet is not None
            assert wallet.held_balance == Decimal("0")
            count = await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(
                    LedgerEntry.reference_id == ids["withdrawal"],
                    LedgerEntry.type == LedgerEntryType.WITHDRAWAL_PAID,
                )
            )
            assert count == 1
    finally:
        await _cleanup(ids)


async def test_concurrent_cancel_and_execute_has_one_financial_outcome(monkeypatch):
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "simulated")
    monkeypatch.setattr(settings, "PAYOUT_SIMULATION_ENABLED", True)
    ids = await _setup_queued_payout()

    async def execute() -> str:
        async with AsyncSessionLocal() as session:
            try:
                result = await build_controlled_payout_service(session).execute(
                    ids["intent"], ids["owner"]
                )
                await session.commit()
                return result.status
            except PayoutTransitionError:
                await session.rollback()
                return "blocked"

    async def cancel() -> str:
        async with AsyncSessionLocal() as session:
            owner = await AccountRepository(session).get_by_id(ids["owner"])
            try:
                result = await build_controlled_payout_service(session).cancel(
                    ids["intent"], owner
                )
                await session.commit()
                return result.status
            except PayoutTransitionError:
                await session.rollback()
                return "blocked"

    try:
        outcomes = await asyncio.gather(execute(), cancel())
        assert sorted(outcomes) in (["blocked", "cancelled"], ["blocked", "succeeded"])
        async with AsyncSessionLocal() as session:
            intent = await session.get(PayoutIntent, ids["intent"])
            withdrawal = await session.get(MerchantWithdrawal, ids["withdrawal"])
            wallet = await session.get(MerchantWallet, ids["wallet"])
            assert intent is not None and withdrawal is not None and wallet is not None
            assert intent.status in (PayoutStatus.CANCELLED, PayoutStatus.SUCCEEDED)
            assert wallet.held_balance == Decimal("0")
            assert (withdrawal.status, wallet.available_balance) in (
                (WithdrawalStatus.CANCELLED, Decimal("25")),
                (WithdrawalStatus.PAID, Decimal("0")),
            )
            entries = await session.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.reference_id == ids["withdrawal"])
            )
            assert entries == 1
    finally:
        await _cleanup(ids)
