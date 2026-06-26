import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from bot.config import settings
from bot.reports import build_full_report
from bot.services import SyncService, AnalyticsService
from database.models import ReportLog, get_session_factory

logger = logging.getLogger(__name__)


async def _send_scheduled_report(bot: Bot) -> None:
    session_factory = get_session_factory()
    report_log = ReportLog(
        report_type="scheduled",
        chat_id=settings.chat_id,
        sent_at=datetime.now(timezone.utc),
    )

    try:
        logger.info("Starting scheduled report job")

        sync_service = SyncService()
        sync_result = await sync_service.sync_deals()
        logger.info("Sync done: %s", sync_result)

        analytics_service = AnalyticsService()
        analytics = await analytics_service.get_analytics()

        from bot.keyboards import report_inline_keyboard
        report_text = build_full_report(analytics)

        if len(report_text) > 4000:
            chunks = [report_text[i:i + 4000] for i in range(0, len(report_text), 4000)]
            for i, chunk in enumerate(chunks):
                kb = report_inline_keyboard() if i == len(chunks) - 1 else None
                await bot.send_message(
                    chat_id=settings.chat_id,
                    text=chunk,
                    reply_markup=kb,
                )
        else:
            await bot.send_message(
                chat_id=settings.chat_id,
                text=report_text,
                reply_markup=report_inline_keyboard(),
            )

        report_log.success = True
        logger.info("Scheduled report sent successfully")

    except Exception as e:
        logger.error("Scheduled report failed: %s", e, exc_info=True)
        report_log.success = False
        report_log.error_message = str(e)[:1000]

        try:
            await bot.send_message(
                chat_id=settings.chat_id,
                text=f"Ошибка автоматического отчёта: {str(e)[:500]}",
            )
        except Exception as send_err:
            logger.error("Could not send error notification: %s", send_err)

    finally:
        async with session_factory() as session:
            session.add(report_log)
            await session.commit()


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Morning report: 9:00 Астана = 04:00 UTC
    scheduler.add_job(
        _send_scheduled_report,
        trigger=CronTrigger(hour=6, minute=15, timezone="UTC"),
        args=[bot],
        id="morning_report",
        name="Morning CRM Report (09:00 Astana)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Evening report: 17:00 Астана = 12:00 UTC
    scheduler.add_job(
        _send_scheduled_report,
        trigger=CronTrigger(hour=12, minute=0, timezone="UTC"),
        args=[bot],
        id="evening_report",
        name="Evening CRM Report (17:00 Astana)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info("Scheduler configured: 09:00 and 17:00 Astana time (04:00 and 12:00 UTC)")

    return scheduler