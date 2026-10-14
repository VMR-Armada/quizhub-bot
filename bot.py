from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiohttp import web

from quizhub.config import load_settings
from quizhub.db import Database
from quizhub.handlers import AppContext, setup_routers
from quizhub.seed import seed_if_empty
from quizhub.web import create_web_app

log = logging.getLogger("quizhub")

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
    added = await seed_if_empty(database)
    if added:
        log.info("В каталог добавлены демо-квизы: %s", added)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())
    ctx = AppContext(db=database, settings=settings)
    setup_routers(dispatcher, ctx)

    app = create_web_app(database)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, settings.web_host, settings.web_port).start()
    log.info("Таблица: %s", settings.public_base_url)

    me = await bot.get_me()
    ctx.bot_username = me.username or ""
    await bot.set_my_commands(COMMANDS)
    log.info("Бот @%s запущен", ctx.bot_username)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
