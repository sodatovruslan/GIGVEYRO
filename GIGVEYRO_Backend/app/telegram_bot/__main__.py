import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Message

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.infra.logging_config import configure_logging
from app.infra.redis_client import close_redis, init_redis
from app.telegram_bot.commands import TelegramCommandService

router = Router(name="gigveyro-read-only-commands")


@router.message(F.chat.type == "private", F.text)
async def handle_private_text(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    async with AsyncSessionLocal() as session:
        try:
            reply = await TelegramCommandService(session).handle(
                telegram_user_id=message.from_user.id,
                chat_id=message.chat.id,
                text_value=message.text,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                telegram_language=message.from_user.language_code,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    await message.answer(reply, protect_content=True)


async def run_polling() -> None:
    if not settings.TELEGRAM_BOT_ENABLED:
        raise RuntimeError("Telegram bot is disabled")
    if settings.TELEGRAM_BOT_MODE != "polling":
        raise RuntimeError("Telegram polling runner requires TELEGRAM_BOT_MODE=polling")
    configure_logging(app_env=settings.APP_ENV, log_level="INFO")
    await init_redis()
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        session=AiohttpSession(timeout=settings.TELEGRAM_API_TIMEOUT_SECONDS),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logging.getLogger(__name__).info("event=telegram.polling.started")
        await dispatcher.start_polling(bot, allowed_updates=["message"])
    finally:
        await bot.session.close()
        await close_redis()
        logging.getLogger(__name__).info("event=telegram.polling.stopped")


if __name__ == "__main__":
    asyncio.run(run_polling())
