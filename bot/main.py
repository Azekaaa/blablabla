import asyncio
import logging
import sys
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.handlers import get_router
from bot.scheduler import setup_scheduler
from database.models import init_db

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    logger.info("Bot starting up...")
    await init_db()
    logger.info("Database initialized")

    me = await bot.get_me()
    logger.info("Logged in as @%s (id=%s)", me.username, me.id)

    # Notify chat that bot started
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


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot shutting down...")
    try:
        await bot.send_message(
            chat_id=settings.chat_id,
            text="🔴 CRM Bot остановлен.",
        )
    except Exception:
        pass


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Register all routers
    dp.include_router(get_router())

    # Startup/shutdown hooks
    dp.startup.register(lambda: on_startup(bot))
    dp.shutdown.register(lambda: on_shutdown(bot))

    # Setup and start scheduler
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
