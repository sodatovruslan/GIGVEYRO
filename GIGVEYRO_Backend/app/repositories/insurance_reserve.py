import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance_reserve import InsuranceReservePolicy


class InsuranceReservePolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_policy(self, *, lock: bool = False) -> InsuranceReservePolicy:
        query = select(InsuranceReservePolicy).where(InsuranceReservePolicy.status == "active")
        if lock:
            query = query.with_for_update(key_share=True)
        return (await self.session.execute(query)).scalar_one()

    async def policy(self, policy_id: uuid.UUID) -> InsuranceReservePolicy | None:
        return await self.session.get(InsuranceReservePolicy, policy_id)

    async def lock_policies(self) -> list[InsuranceReservePolicy]:
        return list(
            (
                await self.session.execute(
                    select(InsuranceReservePolicy)
                    .order_by(InsuranceReservePolicy.version)
                    .with_for_update()
                )
            ).scalars()
        )

    async def save_policy(self, policy: InsuranceReservePolicy) -> InsuranceReservePolicy:
        self.session.add(policy)
        await self.session.flush()
        await self.session.refresh(policy)
        return policy
