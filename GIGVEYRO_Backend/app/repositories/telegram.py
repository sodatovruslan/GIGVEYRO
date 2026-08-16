import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram import TelegramAccountLink


class TelegramLinkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> TelegramAccountLink | None:
        stmt = select(TelegramAccountLink).where(TelegramAccountLink.account_id == account_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_link_code(self, link_code: str) -> TelegramAccountLink | None:
        stmt = select(TelegramAccountLink).where(TelegramAccountLink.link_code == link_code)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_or_update_link_code(
        self, account_id: uuid.UUID, link_code: str, expires_at: datetime
    ) -> TelegramAccountLink:
        link = await self.get_by_account_id(account_id)
        if not link:
            link = TelegramAccountLink(
                account_id=account_id,
                link_code=link_code,
                link_expires_at=expires_at,
                is_linked=False,
            )
            self.session.add(link)
        else:
            link.link_code = link_code
            link.link_expires_at = expires_at
        await self.session.flush()
        return link

    async def complete_link(
        self, link: TelegramAccountLink, telegram_user_id: int, chat_id: int
    ) -> TelegramAccountLink:
        link.telegram_user_id = telegram_user_id
        link.chat_id = chat_id
        link.is_linked = True
        link.link_code = None
        link.link_expires_at = None
        await self.session.flush()
        return link
