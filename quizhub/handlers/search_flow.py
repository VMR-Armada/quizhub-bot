from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from quizhub.db import Database
from quizhub.format import format_quiz_card
from quizhub.handlers.common import _remember, cmd_start, show_search
from quizhub.handlers.middleware import AppContext
from quizhub.keyboards import quiz_keyboard
from quizhub.listing import resolve_quiz
from quizhub.search import parse_search
from quizhub.timeutil import today_msk

_GREETINGS = {"привет", "здравствуйте", "здравствуй", "хай", "hello", "hi"}

router = Router()


@router.message(StateFilter(None), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def private_search(message: Message, db: Database) -> None:
    parsed = parse_search(message.text or "", today_msk())
    if (
        not parsed.date_from
        and not parsed.part
        and not parsed.city_code
        and set(parsed.tokens) <= _GREETINGS
        and parsed.tokens
    ):
        await cmd_start(message, db)
        return
    user = await _remember(message, db)
    await show_search(message, db, user, message.text or "")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text, ~F.text.startswith("/"))
async def group_mention(message: Message, db: Database, ctx: AppContext) -> None:
    text = message.text or ""
    username = ctx.bot_username
    mentioned = bool(username) and re.search(rf"@{re.escape(username)}\b", text, flags=re.IGNORECASE)
    query = re.sub(rf"@{re.escape(username)}\b", " ", text, flags=re.IGNORECASE).strip() if mentioned and username else text.strip()
    parsed = parse_search(query, today_msk())
    asks_schedule = bool(parsed.date_from or parsed.part or parsed.city_code)
    if not mentioned and not asks_schedule:
        return
    if not query:
        await message.reply("Напишите запрос после упоминания. Например: завтра вечером музыка.")
        return
    user = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await show_search(message, db, user, query)


@router.message(StateFilter(None), F.text.startswith("/"))
async def unknown_command(message: Message, db: Database) -> None:
    await message.answer("Такой команды нет. Показываю квизы на сегодня.")
    user = await _remember(message, db)
    await show_search(message, db, user, "сегодня")


@router.callback_query(F.data.startswith("quiz:"))
async def open_quiz(callback: CallbackQuery, db: Database) -> None:
    raw_id = callback.data.split(":", 1)[1]
    quiz = await resolve_quiz(db, callback.from_user.id, raw_id)
    if quiz is None:
        await callback.answer("Квиз уже не в каталоге", show_alert=True)
        return
    city = await db.city_name(quiz["city_code"]) or quiz["city_code"]
    posts = await db.team_posts(quiz["id"])
    await callback.answer()
    await callback.message.answer(format_quiz_card(quiz, city, posts), reply_markup=quiz_keyboard(quiz))
