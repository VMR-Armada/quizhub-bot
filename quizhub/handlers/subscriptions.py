from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from quizhub.db import Database
from quizhub.format import esc
from quizhub.handlers.common import _remember
from quizhub.keyboards import subscriptions_keyboard
from quizhub.search import parse_search
from quizhub.timeutil import today_msk

router = Router()


def _clean_topic(text: str) -> str | None:
    parsed = parse_search(text, today_msk())
    if not parsed.tokens:
        return None
    topic = " ".join(parsed.tokens)
    if parsed.part == "day":
        topic = f"день {topic}"
    elif parsed.part == "evening":
        topic = f"вечер {topic}"
    return topic


async def _show(message: Message, db: Database, telegram_id: int) -> None:
    items = await db.subscriptions(telegram_id)
    if not items:
        await message.answer(
            "Подписок нет.\n"
            "Напишите /sub и тему: <code>/sub русский рок</code>, <code>/sub гарри поттер</code>, "
            "<code>/sub ким</code>.\n"
            "Дата в подписке не нужна: пришлю квиз, когда он появится в каталоге."
        )
        return
    lines = ["<b>Ваши подписки</b>", "Крестик снимает подписку.", ""]
    for item in items:
        lines.append(f"• {esc(item['query'])} — {esc(item['city_name'])}")
    await message.answer("\n".join(lines), reply_markup=subscriptions_keyboard(items))


@router.message(Command("sub"))
async def cmd_sub(message: Message, db: Database) -> None:
    user = await _remember(message, db)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        await _show(message, db, user["telegram_id"])
        return
    topic = _clean_topic(parts[1])
    if topic is None:
        await message.answer("Нужна тема. Например: /sub музыка или /sub игра престолов.")
        return
    added = await db.add_subscription(user["telegram_id"], user["city_code"], topic)
    city = await db.city_name(user["city_code"]) or user["city_code"]
    if added:
        await message.answer(f"Подписал на «{esc(topic)}» в городе {esc(city)}. Пришлю, когда такая игра появится.")
    else:
        await message.answer("Такая подписка уже есть.")


@router.callback_query(F.data == "subs")
async def open_subs(callback: CallbackQuery, db: Database) -> None:
    await db.ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await callback.answer()
    await _show(callback.message, db, callback.from_user.id)


@router.callback_query(F.data.startswith("unsub:"))
async def unsub(callback: CallbackQuery, db: Database) -> None:
    subscription_id = int(callback.data.split(":", 1)[1])
    await db.delete_subscription(callback.from_user.id, subscription_id)
    await callback.answer("Подписка снята")
    await _show(callback.message, db, callback.from_user.id)


@router.callback_query(F.data.startswith("subadd:"))
async def sub_from_quiz(callback: CallbackQuery, db: Database) -> None:
    topic = _clean_topic(callback.data.split(":", 1)[1])
    if topic is None:
        await callback.answer("Эту тему не разобрал", show_alert=True)
        return
    user = await db.ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    added = await db.add_subscription(user["telegram_id"], user["city_code"], topic)
    city = await db.city_name(user["city_code"]) or user["city_code"]
    await callback.answer("Подписка включена" if added else "Уже подписаны")
    if added:
        text = f"Подписал на «{esc(topic)}» — {esc(city)}."
    else:
        text = f"Подписка «{esc(topic)}» в городе {esc(city)} уже есть."
    await callback.message.answer(text)
