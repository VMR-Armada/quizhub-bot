from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from quizhub.db import Database
from quizhub.format import format_quiz_card
from quizhub.handlers.common import _remember, show_search
from quizhub.handlers.middleware import AppContext
from quizhub.keyboards import quiz_keyboard

router = Router()


@router.message(StateFilter(None), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def private_search(message: Message, db: Database) -> None:
    user = await _remember(message, db)
    await show_search(message, db, user, message.text)


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text, ~F.text.startswith("/"))
async def group_mention(message: Message, db: Database, ctx: AppContext) -> None:
    username = ctx.bot_username
    if not username or not message.text:
        return
    if not re.search(rf"@{re.escape(username)}\b", message.text, flags=re.IGNORECASE):
        return
    query = re.sub(rf"@{re.escape(username)}\b", " ", message.text, flags=re.IGNORECASE).strip()
    if not query:
        await message.reply("Напишите запрос после упоминания. Например: завтра вечером музыка.")
        return
    user = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await show_search(message, db, user, query)


@router.callback_query(F.data.startswith("quiz:"))
async def open_quiz(callback: CallbackQuery, db: Database) -> None:
    quiz_id = int(callback.data.split(":", 1)[1])
    quiz = await db.get_quiz(quiz_id)
    if quiz is None:
        await callback.answer("Квиз уже не в каталоге", show_alert=True)
        return
    city = await db.city_name(quiz["city_code"]) or quiz["city_code"]
    posts = await db.team_posts(quiz_id)
    await callback.answer()
    await callback.message.answer(format_quiz_card(quiz, city, posts), reply_markup=quiz_keyboard(quiz))
