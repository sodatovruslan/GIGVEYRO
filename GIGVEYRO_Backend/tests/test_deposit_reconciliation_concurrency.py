import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositNetwork,
    DepositStatus,
    ReconciliationStatus,
)
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.deposit import Deposit, DepositReconciliationAction, UnmatchedTransfer
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.services.audit import AuditService
from app.services.deposit import DepositService, generate_deposit_public_id
from app.services.deposit_provider import MockTRC20DepositProvider, OnChainTransactionDTO
from app.services.deposit_reconciliation import DepositReconciliationService
from app.services.wallet import WalletService


async def _setup(target_count: int = 2):
    async with AsyncSessionLocal() as session:
        owner = Account(
            username=f"reconcile_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Concurrency Owner",
        )
        session.add(owner)
        users: list[Account] = []
        deposits: list[Deposit] = []
        for index in range(target_count):
            user = Account(
                username=f"reconcile_user_{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("ConcurrencyUser123"),
                role=UserRole.USER,
                full_name=f"Concurrency User {index}",
            )
            session.add(user)
            await session.flush()
            session.add(UserWallet(account_id=user.id, available_balance=Decimal("0")))
            deposit = Deposit(
                public_id=generate_deposit_public_id(),
                account_id=user.id,
                network=DepositNetwork.TRC20,
                asset=DepositAsset.USDT,
                expected_amount=Decimal("80"),
                deposit_address=settings.USDT_TRC20_DEPOSIT_ADDRESS,
                required_confirmations=20,
                status=DepositStatus.WAITING,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            session.add(deposit)
            users.append(user)
            deposits.append(deposit)
        await session.flush()
        tx_hash = f"reconcile-race-{uuid.uuid4().hex}"
        transfer = UnmatchedTransfer(
            tx_hash=tx_hash,
            provider_event_id=f"mock:{tx_hash}:0",
            from_address="TConcurrencySenderAddress",
            to_address=settings.USDT_TRC20_DEPOSIT_ADDRESS,
            amount=Decimal("80"),
            asset_contract=settings.USDT_TRC20_CONTRACT_ADDRESS,
            provider="mock",
            network=DepositNetwork.TRC20,
            confirmations=20,
            is_finalized=True,
            correlation_status=CorrelationStatus.AMBIGUOUS,
            reconciliation_status=ReconciliationStatus.PENDING,
            reason="concurrency test",
        )
        session.add(transfer)
        await session.commit()
        return owner.id, [user.id for user in users], [item.id for item in deposits], transfer.id


def _services(session):
    deposits = DepositRepository(session)
    accounts = AccountRepository(session)
    credit = DepositService(
        deposits,
        accounts,
        WalletService(WalletRepository(session), LedgerRepository(session), accounts),
        MockTRC20DepositProvider(),
    )
    reconciliation = DepositReconciliationService(
        deposits, credit, AuditService(AuditRepository(session))
    )
    return credit, reconciliation


async def _link(owner_id, transfer_id, deposit_id, key):
    async with AsyncSessionLocal() as session:
        _, service = _services(session)
        owner = await session.get(Account, owner_id)
        try:
            result = await service.link(transfer_id, deposit_id, owner, key)
            await session.commit()
            return result.result_code
        except Exception as exc:  # competing action is expected to lose safely
            await session.rollback()
            return type(exc).__name__


async def _ignore(owner_id, transfer_id, key):
    async with AsyncSessionLocal() as session:
        _, service = _services(session)
        owner = await session.get(Account, owner_id)
        try:
            result = await service.ignore(transfer_id, owner, "Concurrent investigation", key)
            await session.commit()
            return result.result_code
        except Exception as exc:
            await session.rollback()
            return type(exc).__name__


async def _reprocess(owner_id, transfer_id, key):
    async with AsyncSessionLocal() as session:
        _, service = _services(session)
        owner = await session.get(Account, owner_id)
        try:
            result = await service.reprocess(transfer_id, owner, key)
            await session.commit()
            return result.result_code
        except Exception as exc:
            await session.rollback()
            return type(exc).__name__


async def _verify_single_outcome(user_ids, deposit_ids, transfer_id):
    async with AsyncSessionLocal() as session:
        balance = await session.scalar(
            select(func.coalesce(func.sum(UserWallet.available_balance), 0)).where(
                UserWallet.account_id.in_(user_ids)
            )
        )
        ledger_count = await session.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.account_id.in_(user_ids))
        )
        credited_count = await session.scalar(
            select(func.count())
            .select_from(Deposit)
            .where(Deposit.id.in_(deposit_ids), Deposit.status == DepositStatus.CREDITED)
        )
        assert balance in {Decimal("0"), Decimal("80")}
        assert ledger_count <= 1
        assert credited_count <= 1
        transfer = await session.get(UnmatchedTransfer, transfer_id)
        return balance, ledger_count, transfer.reconciliation_status


async def _cleanup(owner_id, user_ids, deposit_ids, transfer_id):
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DepositReconciliationAction).where(
                DepositReconciliationAction.transfer_id == transfer_id
            )
        )
        await session.execute(delete(AuditLog).where(AuditLog.entity_id == str(transfer_id)))
        await session.execute(delete(LedgerEntry).where(LedgerEntry.account_id.in_(user_ids)))
        await session.execute(delete(UnmatchedTransfer).where(UnmatchedTransfer.id == transfer_id))
        await session.execute(delete(Deposit).where(Deposit.id.in_(deposit_ids)))
        await session.execute(delete(UserWallet).where(UserWallet.account_id.in_(user_ids)))
        await session.execute(delete(Account).where(Account.id.in_([owner_id, *user_ids])))
        await session.commit()


async def test_same_transfer_two_links_and_two_targets_credit_at_most_once():
    owner_id, user_ids, deposit_ids, transfer_id = await _setup()
    try:
        results = await asyncio.gather(
            _link(owner_id, transfer_id, deposit_ids[0], "race-link-one"),
            _link(owner_id, transfer_id, deposit_ids[1], "race-link-two"),
        )
        assert results.count("CREDITED") == 1
        assert await _verify_single_outcome(user_ids, deposit_ids, transfer_id) == (
            Decimal("80"),
            1,
            ReconciliationStatus.CREDITED,
        )
    finally:
        await _cleanup(owner_id, user_ids, deposit_ids, transfer_id)


async def test_ignore_vs_link_has_one_terminal_outcome_and_never_double_credits():
    owner_id, user_ids, deposit_ids, transfer_id = await _setup(target_count=1)
    try:
        results = await asyncio.gather(
            _ignore(owner_id, transfer_id, "race-ignore-one"),
            _link(owner_id, transfer_id, deposit_ids[0], "race-link-ignore"),
        )
        assert len({item for item in results if item in {"IGNORED", "CREDITED"}}) == 1
        balance, ledger_count, state = await _verify_single_outcome(
            user_ids, deposit_ids, transfer_id
        )
        assert (state, balance, ledger_count) in {
            (ReconciliationStatus.IGNORED, Decimal("0"), 0),
            (ReconciliationStatus.CREDITED, Decimal("80"), 1),
        }
    finally:
        await _cleanup(owner_id, user_ids, deposit_ids, transfer_id)


async def test_reprocess_vs_link_credits_exact_candidate_once():
    owner_id, user_ids, deposit_ids, transfer_id = await _setup(target_count=1)
    try:
        results = await asyncio.gather(
            _reprocess(owner_id, transfer_id, "race-reprocess-link"),
            _link(owner_id, transfer_id, deposit_ids[0], "race-direct-link"),
        )
        assert results.count("CREDITED") == 1
        assert await _verify_single_outcome(user_ids, deposit_ids, transfer_id) == (
            Decimal("80"),
            1,
            ReconciliationStatus.CREDITED,
        )
    finally:
        await _cleanup(owner_id, user_ids, deposit_ids, transfer_id)


async def test_scanner_rediscovery_vs_owner_link_is_safe():
    owner_id, user_ids, deposit_ids, transfer_id = await _setup(target_count=1)
    async with AsyncSessionLocal() as read_session:
        transfer = await read_session.get(UnmatchedTransfer, transfer_id)
        tx = OnChainTransactionDTO(
            tx_hash=transfer.tx_hash,
            network=DepositNetwork.TRC20,
            asset_contract=transfer.asset_contract,
            from_address=transfer.from_address,
            to_address=transfer.to_address,
            amount=transfer.amount,
            confirmations=21,
            is_success=True,
            timestamp=datetime.now(UTC),
        )

    async def scan():
        async with AsyncSessionLocal() as session:
            provider = MockTRC20DepositProvider()
            provider.add_simulated_tx(tx)
            accounts = AccountRepository(session)
            service = DepositService(
                DepositRepository(session),
                accounts,
                WalletService(WalletRepository(session), LedgerRepository(session), accounts),
                provider,
            )
            await service.scan_and_correlate_deposits()
            await session.commit()

    try:
        await asyncio.gather(
            scan(), _link(owner_id, transfer_id, deposit_ids[0], "race-link-scanner")
        )
        assert await _verify_single_outcome(user_ids, deposit_ids, transfer_id) == (
            Decimal("80"),
            1,
            ReconciliationStatus.CREDITED,
        )
    finally:
        await _cleanup(owner_id, user_ids, deposit_ids, transfer_id)


async def test_worker_credit_vs_owner_link_uses_deposit_lock_and_credits_once():
    owner_id, user_ids, deposit_ids, transfer_id = await _setup(target_count=1)
    async with AsyncSessionLocal() as read_session:
        transfer = await read_session.get(UnmatchedTransfer, transfer_id)
        event = {
            "tx_hash": transfer.tx_hash,
            "amount": transfer.amount,
            "confirmations": transfer.confirmations,
            "network": transfer.network,
            "asset": DepositAsset.USDT,
            "destination_address": transfer.to_address,
            "provider_event_id": transfer.provider_event_id,
        }

    async def worker_credit():
        async with AsyncSessionLocal() as session:
            service, _ = _services(session)
            try:
                await service.ingest_transaction_event(deposit_ids[0], **event)
                await session.commit()
                return "CREDITED"
            except Exception as exc:
                await session.rollback()
                return type(exc).__name__

    try:
        await asyncio.gather(
            worker_credit(), _link(owner_id, transfer_id, deposit_ids[0], "race-link-worker")
        )
        balance, ledger_count, _ = await _verify_single_outcome(user_ids, deposit_ids, transfer_id)
        assert (balance, ledger_count) == (Decimal("80"), 1)
    finally:
        await _cleanup(owner_id, user_ids, deposit_ids, transfer_id)
