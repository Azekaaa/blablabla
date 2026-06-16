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
    """Main scheduled task: sync data then send report."""
    session_factory = get_session_factory()
    report_log = ReportLog(
        report_type="scheduled",
        chat_id=settings.chat_id,
        sent_at=datetime.now(timezone.utc),
    )

    try:
        logger.info("Starting scheduled report job")

        # Step 1: Sync data from Bitrix24
        sync_service = SyncService()
        sync_result = await sync_service.sync_deals()
        logger.info("Sync done: %s", sync_result)

        # Step 2: Build analytics
        analytics_service = AnalyticsService()
        analytics = await analytics_service.get_analytics()

        # Step 3: Build and send report
        from bot.keyboards import report_inline_keyboard
        report_text = build_full_report(analytics)

        if len(report_text) > 4000:
            chunks = [report_text[i:i + 4000] for i in range(0, len(report_text), 4000)]
            for i, chunk in enumerate(chunks):
                kb = report_inline_keyboard() if i == len(chunks) - 1 else None
                await bot.send_message(
                    chat_id=settings.chat_id,
                    text=chunk,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
        else:
            await bot.send_message(
                chat_id=settings.chat_id,
                text=report_text,
                parse_mode="Markdown",
                reply_markup=report_inline_keyboard(),
            )

        report_log.success = True
        logger.info("Scheduled report sent successfully")

    except Exception as e:
        logger.error("Scheduled report failed: %s", e, exc_info=True)
        report_log.success = False
        report_log.error_message = str(e)[:1000]

        # Notify about failure
        try:
            await bot.send_message(
                chat_id=settings.chat_id,
                text=f"❌ *Ошибка автоматического отчёта*\n\n`{str(e)[:500]}`",
                parse_mode="Markdown",
            )
        except Exception as send_err:
            logger.error("Could not send error notification: %s", send_err)

    finally:
        async with session_factory() as session:
            session.add(report_log)
            await session.commit()


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Morning report
    scheduler.add_job(
        _send_scheduled_report,
        trigger=CronTrigger(
            hour=settings.morning_hour,
            minute=settings.morning_minute,
            timezone="UTC",
        ),
        args=[bot],
        id="morning_report",
        name="Morning CRM Report",
        replace_existing=True,
        misfire_grace_time=300,  # 5 minutes grace period
    )

    # Evening report
    scheduler.add_job(
        _send_scheduled_report,
        trigger=CronTrigger(
            hour=settings.evening_hour,
            minute=settings.evening_minute,
            timezone="UTC",
        ),
        args=[bot],
        id="evening_report",
        name="Evening CRM Report",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        "Scheduler configured: morning=%s:%02d UTC, evening=%s:%02d UTC",
        settings.morning_hour,
        settings.morning_minute,
        settings.evening_hour,
        settings.evening_minute,
    )

    return scheduler
