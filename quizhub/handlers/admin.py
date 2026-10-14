from __future__ import annotations

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from quizhub.config import Settings
from quizhub.db import Database
from quizhub.format import esc, format_when, status_icon
from quizhub.keyboards import cities_keyboard, confirm_keyboard, skip_keyboard, status_keyboard
from quizhub.notify import notify_new_quiz
from quizhub.tags import merge_tags
from quizhub.timeutil import format_stored

router = Router()

_TEXT = F.text & ~F.text.startswith("/")


class NewQuiz(StatesGroup):
    city = State()
    organizer = State()
    title = State()
    when = State()
    place = State()
    price = State()
    team = State()
    tags = State()
    status = State()
    url = State()
    description = State()
    confirm = State()


def _deny(settings: Settings, user_id: int) -> str | None:
    if settings.is_admin(user_id):
        return None
    if not settings.admin_ids:
        return (
            "Список администраторов пуст. Ваш ID есть в ответе на /help — "
            "впишите его в ADMIN_IDS в файле .env и перезапустите бота."
        )
    return "Добавлять квизы может только администратор."


@router.message(Command("newquiz"))
async def start_new(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Добавлять квизы нужно в личном чате с ботом.")
        return
    reason = _deny(settings, message.from_user.id)
    if reason:
        await message.answer(reason)
        return
    await state.set_state(NewQuiz.city)
    await message.answer("Город новой игры.", reply_markup=cities_keyboard(await db.cities(), prefix="newcity"))


@router.message(NewQuiz.city, _TEXT)
async def city_needs_button(message: Message) -> None:
    await message.answer("Город выбирается кнопкой выше. /cancel — выйти.")


@router.callback_query(NewQuiz.city, F.data.startswith("newcity:"))
async def pick_new_city(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    code = callback.data.split(":", 1)[1]
    name = await db.city_name(code)
    if name is None:
        await callback.answer("Нет такого города", show_alert=True)
        return
    await state.update_data(city_code=code, city_name=name)
    await state.set_state(NewQuiz.organizer)
    await callback.answer()
    await callback.message.answer(f"Город: {esc(name)}.\nНапишите организатора. Например: Северный квиз.")


@router.message(NewQuiz.organizer, _TEXT)
async def got_organizer(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not 2 <= len(name) <= 80:
        await message.answer("Название организатора — от 2 до 80 символов.")
        return
    await state.update_data(organizer=name)
    await state.set_state(NewQuiz.title)
    await message.answer("Название игры. Например: Кино и музыка.")


@router.message(NewQuiz.title, _TEXT)
async def got_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not 2 <= len(title) <= 120:
        await message.answer("Название — от 2 до 120 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(NewQuiz.when)
    await message.answer("Дата и время по Москве: <b>17.10.2026 20:00</b>")


@router.message(NewQuiz.when, _TEXT)
async def got_when(message: Message, state: FSMContext) -> None:
    try:
        moment = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Не разобрал дату. Нужен формат 17.10.2026 20:00.")
        return
    await state.update_data(starts_at=format_stored(moment))
    await state.set_state(NewQuiz.place)
    await message.answer("Место: бар и адрес одной строкой.")


@router.message(NewQuiz.place, _TEXT)
async def got_place(message: Message, state: FSMContext) -> None:
    place = message.text.strip()
    if not 2 <= len(place) <= 160:
        await message.answer("Место — от 2 до 160 символов.")
        return
    await state.update_data(place=place)
    await state.set_state(NewQuiz.price)
    await message.answer("Стоимость, например 500 ₽. Или «-», если её нет.", reply_markup=skip_keyboard("wiz:price"))


@router.callback_query(NewQuiz.price, F.data == "wiz:price")
@router.message(NewQuiz.price, _TEXT)
async def got_price(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        price = None
        await event.answer()
        message = event.message
    else:
        raw = event.text.strip()
        price = None if raw == "-" else raw
        message = event
    if price is not None and len(price) > 40:
        await message.answer("Слишком длинная стоимость.")
        return
    await state.update_data(price=price)
    await state.set_state(NewQuiz.team)
    await message.answer("Сколько человек максимум в команде? Число или «-».", reply_markup=skip_keyboard("wiz:team"))


@router.callback_query(NewQuiz.team, F.data == "wiz:team")
@router.message(NewQuiz.team, _TEXT)
async def got_team(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        max_team = None
        await event.answer()
        message = event.message
    else:
        raw = event.text.strip()
        message = event
        if raw == "-":
            max_team = None
        elif raw.isdigit() and 1 <= int(raw) <= 30:
            max_team = int(raw)
        else:
            await message.answer("Нужно число от 1 до 30 или «-».")
            return
    await state.update_data(max_team=max_team)
    await state.set_state(NewQuiz.tags)
    await message.answer(
        "Теги через запятую: кино, музыка, рок.\n"
        "Часть тегов я допишу сам: «кино и музыка» станет ещё и «ким», "
        "«игра престолов» — «сериалы». Можно отправить «-».",
        reply_markup=skip_keyboard("wiz:tags"),
    )


@router.callback_query(NewQuiz.tags, F.data == "wiz:tags")
@router.message(NewQuiz.tags, _TEXT)
async def got_tags(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        explicit: list[str] = []
        await event.answer()
        message = event.message
    else:
        raw = event.text.strip()
        message = event
        explicit = [] if raw == "-" else [part.strip() for part in raw.split(",") if part.strip()]
    data = await state.get_data()
    tags = merge_tags(explicit, data["title"], data.get("organizer") or "")
    await state.update_data(tags=tags)
    await state.set_state(NewQuiz.status)
    shown = ", ".join(tags) if tags else "без тегов"
    await message.answer(f"Теги: {esc(shown)}.\nКакой статус мест?", reply_markup=status_keyboard())


@router.message(NewQuiz.status, _TEXT)
async def status_needs_button(message: Message) -> None:
    await message.answer("Статус выбирается кнопкой.", reply_markup=status_keyboard())


@router.callback_query(NewQuiz.status, F.data.startswith("status:"))
async def got_status(callback: CallbackQuery, state: FSMContext) -> None:
    status = callback.data.split(":", 1)[1]
    if status not in {"open", "few", "full", "announce"}:
        await callback.answer()
        return
    await state.update_data(status=status)
    await state.set_state(NewQuiz.url)
    await callback.answer()
    await callback.message.answer(
        "Ссылка на регистрацию. Или «-», если её нет.",
        reply_markup=skip_keyboard("wiz:url"),
    )


@router.callback_query(NewQuiz.url, F.data == "wiz:url")
@router.message(NewQuiz.url, _TEXT)
async def got_url(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        url = None
        await event.answer()
        message = event.message
    else:
        raw = event.text.strip()
        message = event
        if raw == "-":
            url = None
        elif raw.startswith("http://") or raw.startswith("https://"):
            url = raw
        else:
            await message.answer("Ссылка должна начинаться с http:// или https://. Или отправьте «-».")
            return
    await state.update_data(url=url)
    await state.set_state(NewQuiz.description)
    await message.answer("Короткое описание. Или «-».", reply_markup=skip_keyboard("wiz:desc"))


@router.callback_query(NewQuiz.description, F.data == "wiz:desc")
@router.message(NewQuiz.description, _TEXT)
async def got_description(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        description = None
        await event.answer()
        message = event.message
    else:
        raw = event.text.strip()
        message = event
        description = None if raw == "-" else raw
    if description is not None and len(description) > 500:
        await message.answer("Описание длиннее 500 символов.")
        return
    await state.update_data(description=description)
    await state.set_state(NewQuiz.confirm)
    data = await state.get_data()
    tags = ", ".join(data.get("tags") or []) or "нет"
    price = data.get("price") or "не указана"
    team = data.get("max_team") or "не указан"
    await message.answer(
        "<b>Проверьте игру</b>\n"
        f"{status_icon(data['status'])} {esc(data['title'])}\n"
        f"{esc(data['city_name'])} · {esc(format_when(data['starts_at']))}\n"
        f"{esc(data['organizer'])}\n{esc(data['place'])}\n"
        f"Стоимость: {esc(price)}\nКоманда до: {esc(team)}\nТеги: {esc(tags)}",
        reply_markup=confirm_keyboard(),
    )


@router.message(NewQuiz.confirm, _TEXT)
async def confirm_needs_button(message: Message) -> None:
    await message.answer("Нажмите «Сохранить» или «Отмена».", reply_markup=confirm_keyboard())


@router.callback_query(NewQuiz.confirm, F.data == "quizdrop")
async def drop_quiz(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("Не сохранял.")


@router.callback_query(NewQuiz.confirm, F.data == "quizsave")
async def save_quiz(callback: CallbackQuery, state: FSMContext, db: Database, bot: Bot, settings: Settings) -> None:
    if _deny(settings, callback.from_user.id):
        await state.clear()
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    data = await state.get_data()
    quiz_id = await db.add_quiz(
        city_code=data["city_code"],
        organizer=data["organizer"],
        title=data["title"],
        starts_at=data["starts_at"],
        place=data["place"],
        price=data.get("price"),
        max_team=data.get("max_team"),
        description=data.get("description"),
        url=data.get("url"),
        status=data["status"],
        tags=list(data.get("tags") or []),
    )
    await state.clear()
    await callback.answer()
    await callback.message.answer(f"Игра сохранена, номер {quiz_id}. Рассылаю подписчикам.")
    await notify_new_quiz(bot, db, quiz_id)
