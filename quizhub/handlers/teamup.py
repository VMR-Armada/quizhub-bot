from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizhub.db import Database
from quizhub.format import esc
from quizhub.handlers.common import _remember
from quizhub.listing import PAGE_SIZE, resolve_quiz

router = Router()


class TeamUp(StatesGroup):
    number = State()
    name = State()
    note = State()


def _kind_keyboard(quiz_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ищу игрока", callback_data=f"want:player:{quiz_id}"),
                InlineKeyboardButton(text="Ищу команду", callback_data=f"want:team:{quiz_id}"),
            ]
        ]
    )


@router.message(Command("find"))
@router.callback_query(F.data == "findmenu")
async def start_find(event: Message | CallbackQuery, state: FSMContext, db: Database) -> None:
    user_id = event.from_user.id
    cache = await db.search_cache(user_id)
    message = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    if cache is None or not cache["quiz_ids"]:
        await message.answer("Сначала найдите квиз, например: завтра вечером. Потом вернитесь к этой кнопке.")
        return
    page = int(cache["page"])
    chunk = cache["quiz_ids"][page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    await state.set_state(TeamUp.number)
    await message.answer(
        "Напишите номер квиза с текущей страницы поиска, от 1 до "
        f"{len(chunk)}. /cancel — выйти."
    )


@router.message(TeamUp.number, F.text, ~F.text.startswith("/"))
async def pick_number(message: Message, state: FSMContext, db: Database) -> None:
    cache = await db.search_cache(message.from_user.id)
    if cache is None:
        await state.clear()
        await message.answer("Список поиска пропал. Напишите запрос ещё раз.")
        return
    chunk = cache["quiz_ids"][int(cache["page"]) * PAGE_SIZE : (int(cache["page"]) + 1) * PAGE_SIZE]
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(chunk):
        await message.answer(f"Нужна цифра от 1 до {len(chunk)}.")
        return
    item = chunk[int(raw) - 1]
    quiz = item if isinstance(item, dict) else await resolve_quiz(db, message.from_user.id, str(item))
    await state.clear()
    if quiz is None:
        await message.answer("Этот квиз уже не в каталоге.")
        return
    await message.answer(f"«{esc(quiz['title'])}». Кого ищете?", reply_markup=_kind_keyboard(quiz["id"]))


@router.callback_query(F.data.startswith("want:"))
async def choose_kind(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, kind, raw_id = callback.data.split(":")
    if kind not in {"player", "team"}:
        await callback.answer()
        return
    quiz = await resolve_quiz(db, callback.from_user.id, raw_id)
    if quiz is None:
        await callback.answer("Квиз не найден", show_alert=True)
        return
    await state.set_state(TeamUp.name)
    await state.update_data(quiz_id=quiz["id"], kind=kind)
    await callback.answer()
    if kind == "team":
        prompt = "Как называется ваша команда или как к вам обращаться?"
    else:
        prompt = "Как к вам обращаться?"
    await callback.message.answer(f"{prompt}\nИмя увидят в карточке квиза. /cancel — выйти.")


@router.message(TeamUp.name, F.text, ~F.text.startswith("/"))
async def got_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not 2 <= len(name) <= 80:
        await message.answer("Имя нужно от 2 до 80 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(TeamUp.note)
    await message.answer("Коротко напишите, кого ищете. Или отправьте «-», чтобы пропустить.")


@router.message(TeamUp.note, F.text, ~F.text.startswith("/"))
async def got_note(message: Message, state: FSMContext, db: Database) -> None:
    note = message.text.strip()
    if note == "-":
        note = ""
    if len(note) > 300:
        await message.answer("Текст длиннее 300 символов. Сократите его.")
        return
    data = await state.get_data()
    user = await _remember(message, db)
    await db.add_team_post(
        quiz_id=data["quiz_id"],
        telegram_id=user["telegram_id"],
        kind=data["kind"],
        name=data["name"],
        note=note or None,
        username=message.from_user.username,
    )
    await state.clear()
    label = "команду" if data["kind"] == "team" else "игрока"
    await message.answer(f"Записал: ищете {label}. Объявление видно в карточке квиза и на сайте.")
