from aiogram import Router
from bot.handlers.commands import router as commands_router
from bot.handlers.callbacks import router as callbacks_router


def get_router() -> Router:
    main_router = Router()
    main_router.include_router(commands_router)
    main_router.include_router(callbacks_router)
    return main_router
