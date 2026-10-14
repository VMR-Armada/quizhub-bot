from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizhub.db import Database
from quizhub.format import esc, format_day_label, status_icon
from quizhub.search import CITY_ALIASES
from quizhub.textutil import normalize
from quizhub.timeutil import parse_stored, today_msk

router = Router()

CODES = {"spb", "msk", "kzn", "klgd", "spbs"}


def resolve_city(raw: str) -> str | None:
    text = normalize(raw)
    if text in CODES:
        return text
    if text in CITY_ALIASES:
        return CITY_ALIASES[text]
    for token in text.split():
        if token in CODES:
            return token
        if token in CITY_ALIASES:
            return CITY_ALIASES[token]
    return None


def week_text(city_name: str, quizzes: list[dict]) -> str:
    lines = [f"<b>{esc(city_name)}</b>", "Расписание на 7 дней.", ""]
    if not quizzes:
        lines.append("На этой неделе квизов нет.")
        return "\n".join(lines)
    current = None
    for quiz in quizzes:
        moment = parse_stored(quiz["starts_at"])
        label = format_day_label(moment)
        if label != current:
            current = label
            lines.append(f"<b>{esc(label)}</b>")
        lines.append(
            f"• {status_icon(quiz['status'])} {moment.strftime('%H:%M')} "
            f"{esc(quiz['title'])} — {esc(quiz['organizer'])}, {esc(quiz['place'])}"
        )
    lines.append("\nЧтобы обновить, отправьте /createschedule")
    return "\n".join(lines)[:4000]


def _refresh_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Обновить", callback_data="sched:refresh")]]
    )


async def _publish(message: Message, db: Database, city_code: str) -> None:
    city_name = await db.city_name(city_code) or city_code
    quizzes = await db.quizzes_between(city_code, today_msk(), 7)
    text = week_text(city_name, quizzes)
    markup = _refresh_markup()
    existing = await db.chat_schedule(message.chat.id)
    if existing and existing.get("message_id"):
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=existing["message_id"],
                reply_markup=markup,
            )
            await db.save_chat_schedule(message.chat.id, city_code, message.from_user.id, existing["message_id"])
            await message.answer("Обновил сообщение с расписанием.")
            return
        except TelegramBadRequest:
            pass
    sent = await message.answer(text, reply_markup=markup)
    await db.save_chat_schedule(message.chat.id, city_code, message.from_user.id, sent.message_id)


@router.message(Command("createschedule"))
async def create_schedule(message: Message, db: Database) -> None:
    if message.chat.type == "private":
        await message.answer(
            "Команду /createschedule отправляют в чате команды. "
            "Бот пришлёт туда расписание на 7 дней и сможет его обновлять.\n"
            "Город можно указать сразу: /createschedule москва"
        )
        return
    await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        city = resolve_city(parts[1])
        if city is None:
            await message.reply("Город не разобрал. Пример: /createschedule санкт-петербург")
            return
    else:
        existing = await db.chat_schedule(message.chat.id)
        if existing:
            city = existing["city_code"]
        else:
            user = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
            city = user["city_code"]
    await _publish(message, db, city)


@router.callback_query(F.data == "sched:refresh")
async def refresh_schedule(callback: CallbackQuery, db: Database) -> None:
    existing = await db.chat_schedule(callback.message.chat.id)
    if existing is None:
        await callback.answer("Расписание в этом чате ещё не создавали", show_alert=True)
        return
    city_name = await db.city_name(existing["city_code"]) or existing["city_code"]
    quizzes = await db.quizzes_between(existing["city_code"], today_msk(), 7)
    try:
        await callback.message.edit_text(week_text(city_name, quizzes), reply_markup=_refresh_markup())
    except TelegramBadRequest:
        await callback.answer("Уже актуально")
        return
    await callback.answer("Обновил")
