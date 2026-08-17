import asyncio
import uuid

from sqlalchemy import delete

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.payment_requisite import PaymentRequisiteType
from app.models.account import Account
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.repositories.account import AccountRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.services.payment_requisite import PaymentRequisiteService
from app.services.traffic import TrafficNotEligibleError, TrafficService


async def test_enable_traffic_races_last_requisite_deactivation_without_violating_invariant():
    """Concurrently: (1) enable traffic, (2) deactivate the user's only
    active requisite. Whichever transaction commits first, the invariant
    "traffic enabled implies at least one active requisite" must hold once
    both have finished - never enabled=True with zero eligible requisites.
    Needs two real, independent connections (unlike the shared, rolled-back
    db_session fixture) to exercise the row lock.
    """
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        traffic_repo = TrafficRepository(setup_session)
        requisite_repo = PaymentRequisiteRepository(setup_session)

        user = Account(
            username=f"race_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("RaceTest123"),
            role=UserRole.USER,
            full_name="Race Test User",
            is_active=True,
        )
        await account_repo.create(user)

        await traffic_repo.create(UserTrafficSettings(account_id=user.id, is_enabled=False))

        requisite = PaymentRequisite(
            account_id=user.id,
            type=PaymentRequisiteType.BANK_CARD,
            bank_name="Race Bank",
            holder_name="Race Holder",
            card_number="4111111111119999",
            is_active=True,
            is_archived=False,
        )
        await requisite_repo.create(requisite)

        await setup_session.commit()
        user_id = user.id
        requisite_id = requisite.id

    async def try_enable() -> None:
        async with AsyncSessionLocal() as session:
            service = TrafficService(
                TrafficRepository(session),
                PaymentRequisiteRepository(session),
                AccountRepository(session),
            )
            try:
                await service.enable_traffic(user_id)
            except TrafficNotEligibleError:
                pass
            await session.commit()

    async def deactivate_requisite() -> None:
        async with AsyncSessionLocal() as session:
            traffic_service = TrafficService(
                TrafficRepository(session),
                PaymentRequisiteRepository(session),
                AccountRepository(session),
            )
            requisite_service = PaymentRequisiteService(
                PaymentRequisiteRepository(session), traffic_service, AccountRepository(session)
            )
            await requisite_service.deactivate(user_id, requisite_id)
            await session.commit()

    try:
        await asyncio.gather(try_enable(), deactivate_requisite())

        async with AsyncSessionLocal() as verify_session:
            traffic = await TrafficRepository(verify_session).get_by_account_id(user_id)
            eligible_count = await PaymentRequisiteRepository(verify_session).count_eligible(
                user_id
            )

            assert not (traffic.is_enabled and eligible_count == 0), (
                f"invariant violated: is_enabled={traffic.is_enabled}, "
                f"eligible_count={eligible_count}"
            )
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(PaymentRequisite).where(PaymentRequisite.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(UserTrafficSettings).where(UserTrafficSettings.account_id == user_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == user_id))
            await cleanup_session.commit()
