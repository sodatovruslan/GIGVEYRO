import asyncio
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy import delete

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.user_withdrawal import UserWithdrawal
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.user_withdrawal import UserWithdrawalRepository
from app.repositories.wallet import WalletRepository
from app.services.user_withdrawal import InvalidWithdrawalTransitionError, UserWithdrawalService
from app.services.wallet import WalletService


@asynccontextmanager
async def _bootstrap(available: Decimal = Decimal("100")):
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)

        user = Account(
            username=f"uwconc_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Concurrency Test User",
            is_active=True,
        )
        await account_repo.create(user)

        owner = Account(
            username=f"uwconc_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Concurrency Test Owner",
            is_active=True,
        )
        await account_repo.create(owner)

        wallet = UserWallet(account_id=user.id, available_balance=available)
        await wallet_repo.create(wallet)

        withdrawal = UserWithdrawal(
            public_id=f"UWD-{uuid.uuid4().hex[:8].upper()}",
            user_id=user.id,
            wallet_id=wallet.id,
            amount=Decimal("30"),
            destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
            destination="T" + "a" * 33,
            status=WithdrawalStatus.PENDING,
            created_by_account_id=user.id,
        )
        setup_session.add(withdrawal)
        await setup_session.flush()

        wallet.available_balance = available - withdrawal.amount
        wallet.frozen_balance = withdrawal.amount
        await setup_session.commit()

        withdrawal_id = withdrawal.id
        user_id = user.id
        owner_id = owner.id

    try:
        yield withdrawal_id, user_id, owner_id
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(UserWithdrawal).where(UserWithdrawal.id == withdrawal_id)
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(Account).where(Account.id.in_([user_id, owner_id]))
            )
            await cleanup_session.commit()


def _service(session) -> UserWithdrawalService:
    account_repo = AccountRepository(session)
    wallet_service = WalletService(WalletRepository(session), LedgerRepository(session), account_repo)
    return UserWithdrawalService(
        withdrawal_repository=UserWithdrawalRepository(session),
        wallet_service=wallet_service,
        account_repository=account_repo,
    )


async def _approve(withdrawal_id, owner_id) -> str:
    async with AsyncSessionLocal() as session:
        try:
            withdrawal = await _service(session).approve_by_owner(owner_id, withdrawal_id)
            await session.commit()
            return withdrawal.status.value
        except InvalidWithdrawalTransitionError:
            await session.rollback()
            return "rejected_by_state_machine"


async def _reject(withdrawal_id, owner_id) -> str:
    async with AsyncSessionLocal() as session:
        try:
            withdrawal = await _service(session).reject_by_owner(owner_id, withdrawal_id)
            await session.commit()
            return withdrawal.status.value
        except InvalidWithdrawalTransitionError:
            await session.rollback()
            return "rejected_by_state_machine"


async def _cancel(withdrawal_id, user_id) -> str:
    async with AsyncSessionLocal() as session:
        try:
            withdrawal = await _service(session).cancel_by_user(user_id, withdrawal_id)
            await session.commit()
            return withdrawal.status.value
        except InvalidWithdrawalTransitionError:
            await session.rollback()
            return "rejected_by_state_machine"


async def _mark_paid(withdrawal_id, owner_id) -> str:
    async with AsyncSessionLocal() as session:
        try:
            withdrawal = await _service(session).mark_paid_by_owner(owner_id, withdrawal_id)
            await session.commit()
            return withdrawal.status.value
        except InvalidWithdrawalTransitionError:
            await session.rollback()
            return "rejected_by_state_machine"


async def test_concurrent_double_approve_does_not_duplicate_transition():
    async with _bootstrap() as (withdrawal_id, user_id, owner_id):
        results = await asyncio.gather(
            _approve(withdrawal_id, owner_id), _approve(withdrawal_id, owner_id)
        )
        # Both calls succeed (the second is an idempotent no-op returning
        # the already-approved state), never an inconsistent result.
        assert results == ["approved", "approved"]

        async with AsyncSessionLocal() as verify_session:
            withdrawal = await UserWithdrawalRepository(verify_session).get_by_id(withdrawal_id)
            assert withdrawal.status == WithdrawalStatus.APPROVED


async def test_concurrent_cancel_vs_approve_is_deterministic():
    async with _bootstrap() as (withdrawal_id, user_id, owner_id):
        results = await asyncio.gather(
            _cancel(withdrawal_id, user_id), _approve(withdrawal_id, owner_id)
        )
        # Exactly one side wins the race; the other observes the
        # already-transitioned state and is rejected by the state machine -
        # never both "succeeding" into two different terminal states.
        outcomes = set(results)
        assert outcomes in ({"cancelled", "rejected_by_state_machine"}, {"approved", "rejected_by_state_machine"})
        assert results.count("rejected_by_state_machine") == 1

        async with AsyncSessionLocal() as verify_session:
            withdrawal = await UserWithdrawalRepository(verify_session).get_by_id(withdrawal_id)
            assert withdrawal.status.value in results

            wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            if withdrawal.status == WithdrawalStatus.CANCELLED:
                assert wallet.available_balance == Decimal("100")
                assert wallet.frozen_balance == Decimal("0")
            else:
                assert wallet.available_balance == Decimal("70")
                assert wallet.frozen_balance == Decimal("30")


async def test_concurrent_reject_vs_cancel_is_deterministic():
    async with _bootstrap() as (withdrawal_id, user_id, owner_id):
        results = await asyncio.gather(
            _reject(withdrawal_id, owner_id), _cancel(withdrawal_id, user_id)
        )
        outcomes = set(results)
        assert outcomes in ({"rejected", "rejected_by_state_machine"}, {"cancelled", "rejected_by_state_machine"})
        assert results.count("rejected_by_state_machine") == 1

        async with AsyncSessionLocal() as verify_session:
            # Funds released exactly once regardless of which side won.
            wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert wallet.available_balance == Decimal("100")
            assert wallet.frozen_balance == Decimal("0")

            entries = await LedgerRepository(verify_session).list_for_account(
                account_id=user_id,
                entry_type=LedgerEntryType.WITHDRAWAL_RELEASE,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(entries) == 1


async def test_concurrent_double_mark_paid_does_not_double_spend():
    async with _bootstrap() as (withdrawal_id, user_id, owner_id):
        async with AsyncSessionLocal() as session:
            withdrawal = await _service(session).approve_by_owner(owner_id, withdrawal_id)
            await session.commit()
            assert withdrawal.status == WithdrawalStatus.APPROVED

        results = await asyncio.gather(
            _mark_paid(withdrawal_id, owner_id), _mark_paid(withdrawal_id, owner_id)
        )
        assert results == ["paid", "paid"]

        async with AsyncSessionLocal() as verify_session:
            wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            # The 30 that was frozen is gone entirely - not doubly deducted,
            # not returned to available.
            assert wallet.available_balance == Decimal("70")
            assert wallet.frozen_balance == Decimal("0")

            entries = await LedgerRepository(verify_session).list_for_account(
                account_id=user_id,
                entry_type=LedgerEntryType.WITHDRAWAL_PAID,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(entries) == 1


async def test_concurrent_mark_paid_vs_cancel_after_approval_is_safe():
    """APPROVED only allows -> PAID in this codebase (no owner cancel-after-
    approval path exists for either withdrawal type - see final report).
    A user CANCEL attempt on an already-APPROVED withdrawal must simply be
    rejected by the state machine, concurrently with a real PAID, without
    corrupting the ledger."""
    async with _bootstrap() as (withdrawal_id, user_id, owner_id):
        async with AsyncSessionLocal() as session:
            await _service(session).approve_by_owner(owner_id, withdrawal_id)
            await session.commit()

        results = await asyncio.gather(
            _mark_paid(withdrawal_id, owner_id), _cancel(withdrawal_id, user_id)
        )

        assert "paid" in results
        assert "rejected_by_state_machine" in results

        async with AsyncSessionLocal() as verify_session:
            wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert wallet.available_balance == Decimal("70")
            assert wallet.frozen_balance == Decimal("0")
