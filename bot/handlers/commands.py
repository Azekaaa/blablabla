import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards import main_keyboard, report_inline_keyboard, back_keyboard
from bot.reports import (
    build_full_report, build_managers_report,
    build_problems_report, build_stats_report,
)
from bot.services import AnalyticsService, SyncService

logger = logging.getLogger(__name__)
router = Router()

analytics_service = AnalyticsService()
sync_service = SyncService()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 *CRM Bitrix24 Bot*\n\n"
        "Я анализирую ваш CRM и отправляю отчёты дважды в день.\n\n"
        "📋 *Команды:*\n"
        "/report — полный отчёт\n"
        "/stats — статистика\n"
        "/managers — рейтинг менеджеров\n"
        "/problems — проблемные сделки\n\n"
        "Выберите действие в меню ниже 👇",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


@router.message(Command("report"))
@router.message(lambda m: m.text == "📊 Отчёт")
async def cmd_report(message: Message) -> None:
    status_msg = await message.answer("⏳ Генерирую отчёт...")
    try:
        analytics = await analytics_service.get_analytics()
        report_text = build_full_report(analytics)

        await status_msg.delete()
        # Telegram max message length is 4096, split if needed
        if len(report_text) > 4000:
            chunks = [report_text[i:i + 4000] for i in range(0, len(report_text), 4000)]
            for i, chunk in enumerate(chunks):
                kb = report_inline_keyboard() if i == len(chunks) - 1 else None
                await message.answer(chunk, parse_mode="Markdown", reply_markup=kb)
        else:
            await message.answer(
                report_text,
                parse_mode="Markdown",
                reply_markup=report_inline_keyboard(),
            )
    except Exception as e:
        logger.error("Error generating report: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка при генерации отчёта: {e}")


@router.message(Command("stats"))
@router.message(lambda m: m.text == "📈 Статистика")
async def cmd_stats(message: Message) -> None:
    status_msg = await message.answer("⏳ Загружаю статистику...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_stats_report(analytics)
        await status_msg.delete()
        await message.answer(text, parse_mode="Markdown", reply_markup=back_keyboard())
    except Exception as e:
        logger.error("Error generating stats: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка: {e}")


@router.message(Command("managers"))
@router.message(lambda m: m.text == "🏆 Менеджеры")
async def cmd_managers(message: Message) -> None:
    status_msg = await message.answer("⏳ Загружаю рейтинг менеджеров...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_managers_report(analytics)
        await status_msg.delete()
        await message.answer(text, parse_mode="Markdown", reply_markup=back_keyboard())
    except Exception as e:
        logger.error("Error generating managers report: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка: {e}")


@router.message(Command("problems"))
@router.message(lambda m: m.text == "⚠️ Проблемы")
async def cmd_problems(message: Message) -> None:
    status_msg = await message.answer("⏳ Анализирую проблемные сделки...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_problems_report(analytics)
        await status_msg.delete()
        await message.answer(text, parse_mode="Markdown", reply_markup=back_keyboard())
    except Exception as e:
        logger.error("Error generating problems report: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка: {e}")
