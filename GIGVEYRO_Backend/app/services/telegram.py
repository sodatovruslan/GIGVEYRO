import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.models.telegram import TelegramAccountLink
from app.repositories.telegram import TelegramLinkRepository


class TelegramService:
    def __init__(self, telegram_repo: TelegramLinkRepository):
        self.telegram_repo = telegram_repo

    async def generate_link_code(self, account_id: uuid.UUID) -> tuple[str, TelegramAccountLink]:
        raw_code = secrets.token_hex(16)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        link = await self.telegram_repo.create_or_update_verification_code(account_id, raw_code, expires_at)
        return raw_code, link

    async def process_telegram_command(
        self, telegram_user_id: int, chat_id: int, text: str
    ) -> str:
        parts = text.strip().split()
        if not parts:
            return "Invalid command"

        cmd = parts[0]
        if cmd == "/start" and len(parts) > 1:
            code = parts[1]
            link = await self.telegram_repo.get_by_verification_code(code)
            if not link:
                return "Invalid or expired link code."
            if link.verification_expires_at and link.verification_expires_at < datetime.now(timezone.utc):
                return "Link code has expired."

            await self.telegram_repo.complete_link(link, telegram_user_id, chat_id)
            return "Telegram account linked successfully!"

        return "Welcome to Gigveyro Bot! Send /start <code_from_app> to link your account."
