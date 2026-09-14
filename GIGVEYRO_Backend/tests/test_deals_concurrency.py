import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.deal import Deal
from app.models.ledger import LedgerEntry
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.fees import FeeRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.repositories.wallet import WalletRepository
from app.services.deal import DealNotAvailableError, DealService, generate_public_id
from app.services.exchange_rate import ConfiguredExchangeRateProvider
from app.services.wallet import WalletService


async def test_two_users_racing_to_accept_same_deal_exactly_one_wins():
    """Deal AVAILABLE, two USERs call accept concurrently on independent
    connections. Exactly one must win: Deal.user_id set to the winner only,
    USDT frozen only in the winner's wallet, exactly one DEAL_FREEZE ledger
    entry created overall. Needs two real, separate DB connections (unlike
    the shared, rolled-back db_session fixture) to exercise the deal row
    lock that serializes the race.
    """
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)
        requisite_repo = PaymentRequisiteRepository(setup_session)
        traffic_repo = TrafficRepository(setup_session)
        deal_repo = DealRepository(setup_session)

        merchant = Account(
            username=f"race_merchant_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("RaceMerchant123"),
            role=UserRole.MERCHANT,
            full_name="Race Merchant",
            is_active=True,
        )
        await account_repo.create(merchant)

        users = []
        requisites = []
        for label in ("a", "b"):
            user = Account(
                username=f"race_user_{label}_{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("RaceUser123"),
                role=UserRole.USER,
                full_name=f"Race User {label}",
                is_active=True,
            )
            await account_repo.create(user)
            await wallet_repo.create(
                UserWallet(
                    account_id=user.id, currency=Currency.USDT, available_balance=Decimal("500")
                )
            )
            requisite = PaymentRequisite(
                account_id=user.id,
                type=PaymentRequisiteType.BANK_CARD,
                bank_name="Race Bank",
                holder_name=f"Race Holder {label}",
                card_number=f"411111111111{label}999" if label == "a" else "4111111111119998",
                is_active=True,
                is_archived=False,
            )
            await requisite_repo.create(requisite)
            await traffic_repo.create(UserTrafficSettings(account_id=user.id, is_enabled=True))
            users.append(user)
            requisites.append(requisite)

        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            amount_tjs=Decimal("200"),
            status=DealStatus.AVAILABLE,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        await deal_repo.create(deal)

        await setup_session.commit()
        merchant_id = merchant.id
        user_ids = [u.id for u in users]
        requisite_ids = [r.id for r in requisites]
        deal_id = deal.id

    async def try_accept(user_id: uuid.UUID, requisite_id: uuid.UUID) -> str:
        async with AsyncSessionLocal() as session:
            account_repository = AccountRepository(session)
            account = await account_repository.get_by_id(user_id)
            wallet_service = WalletService(
                WalletRepository(session), LedgerRepository(session), account_repository
            )
            service = DealService(
                DealRepository(session),
                PaymentRequisiteRepository(session),
                TrafficRepository(session),
                account_repository,
                wallet_service,
                ConfiguredExchangeRateProvider(),
                FeeRepository(session),
            )
            try:
                await service.accept_deal(
                    account=account, deal_id=deal_id, requisite_id=requisite_id
                )
                await session.commit()
                return "won"
            except DealNotAvailableError:
                await session.rollback()
                return "lost"

    try:
        results = await asyncio.gather(
            try_accept(user_ids[0], requisite_ids[0]),
            try_accept(user_ids[1], requisite_ids[1]),
        )

        assert sorted(results) == ["lost", "won"]
        winner_index = results.index("won")
        winner_id = user_ids[winner_index]
        loser_id = user_ids[1 - winner_index]

        async with AsyncSessionLocal() as verify_session:
            final_deal = await DealRepository(verify_session).get_by_id(deal_id)
            assert final_deal.status == DealStatus.ACCEPTED
            assert final_deal.user_id == winner_id

            winner_wallet = await WalletRepository(verify_session).get_by_account_id(winner_id)
            loser_wallet = await WalletRepository(verify_session).get_by_account_id(loser_id)

            assert winner_wallet.available_balance < Decimal("500")
            assert winner_wallet.frozen_balance > Decimal("0")
            assert loser_wallet.available_balance == Decimal("500")
            assert loser_wallet.frozen_balance == Decimal("0")

            freeze_entries = await LedgerRepository(verify_session).list_for_account(
                account_id=winner_id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(freeze_entries) == 1
            assert freeze_entries[0].reference_id == deal_id

            loser_entries = await LedgerRepository(verify_session).list_for_account(
                account_id=loser_id,
                entry_type=None,
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )
            assert len(loser_entries) == 0
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id.in_(user_ids))
            )
            await cleanup_session.execute(delete(Deal).where(Deal.id == deal_id))
            await cleanup_session.execute(
                delete(PaymentRequisite).where(PaymentRequisite.account_id.in_(user_ids))
            )
            await cleanup_session.execute(
                delete(UserTrafficSettings).where(UserTrafficSettings.account_id.in_(user_ids))
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id.in_(user_ids))
            )
            await cleanup_session.execute(
                delete(Account).where(Account.id.in_([*user_ids, merchant_id]))
            )
            await cleanup_session.commit()
