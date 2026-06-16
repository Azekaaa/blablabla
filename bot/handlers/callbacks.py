import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards import report_inline_keyboard, back_keyboard
from bot.reports import (
    build_full_report, build_managers_report,
    build_problems_report, build_stats_report,
)
from bot.services import AnalyticsService, SyncService

logger = logging.getLogger(__name__)
router = Router()

analytics_service = AnalyticsService()
sync_service = SyncService()


@router.callback_query(F.data == "refresh_report")
async def cb_refresh_report(callback: CallbackQuery) -> None:
    await callback.answer("🔄 Обновляю...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_full_report(analytics)
        await callback.message.edit_text(
            text[:4000],
            parse_mode="Markdown",
            reply_markup=report_inline_keyboard(),
        )
    except Exception as e:
        logger.error("Error refreshing report: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "show_problems")
async def cb_show_problems(callback: CallbackQuery) -> None:
    await callback.answer("⏳")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_problems_report(analytics)
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.error("Error showing problems: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "show_managers")
async def cb_show_managers(callback: CallbackQuery) -> None:
    await callback.answer("⏳")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_managers_report(analytics)
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.error("Error showing managers: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "show_stats")
async def cb_show_stats(callback: CallbackQuery) -> None:
    await callback.answer("⏳")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_stats_report(analytics)
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.error("Error showing stats: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "back_to_report")
async def cb_back_to_report(callback: CallbackQuery) -> None:
    await callback.answer("⏳")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_full_report(analytics)
        await callback.message.edit_text(
            text[:4000],
            parse_mode="Markdown",
            reply_markup=report_inline_keyboard(),
        )
    except Exception as e:
        logger.error("Error going back to report: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "force_sync")
async def cb_force_sync(callback: CallbackQuery) -> None:
    await callback.answer("🔃 Синхронизирую данные с Bitrix24...")
    try:
        result = await sync_service.sync_deals()
        await callback.answer(
            f"✅ Синхронизация завершена!\n"
            f"Загружено: {result['fetched']} сделок",
            show_alert=True,
        )
    except Exception as e:
        logger.error("Force sync failed: %s", e, exc_info=True)
        await callback.answer(f"❌ Ошибка синхронизации: {e}", show_alert=True)
