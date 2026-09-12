import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import delete

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.services.wallet import WalletService


async def test_concurrent_allocations_do_not_lose_updates():
    """Two allocations racing on the same wallet, each on its own real DB
    connection/transaction (unlike the rest of the suite, this needs true
    concurrency to exercise SELECT ... FOR UPDATE, so it can't use the
    single shared, rolled-back db_session fixture). Commits for real and
    cleans up afterward.
    """
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)

        user = Account(
            username=f"conc_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Concurrency Test User",
            is_active=True,
        )
        await account_repo.create(user)

        actor = Account(
            username=f"conc_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Concurrency Test Owner",
            is_active=True,
        )
        await account_repo.create(actor)

        wallet = UserWallet(account_id=user.id, available_balance=Decimal("100"))
        await wallet_repo.create(wallet)

        await setup_session.commit()
        user_id = user.id
        actor_id = actor.id

    async def run_allocation(amount: Decimal, idempotency_key: str) -> None:
        async with AsyncSessionLocal() as session:
            actor_account = await AccountRepository(session).get_by_id(actor_id)
            service = WalletService(
                WalletRepository(session), LedgerRepository(session), AccountRepository(session)
            )
            await service.allocate(
                actor=actor_account,
                target_account_id=user_id,
                amount=amount,
                description="concurrency test",
                idempotency_key=idempotency_key,
            )
            await session.commit()

    try:
        await asyncio.gather(
            run_allocation(Decimal("50"), "conc-alloc-1"),
            run_allocation(Decimal("70"), "conc-alloc-2"),
        )

        async with AsyncSessionLocal() as verify_session:
            final_wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert final_wallet.available_balance == Decimal("220")

            entries = await LedgerRepository(verify_session).list_for_account(
                account_id=user_id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(entries) == 2
            assert {entry.amount for entry in entries} == {Decimal("50"), Decimal("70")}
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(Account).where(Account.id.in_([user_id, actor_id]))
            )
            await cleanup_session.commit()


async def test_concurrent_same_idempotency_key_applies_exactly_once():
    """Two concurrent manual_adjust calls carrying the SAME idempotency key
    (a naive client retry-on-timeout or a UI double-click) must apply the
    balance change exactly once, not twice - this is the H3 security fix."""
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)

        user = Account(
            username=f"idem_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Idempotency Test User",
            is_active=True,
        )
        await account_repo.create(user)

        actor = Account(
            username=f"idem_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Idempotency Test Owner",
            is_active=True,
        )
        await account_repo.create(actor)

        wallet = UserWallet(account_id=user.id, available_balance=Decimal("100"))
        await wallet_repo.create(wallet)

        await setup_session.commit()
        user_id = user.id
        actor_id = actor.id

    async def run_adjust() -> None:
        async with AsyncSessionLocal() as session:
            actor_account = await AccountRepository(session).get_by_id(actor_id)
            service = WalletService(
                WalletRepository(session), LedgerRepository(session), AccountRepository(session)
            )
            await service.manual_adjust(
                actor=actor_account,
                target_account_id=user_id,
                amount=Decimal("30.00"),
                reason="concurrent retry",
                idempotency_key="same-retry-key",
            )
            await session.commit()

    try:
        results = await asyncio.gather(run_adjust(), run_adjust(), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result

        async with AsyncSessionLocal() as verify_session:
            final_wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert final_wallet.available_balance == Decimal(
                "130"
            ), "the same idempotency key must not be applied twice"

            entries = await LedgerRepository(verify_session).list_for_account(
                account_id=user_id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(entries) == 1
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(Account).where(Account.id.in_([user_id, actor_id]))
            )
            await cleanup_session.commit()
