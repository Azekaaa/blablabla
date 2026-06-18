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


def split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        chunks.append(current.strip())
    return chunks


def strip_markdown(text: str) -> str:
    return text.replace("*", "").replace("`", "").replace("_", "")


async def send_chunks(message: Message, text: str, kb=None) -> None:
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        reply_kb = kb if i == len(chunks) - 1 else None
        try:
            await message.answer(chunk, parse_mode="Markdown", reply_markup=reply_kb)
        except Exception:
            await message.answer(strip_markdown(chunk), reply_markup=reply_kb)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 CRM Bitrix24 Bot\n\n"
        "Я анализирую ваш CRM и отправляю отчёты дважды в день.\n\n"
        "Команды:\n"
        "/report — полный отчёт\n"
        "/stats — статистика\n"
        "/managers — рейтинг менеджеров\n"
        "/problems — проблемные сделки\n\n"
        "Выберите действие в меню ниже 👇",
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
        await send_chunks(message, report_text, report_inline_keyboard())
    except Exception as e:
        logger.error("Error generating report: %s", e, exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("stats"))
@router.message(lambda m: m.text == "📈 Статистика")
async def cmd_stats(message: Message) -> None:
    status_msg = await message.answer("⏳ Загружаю статистику...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_stats_report(analytics)
        await status_msg.delete()
        await send_chunks(message, text, back_keyboard())
    except Exception as e:
        logger.error("Error generating stats: %s", e, exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("managers"))
@router.message(lambda m: m.text == "🏆 Менеджеры")
async def cmd_managers(message: Message) -> None:
    status_msg = await message.answer("⏳ Загружаю рейтинг менеджеров...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_managers_report(analytics)
        await status_msg.delete()
        await send_chunks(message, text, back_keyboard())
    except Exception as e:
        logger.error("Error generating managers report: %s", e, exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("problems"))
@router.message(lambda m: m.text == "⚠️ Проблемы")
async def cmd_problems(message: Message) -> None:
    status_msg = await message.answer("⏳ Анализирую проблемные сделки...")
    try:
        analytics = await analytics_service.get_analytics()
        text = build_problems_report(analytics)
        await status_msg.delete()
        await send_chunks(message, text, back_keyboard())
    except Exception as e:
        logger.error("Error generating problems report: %s", e, exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")
