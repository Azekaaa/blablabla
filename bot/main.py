import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.handlers import get_router
from bot.scheduler import setup_scheduler
from database.models import init_db, get_engine, Base

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)


async def on_startup() -> None:
    logger.info("Bot starting up...")

    # Явно создаём все таблицы
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")

    me = await bot.get_me()
    logger.info("Logged in as @%s (id=%s)", me.username, me.id)

    try:
        await bot.send_message(
            chat_id=settings.chat_id,
            text=(
                "🤖 *CRM Bot запущен*\n\n"
                f"📅 Отчёты в: `{settings.report_time_morning}` и `{settings.report_time_evening}` UTC\n"
                f"⚙️ Порог неактивности: {settings.inactive_days_threshold} дней\n"
                f"⚙️ Порог застревания: {settings.stuck_stage_days_threshold} дней\n\n"
                "Используйте /report для получения отчёта прямо сейчас."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning("Could not send startup message: %s", e)


async def on_shutdown() -> None:
    logger.info("Bot shutting down...")
    try:
        await bot.send_message(chat_id=settings.chat_id, text="🔴 CRM Bot остановлен.")
    except Exception:
        pass


async def main() -> None:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(get_router())

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")

    try:
        logger.info("Starting polling...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
