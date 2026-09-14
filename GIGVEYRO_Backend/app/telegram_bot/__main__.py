import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.infra.logging_config import configure_logging
from app.infra.redis_client import close_redis, init_redis
from app.telegram_bot.commands import TelegramCommandService

router = Router(name="gigveyro-commands")


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
    await message.answer(reply, reply_markup=getattr(reply, "keyboard", None), protect_content=True)


@router.callback_query(F.message.chat.type == "private")
async def handle_private_callback(callback_query: CallbackQuery) -> None:
    if callback_query.data is None or callback_query.message is None:
        await callback_query.answer()
        return
    async with AsyncSessionLocal() as session:
        try:
            reply = await TelegramCommandService(session).handle_callback(
                telegram_user_id=callback_query.from_user.id,
                chat_id=callback_query.message.chat.id,
                data=callback_query.data,
                username=callback_query.from_user.username,
                first_name=callback_query.from_user.first_name,
                telegram_language=callback_query.from_user.language_code,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    await callback_query.answer()
    if reply is None:
        return
    try:
        await callback_query.message.edit_text(reply, reply_markup=getattr(reply, "keyboard", None))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


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
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        await close_redis()
        logging.getLogger(__name__).info("event=telegram.polling.stopped")


if __name__ == "__main__":
    asyncio.run(run_polling())
