import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.telegram import TelegramAccountLink, TelegramLinkToken


class TelegramLinkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    hash_code = hash_token

    async def get_by_account_id(
        self, account_id: uuid.UUID, *, for_update: bool = False
    ) -> TelegramAccountLink | None:
        stmt = select(TelegramAccountLink).where(TelegramAccountLink.account_id == account_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_user_id(
        self, telegram_user_id: int, *, for_update: bool = False, include_account: bool = False
    ) -> TelegramAccountLink | None:
        stmt = select(TelegramAccountLink).where(
            TelegramAccountLink.telegram_user_id == telegram_user_id,
            TelegramAccountLink.is_linked.is_(True),
        )
        if include_account:
            stmt = stmt.options(selectinload(TelegramAccountLink.account))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_unused_tokens(self, account_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(TelegramLinkToken)
            .where(
                TelegramLinkToken.account_id == account_id,
                TelegramLinkToken.used_at.is_(None),
                TelegramLinkToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def create_token(
        self, account_id: uuid.UUID, raw_token: str, expires_at: datetime
    ) -> TelegramLinkToken:
        token = TelegramLinkToken(
            account_id=account_id,
            token_hash=self.hash_token(raw_token),
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_token_for_update(self, raw_token: str) -> TelegramLinkToken | None:
        result = await self.session.execute(
            select(TelegramLinkToken)
            .where(TelegramLinkToken.token_hash == self.hash_token(raw_token))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def activate_connection(
        self,
        *,
        account_id: uuid.UUID,
        telegram_user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        language: str,
        now: datetime,
    ) -> TelegramAccountLink:
        connection = await self.get_by_account_id(account_id, for_update=True)
        if connection is None:
            connection = TelegramAccountLink(account_id=account_id)
            self.session.add(connection)
        connection.telegram_user_id = telegram_user_id
        connection.chat_id = chat_id
        connection.telegram_username = username
        connection.telegram_first_name = first_name
        connection.language = language
        connection.is_linked = True
        connection.delivery_enabled = True
        connection.linked_at = now
        connection.last_seen_at = now
        connection.disabled_at = None
        connection.last_error_category = None
        await self.session.flush()
        return connection

    async def disconnect(self, connection: TelegramAccountLink, now: datetime) -> None:
        connection.is_linked = False
        connection.delivery_enabled = False
        connection.disabled_at = now
        await self.session.flush()

    async def update_language(
        self, connection: TelegramAccountLink, language: str, now: datetime
    ) -> None:
        connection.language = language
        connection.last_seen_at = now
        await self.session.flush()

    async def update_delivery(
        self, connection: TelegramAccountLink, enabled: bool, now: datetime
    ) -> None:
        connection.delivery_enabled = enabled
        connection.disabled_at = None if enabled else now
        if enabled:
            connection.last_error_category = None
        await self.session.flush()
