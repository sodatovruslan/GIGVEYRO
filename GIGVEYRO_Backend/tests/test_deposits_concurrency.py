import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete

from app.core.config import settings as app_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.models.account import Account
from app.models.deposit import Deposit
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.services.deposit import DepositService, generate_deposit_public_id
from app.services.deposit_provider import MockTRC20DepositProvider
from app.services.wallet import WalletService


async def test_two_simultaneous_credit_attempts_credit_exactly_once():
    """The same confirmed transaction event arrives on two independent
    connections at once (e.g. a flaky/duplicating listener). Only one may
    actually credit the wallet - needs two real, separate DB connections
    (unlike the shared, rolled-back db_session fixture) to exercise the
    deposit row lock that serializes this.
    """
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)
        deposit_repo = DepositRepository(setup_session)

        user = Account(
            username=f"race_dep_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("RaceDepositTest123"),
            role=UserRole.USER,
            full_name="Race Deposit User",
            is_active=True,
        )
        await account_repo.create(user)
        await wallet_repo.create(UserWallet(account_id=user.id, available_balance=Decimal("0")))

        deposit = Deposit(
            public_id=generate_deposit_public_id(),
            account_id=user.id,
            network=DepositNetwork.TRC20,
            asset=DepositAsset.USDT,
            expected_amount=Decimal("100"),
            deposit_address=app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
            confirmations=0,
            required_confirmations=1,
            status=DepositStatus.WAITING,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        await deposit_repo.create(deposit)

        await setup_session.commit()
        user_id = user.id
        deposit_id = deposit.id

    async def try_confirm() -> None:
        async with AsyncSessionLocal() as session:
            account_repository = AccountRepository(session)
            wallet_service = WalletService(
                WalletRepository(session), LedgerRepository(session), account_repository
            )
            service = DepositService(
                DepositRepository(session),
                account_repository,
                wallet_service,
                MockTRC20DepositProvider(),
            )
            await service.ingest_transaction_event(
                deposit_id,
                tx_hash="tx_race_credit",
                amount=Decimal("100"),
                confirmations=1,
                network=DepositNetwork.TRC20,
                asset=DepositAsset.USDT,
                destination_address=app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
            )
            await session.commit()

    try:
        await asyncio.gather(try_confirm(), try_confirm())

        async with AsyncSessionLocal() as verify_session:
            final_deposit = await DepositRepository(verify_session).get_by_id(deposit_id)
            assert final_deposit.status == DepositStatus.CREDITED
            assert final_deposit.credited_amount == Decimal("100")

            wallet = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert wallet.available_balance == Decimal("100")

            entries = await LedgerRepository(verify_session).list_for_account(
                account_id=user_id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(entries) == 1
            assert entries[0].reference_id == deposit_id
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == user_id)
            )
            await cleanup_session.execute(delete(Deposit).where(Deposit.id == deposit_id))
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == user_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == user_id))
            await cleanup_session.commit()
