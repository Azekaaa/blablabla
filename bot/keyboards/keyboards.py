from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def main_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Отчёт"),
                KeyboardButton(text="📈 Статистика"),
            ],
            [
                KeyboardButton(text="🏆 Менеджеры"),
                KeyboardButton(text="⚠️ Проблемы"),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def report_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for the report message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_report"),
                InlineKeyboardButton(text="⚠️ Проблемы", callback_data="show_problems"),
            ],
            [
                InlineKeyboardButton(text="🏆 Менеджеры", callback_data="show_managers"),
                InlineKeyboardButton(text="📈 Статистика", callback_data="show_stats"),
            ],
            [
                InlineKeyboardButton(text="🔃 Синхронизировать", callback_data="force_sync"),
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    """Back button keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к отчёту", callback_data="back_to_report")],
            [InlineKeyboardButton(text="🔄 Обновить данные", callback_data="force_sync")],
        ]
    )
