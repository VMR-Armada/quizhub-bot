from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.utils.token import TokenValidationError
from aiohttp import web

from quizhub.config import load_settings
from quizhub.db import Database
from quizhub.handlers import AppContext, setup_routers
from quizhub.seed import delete_demo_quizzes
from quizhub.web import create_web_app

log = logging.getLogger("quizhub")


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        return


def _port_busy(exc: OSError) -> bool:
    return exc.errno in {98, 10048} or getattr(exc, "winerror", None) == 10048


COMMANDS = [
    BotCommand(command="start", description="Начало и город"),
    BotCommand(command="city", description="Сменить город"),
    BotCommand(command="today", description="Квизы на сегодня"),
    BotCommand(command="tomorrow", description="Квизы на завтра"),
    BotCommand(command="sub", description="Подписки на темы"),
    BotCommand(command="table", description="Таблица расписания"),
    BotCommand(command="find", description="Найти команду или игрока"),
    BotCommand(command="createschedule", description="Расписание в чат на неделю"),
    BotCommand(command="stats", description="Короткая сводка"),
    BotCommand(command="help", description="Как пользоваться"),
    BotCommand(command="cancel", description="Отменить текущий шаг"),
    BotCommand(command="newquiz", description="Добавить квиз (админ)"),
]


async def main() -> None:
    settings = load_settings()
    database = Database(settings.db_path)
    await database.init()
    removed = await delete_demo_quizzes(database)
    if removed:
        log.info("Убраны учебные квизы, которых нет в живом расписании: %s", removed)

    try:
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except TokenValidationError as error:
        raise SystemExit(
            "Токен в .env имеет неверный формат.\n"
            "Нужна одна строка вида 123456789:AAH... без кавычек, пробелов и слова bot."
        ) from error
    dispatcher = Dispatcher(storage=MemoryStorage())
    ctx = AppContext(db=database, settings=settings)
    setup_routers(dispatcher, ctx)

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError as error:
        await bot.session.close()
        raise SystemExit(
            "Telegram не принял токен. Проверьте BOT_TOKEN в .env: его выдаёт @BotFather командой /newbot."
        ) from error
    except TelegramNetworkError as error:
        await bot.session.close()
        raise SystemExit("Нет связи с Telegram. Проверьте интернет и запустите бота ещё раз.") from error
    ctx.bot_username = me.username or ""
    await bot.set_my_commands(COMMANDS)

    app = create_web_app(database)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, settings.web_host, settings.web_port).start()
    except OSError as error:
        await bot.session.close()
        await runner.cleanup()
        if _port_busy(error):
            raise SystemExit(
                f"Порт {settings.web_port} уже занят. Закройте другую копию бота или укажите другой WEB_PORT в .env."
            ) from error
        raise
    log.info("Таблица: %s", settings.public_base_url)
    log.info("Бот @%s запущен", ctx.bot_username)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    configure_console()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
