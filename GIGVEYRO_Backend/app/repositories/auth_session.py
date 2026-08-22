import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.auth_session import AuthSession


class AuthSessionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, auth_session: AuthSession) -> AuthSession:
        self._session.add(auth_session)
        await self._session.flush()
        await self._session.refresh(auth_session)
        return auth_session

    async def get_by_id(self, session_id: uuid.UUID) -> AuthSession | None:
        return await self._session.get(AuthSession, session_id)

    async def get_by_id_for_update(self, session_id: uuid.UUID) -> AuthSession | None:
        # Row lock: serializes concurrent /auth/refresh calls racing on the
        # same session so exactly one rotation can win per request.
        result = await self._session.execute(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_for_account(self, account_id: uuid.UUID) -> list[AuthSession]:
        result = await self._session.execute(
            select(AuthSession)
            .where(
                AuthSession.account_id == account_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > func.now(),
            )
            .order_by(AuthSession.last_used_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, auth_session: AuthSession) -> AuthSession:
        await self._session.flush()
        await self._session.refresh(auth_session)
        return auth_session

    async def revoke_all_for_account(
        self,
        account_id: uuid.UUID,
        *,
        reason: str,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        stmt = (
            update(AuthSession)
            .where(AuthSession.account_id == account_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=func.now(), revoked_reason=reason)
        )
        if except_session_id is not None:
            stmt = stmt.where(AuthSession.id != except_session_id)
        result = await self._session.execute(stmt.execution_options(synchronize_session=False))
        return result.rowcount or 0

    async def prune_expired(self, older_than: datetime) -> int:
        result = await self._session.execute(
            delete(AuthSession).where(AuthSession.expires_at < older_than)
        )
        return result.rowcount or 0
