import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payout import PayoutDestination, PayoutNetwork


class PayoutSecurityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def destinations(self) -> list[PayoutDestination]:
        return list(
            (
                await self.session.execute(
                    select(PayoutDestination).order_by(PayoutDestination.created_at.desc())
                )
            ).scalars()
        )

    async def destination(self, destination_id: uuid.UUID, *, lock: bool = False):
        query = select(PayoutDestination).where(PayoutDestination.id == destination_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def destination_by_fingerprint(self, fingerprint: str):
        return (
            await self.session.execute(
                select(PayoutDestination)
                .where(PayoutDestination.fingerprint == fingerprint)
                .where(PayoutDestination.enabled.is_(True))
            )
        ).scalar_one_or_none()

    async def save_destination(self, destination: PayoutDestination) -> PayoutDestination:
        self.session.add(destination)
        await self.session.flush()
        await self.session.refresh(destination)
        return destination

    async def enabled_destination_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(PayoutDestination)
                .where(PayoutDestination.enabled.is_(True))
            )
            or 0
        )

    async def networks(self) -> list[PayoutNetwork]:
        return list(
            (
                await self.session.execute(
                    select(PayoutNetwork).order_by(PayoutNetwork.asset, PayoutNetwork.network)
                )
            ).scalars()
        )

    async def network(self, network_id: uuid.UUID, *, lock: bool = False):
        query = select(PayoutNetwork).where(PayoutNetwork.id == network_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def enabled_network(self, asset: str, network: str) -> PayoutNetwork | None:
        return (
            await self.session.execute(
                select(PayoutNetwork).where(
                    PayoutNetwork.asset == asset,
                    PayoutNetwork.network == network,
                    PayoutNetwork.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def enabled_network_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(PayoutNetwork)
                .where(PayoutNetwork.enabled.is_(True))
            )
            or 0
        )

    async def save_network(self, network: PayoutNetwork) -> PayoutNetwork:
        self.session.add(network)
        await self.session.flush()
        await self.session.refresh(network)
        return network
