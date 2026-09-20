from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_request import AccessRequest


class AccessRequestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, request: AccessRequest) -> AccessRequest:
        self.session.add(request)
        await self.session.flush()
        return request
