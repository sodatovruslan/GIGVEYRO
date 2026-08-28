import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.fees import FeeSnapshot, OwnerProfitEntry
from app.models.fiat_wallet import FiatConversion, FiatLedgerEntry, FiatWalletBalance
from app.repositories.account import AccountRepository
from app.repositories.fees import FeeRepository
from app.repositories.fiat_wallet import (
    FiatConversionRepository,
    FiatLedgerRepository,
    FiatWalletRepository,
)
from app.services.fiat_rate.models import FiatConversionQuote, FiatSourceType
from app.services.fiat_wallet import FiatInsufficientBalanceError, FiatWalletService


class FixedRates:
    async def get_quote(
        self, from_currency: Currency, to_currency: Currency
    ) -> FiatConversionQuote:
        now = datetime.now(UTC)
        rate = Decimal("10") if from_currency == Currency.TJS else Decimal("0.1")
        return FiatConversionQuote(
            from_currency=from_currency.value,
            to_currency=to_currency.value,
            rate=rate,
            provider="nbt",
            published_at=now,
            received_at=now,
            source_type=FiatSourceType.OFFICIAL,
            provider_nominal=Decimal("1"),
            provider_rate=Decimal("0.1"),
            policy_version="concurrency-v1",
            mode="official",
            is_stale=False,
        )


def _service(session) -> FiatWalletService:
    return FiatWalletService(
        wallets=FiatWalletRepository(session),
        ledger=FiatLedgerRepository(session),
        conversions=FiatConversionRepository(session),
        accounts=AccountRepository(session),
        rates=FixedRates(),
        fees=FeeRepository(session),
    )


async def _setup(initial_tjs: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        user = Account(
            username=f"fiat_conc_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyUser123"),
            role=UserRole.USER,
            full_name="Fiat Concurrency User",
            is_active=True,
        )
        owner = Account(
            username=f"fiat_conc_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Fiat Concurrency Owner",
            is_active=True,
        )
        session.add_all([user, owner])
        await session.flush()
        await _service(session).allocate(
            actor=owner,
            target_account_id=user.id,
            currency=Currency.TJS,
            amount=Decimal(initial_tjs),
            comment="seed",
            idempotency_key=f"seed-{uuid.uuid4()}",
        )
        await session.commit()
        return user.id, owner.id


async def _cleanup(user_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        conversion_ids = select(FiatConversion.id).where(FiatConversion.account_id == user_id)
        await session.execute(
            delete(OwnerProfitEntry).where(OwnerProfitEntry.source_id.in_(conversion_ids))
        )
        await session.execute(delete(FeeSnapshot).where(FeeSnapshot.source_id.in_(conversion_ids)))
        await session.execute(delete(FiatLedgerEntry).where(FiatLedgerEntry.account_id == user_id))
        await session.execute(delete(FiatConversion).where(FiatConversion.account_id == user_id))
        await session.execute(
            delete(FiatWalletBalance).where(FiatWalletBalance.account_id == user_id)
        )
        await session.execute(delete(Account).where(Account.id.in_([user_id, owner_id])))
        await session.commit()


async def _convert(
    user_id: uuid.UUID, owner_id: uuid.UUID, amount: str, key: str
) -> uuid.UUID | None:
    async with AsyncSessionLocal() as session:
        owner = await AccountRepository(session).get_by_id(owner_id)
        try:
            conversion, _ = await _service(session).convert(
                actor=owner,
                target_account_id=user_id,
                from_currency=Currency.TJS,
                to_currency=Currency.RUB,
                source_amount=Decimal(amount),
                comment=None,
                idempotency_key=key,
            )
            await session.commit()
            return conversion.id
        except FiatInsufficientBalanceError:
            await session.rollback()
            return None


async def test_two_conversions_racing_cannot_double_spend_or_go_negative():
    user_id, owner_id = await _setup("100")
    try:
        results = await asyncio.gather(
            _convert(user_id, owner_id, "80", "race-convert-a"),
            _convert(user_id, owner_id, "80", "race-convert-b"),
        )
        assert sum(item is not None for item in results) == 1
        async with AsyncSessionLocal() as session:
            balances = {
                item.currency: item.available
                for item in await FiatWalletRepository(session).list_balances(user_id)
            }
            assert balances[Currency.TJS] == Decimal("20")
            assert balances[Currency.RUB] == Decimal("800")
            assert all(value >= 0 for value in balances.values())
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FiatConversion)
                    .where(FiatConversion.account_id == user_id)
                )
                == 1
            )
    finally:
        await _cleanup(user_id, owner_id)


async def test_allocation_and_conversion_race_has_no_lost_update():
    user_id, owner_id = await _setup("100")

    async def allocate() -> None:
        async with AsyncSessionLocal() as session:
            owner = await AccountRepository(session).get_by_id(owner_id)
            await _service(session).allocate(
                actor=owner,
                target_account_id=user_id,
                currency=Currency.TJS,
                amount=Decimal("50"),
                comment=None,
                idempotency_key="race-allocation",
            )
            await session.commit()

    try:
        conversion_id, _ = await asyncio.gather(
            _convert(user_id, owner_id, "80", "race-with-allocation"), allocate()
        )
        assert conversion_id is not None
        async with AsyncSessionLocal() as session:
            balances = {
                item.currency: item.available
                for item in await FiatWalletRepository(session).list_balances(user_id)
            }
            assert balances == {Currency.TJS: Decimal("70"), Currency.RUB: Decimal("800")}
    finally:
        await _cleanup(user_id, owner_id)


async def test_concurrent_same_idempotency_key_creates_one_conversion_and_credit():
    user_id, owner_id = await _setup("100")
    try:
        first, second = await asyncio.gather(
            _convert(user_id, owner_id, "10", "same-concurrent-key"),
            _convert(user_id, owner_id, "10", "same-concurrent-key"),
        )
        assert first == second
        async with AsyncSessionLocal() as session:
            balances = {
                item.currency: item.available
                for item in await FiatWalletRepository(session).list_balances(user_id)
            }
            assert balances == {Currency.TJS: Decimal("90"), Currency.RUB: Decimal("100")}
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FiatConversion)
                    .where(FiatConversion.account_id == user_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FiatLedgerEntry)
                    .where(
                        FiatLedgerEntry.reference_type == "fiat_conversion",
                        FiatLedgerEntry.account_id == user_id,
                    )
                )
                == 2
            )
    finally:
        await _cleanup(user_id, owner_id)
