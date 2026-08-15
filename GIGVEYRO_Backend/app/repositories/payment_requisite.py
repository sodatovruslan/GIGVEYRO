import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_requisite import PaymentRequisite


class PaymentRequisiteRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, requisite_id: uuid.UUID) -> PaymentRequisite | None:
        return await self._session.get(PaymentRequisite, requisite_id)

    async def list_for_account(self, account_id: uuid.UUID) -> list[PaymentRequisite]:
        result = await self._session.execute(
            select(PaymentRequisite)
            .where(PaymentRequisite.account_id == account_id)
            .order_by(PaymentRequisite.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_non_archived(self, account_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(PaymentRequisite)
            .where(
                PaymentRequisite.account_id == account_id,
                PaymentRequisite.is_archived.is_(False),
            )
        )
        return result.scalar_one()

    async def count_eligible(self, account_id: uuid.UUID) -> int:
        """Non-archived AND active - the set that makes traffic eligible."""
        result = await self._session.execute(
            select(func.count())
            .select_from(PaymentRequisite)
            .where(
                PaymentRequisite.account_id == account_id,
                PaymentRequisite.is_active.is_(True),
                PaymentRequisite.is_archived.is_(False),
            )
        )
        return result.scalar_one()

    async def find_non_archived_duplicate(
        self, account_id: uuid.UUID, card_number: str
    ) -> PaymentRequisite | None:
        result = await self._session.execute(
            select(PaymentRequisite).where(
                PaymentRequisite.account_id == account_id,
                PaymentRequisite.card_number == card_number,
                PaymentRequisite.is_archived.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, requisite: PaymentRequisite) -> PaymentRequisite:
        self._session.add(requisite)
        await self._session.flush()
        await self._session.refresh(requisite)
        return requisite

    async def save(self, requisite: PaymentRequisite) -> PaymentRequisite:
        await self._session.flush()
        await self._session.refresh(requisite)
        return requisite
