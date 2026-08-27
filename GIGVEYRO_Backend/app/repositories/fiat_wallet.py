import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.wallet import Currency
from app.models.fiat_wallet import FiatConversion, FiatLedgerEntry, FiatWalletBalance


class FiatWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_balances(self, account_id: uuid.UUID) -> list[FiatWalletBalance]:
        result = await self.session.execute(
            select(FiatWalletBalance)
            .where(FiatWalletBalance.account_id == account_id)
            .order_by(FiatWalletBalance.currency)
        )
        return list(result.scalars().all())

    async def ensure_balances(self, account_id: uuid.UUID) -> None:
        for currency in Currency.managed_fiat():
            await self.session.execute(
                insert(FiatWalletBalance)
                .values(id=uuid.uuid4(), account_id=account_id, currency=currency, available=0)
                .on_conflict_do_nothing(index_elements=["account_id", "currency"])
            )
        await self.session.flush()

    async def lock_balances(self, account_id: uuid.UUID) -> dict[Currency, FiatWalletBalance]:
        await self.ensure_balances(account_id)
        result = await self.session.execute(
            select(FiatWalletBalance)
            .where(
                FiatWalletBalance.account_id == account_id,
                FiatWalletBalance.currency.in_(Currency.managed_fiat()),
            )
            .order_by(FiatWalletBalance.currency)
            .with_for_update()
        )
        return {item.currency: item for item in result.scalars().all()}

    async def save(self, balance: FiatWalletBalance) -> FiatWalletBalance:
        await self.session.flush()
        await self.session.refresh(balance)
        return balance


class FiatLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entry: FiatLedgerEntry) -> FiatLedgerEntry:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def by_idempotency(
        self, balance_id: uuid.UUID, idempotency_key: str
    ) -> FiatLedgerEntry | None:
        result = await self.session.execute(
            select(FiatLedgerEntry).where(
                FiatLedgerEntry.balance_id == balance_id,
                FiatLedgerEntry.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def by_actor_idempotency(
        self, actor_id: uuid.UUID, idempotency_key: str
    ) -> FiatLedgerEntry | None:
        result = await self.session.execute(
            select(FiatLedgerEntry).where(
                FiatLedgerEntry.created_by_account_id == actor_id,
                FiatLedgerEntry.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_account(
        self, account_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[FiatLedgerEntry], int]:
        filtered = FiatLedgerEntry.account_id == account_id
        result = await self.session.execute(
            select(FiatLedgerEntry)
            .where(filtered)
            .order_by(FiatLedgerEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count = await self.session.scalar(
            select(func.count()).select_from(FiatLedgerEntry).where(filtered)
        )
        return list(result.scalars().all()), int(count or 0)


class FiatConversionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, conversion: FiatConversion) -> FiatConversion:
        self.session.add(conversion)
        await self.session.flush()
        await self.session.refresh(conversion)
        return conversion

    async def by_actor_idempotency(
        self, actor_id: uuid.UUID, idempotency_key: str
    ) -> FiatConversion | None:
        result = await self.session.execute(
            select(FiatConversion).where(
                FiatConversion.initiated_by_account_id == actor_id,
                FiatConversion.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_history(
        self,
        *,
        account_id: uuid.UUID | None,
        currency: Currency | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FiatConversion], int]:
        query: Select = select(FiatConversion)
        count_query: Select = select(func.count()).select_from(FiatConversion)
        filters = []
        if account_id is not None:
            filters.append(FiatConversion.account_id == account_id)
        if currency is not None:
            filters.append(
                (FiatConversion.from_currency == currency)
                | (FiatConversion.to_currency == currency)
            )
        if date_from is not None:
            filters.append(FiatConversion.created_at >= date_from)
        if date_to is not None:
            filters.append(FiatConversion.created_at <= date_to)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
        result = await self.session.execute(
            query.order_by(FiatConversion.created_at.desc()).limit(limit).offset(offset)
        )
        count = await self.session.scalar(count_query)
        return list(result.scalars().all()), int(count or 0)
