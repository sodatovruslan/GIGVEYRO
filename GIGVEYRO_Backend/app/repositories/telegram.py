import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram import TelegramAccountLink


class TelegramLinkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    async def get_by_account_id(self, account_id: uuid.UUID) -> TelegramAccountLink | None:
        stmt = select(TelegramAccountLink).where(TelegramAccountLink.account_id == account_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_verification_code(self, code: str) -> TelegramAccountLink | None:
        code_hash = self.hash_code(code)
        stmt = select(TelegramAccountLink).where(
            TelegramAccountLink.verification_code_hash == code_hash
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_or_update_verification_code(
        self, account_id: uuid.UUID, code: str, expires_at: datetime
    ) -> TelegramAccountLink:
        code_hash = self.hash_code(code)
        link = await self.get_by_account_id(account_id)
        if not link:
            link = TelegramAccountLink(
                account_id=account_id,
                verification_code_hash=code_hash,
                verification_expires_at=expires_at,
                is_linked=False,
            )
            self.session.add(link)
        else:
            link.verification_code_hash = code_hash
            link.verification_expires_at = expires_at
        await self.session.flush()
        return link

    async def complete_link(
        self, link: TelegramAccountLink, telegram_user_id: int, chat_id: int
    ) -> TelegramAccountLink:
        link.telegram_user_id = telegram_user_id
        link.chat_id = chat_id
        link.is_linked = True
        link.verification_code_hash = None
        link.verification_expires_at = None
        await self.session.flush()
        return link
