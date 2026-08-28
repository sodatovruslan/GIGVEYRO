import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.fees import FeeType
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.fees import FeePolicy, FeePolicyComponent, FeeSnapshot, OwnerProfitEntry
from app.models.fiat_wallet import FiatConversion, FiatLedgerEntry, FiatWalletBalance
from app.repositories.account import AccountRepository
from app.repositories.fees import FeeRepository
from app.repositories.fiat_wallet import (
    FiatConversionRepository,
    FiatLedgerRepository,
    FiatWalletRepository,
)
from app.services.fees import FeePolicyService, FeeTerms
from app.services.fiat_wallet import FiatWalletService
from tests.test_fiat_wallet_concurrency import FixedRates


async def test_conversion_keeps_one_policy_snapshot_when_activation_races():
    policy_locked = asyncio.Event()
    release_conversion = asyncio.Event()

    class SignalingFeeRepository(FeeRepository):
        async def active_policy(self, *, lock: bool = False):
            policy = await super().active_policy(lock=lock)
            if lock:
                policy_locked.set()
                await release_conversion.wait()
            return policy

    async with AsyncSessionLocal() as session:
        owner = Account(
            username=f"fee_conc_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("FeeConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Fee Concurrency Owner",
            is_active=True,
        )
        user = Account(
            username=f"fee_conc_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("FeeConcurrencyUser123"),
            role=UserRole.USER,
            full_name="Fee Concurrency User",
            is_active=True,
        )
        session.add_all([owner, user])
        await session.flush()
        fees = FeeRepository(session)
        terms = {fee_type: FeeTerms(False, 0, Decimal("0")) for fee_type in FeeType}
        terms[FeeType.FIAT_CONVERSION] = FeeTerms(True, 100, Decimal("0"), payer="USER")
        draft = await FeePolicyService(fees).create(owner, terms)
        service = FiatWalletService(
            wallets=FiatWalletRepository(session),
            ledger=FiatLedgerRepository(session),
            conversions=FiatConversionRepository(session),
            accounts=AccountRepository(session),
            rates=FixedRates(),
            fees=fees,
        )
        await service.allocate(
            actor=owner,
            target_account_id=user.id,
            currency=Currency.TJS,
            amount=Decimal("100"),
            comment=None,
            idempotency_key="fee-policy-race-seed",
        )
        await session.commit()
        owner_id, user_id, draft_id = owner.id, user.id, draft.id

    async def convert():
        async with AsyncSessionLocal() as session:
            repository = SignalingFeeRepository(session)
            service = FiatWalletService(
                wallets=FiatWalletRepository(session),
                ledger=FiatLedgerRepository(session),
                conversions=FiatConversionRepository(session),
                accounts=AccountRepository(session),
                rates=FixedRates(),
                fees=repository,
            )
            owner = await AccountRepository(session).get_by_id(owner_id)
            conversion, _ = await service.convert(
                actor=owner,
                target_account_id=user_id,
                from_currency=Currency.TJS,
                to_currency=Currency.RUB,
                source_amount=Decimal("10"),
                comment=None,
                idempotency_key="fee-policy-race-conversion",
            )
            await session.commit()
            return conversion.id, conversion.fee_policy_version, conversion.fee_amount

    async def activate():
        await policy_locked.wait()
        async with AsyncSessionLocal() as session:
            owner = await AccountRepository(session).get_by_id(owner_id)
            policy = await FeePolicyService(FeeRepository(session)).activate(owner, draft_id)
            await session.commit()
            return policy.version

    conversion_task = asyncio.create_task(convert())
    activation_task = asyncio.create_task(activate())
    await policy_locked.wait()
    await asyncio.sleep(0.1)
    assert not activation_task.done()
    release_conversion.set()
    (conversion_id, snapshot_version, fee_amount), active_version = await asyncio.gather(
        conversion_task, activation_task
    )
    assert snapshot_version == 1
    assert fee_amount == Decimal("0")
    assert active_version == 2

    async with AsyncSessionLocal() as session:
        snapshot = await session.scalar(
            select(FeeSnapshot).where(FeeSnapshot.source_id == conversion_id)
        )
        assert snapshot.policy_version == 1
        assert snapshot.fee_amount == 0
        await session.execute(
            delete(OwnerProfitEntry).where(OwnerProfitEntry.source_id == conversion_id)
        )
        await session.execute(delete(FeeSnapshot).where(FeeSnapshot.source_id == conversion_id))
        await session.execute(delete(FiatLedgerEntry).where(FiatLedgerEntry.account_id == user_id))
        await session.execute(delete(FiatConversion).where(FiatConversion.account_id == user_id))
        await session.execute(
            delete(FiatWalletBalance).where(FiatWalletBalance.account_id == user_id)
        )
        await session.execute(
            update(FeePolicy).where(FeePolicy.id == draft_id).values(status="retired")
        )
        await session.flush()
        await session.execute(
            update(FeePolicy).where(FeePolicy.version == 1).values(status="active")
        )
        await session.execute(
            delete(FeePolicyComponent).where(FeePolicyComponent.policy_id == draft_id)
        )
        await session.execute(delete(FeePolicy).where(FeePolicy.id == draft_id))
        await session.execute(delete(Account).where(Account.id.in_([owner_id, user_id])))
        await session.commit()
