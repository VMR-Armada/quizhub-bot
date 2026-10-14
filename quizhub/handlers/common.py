from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from quizhub.config import Settings
from quizhub.db import Database
from quizhub.format import esc
from quizhub.keyboards import cities_keyboard, main_keyboard
from quizhub.listing import collect, describe, render_results
from quizhub.textutil import plural_quizzes
from quizhub.timeutil import today_msk

router = Router()

HELP = (
    "<b>Как искать</b>\n"
    "Напишите обычную фразу, как в переписке:\n"
    "• сегодня\n"
    "• завтра вечером\n"
    "• суббота музыка\n"
    "• 18.10 кино\n"
    "• выходные рок\n"
    "• гарри поттер\n"
    "• ким — это квизы, где в названии есть и кино, и музыка\n\n"
    "День — всё до 18:00, вечер — с 18:00.\n"
    "Город можно назвать в запросе: «москва завтра».\n\n"
    "<b>Команды</b>\n"
    "/city — сменить город\n"
    "/today и /tomorrow — квизы на день\n"
    "/sub тема — подписаться на новые квизы\n"
    "/table — таблица на сайте, со своим фильтром организаторов\n"
    "/find — оставить объявление «ищу команду» или «ищу игрока»\n"
    "/stats — короткая сводка\n"
    "/cancel — прервать текущий шаг\n\n"
    "В групповом чате бот молчит, пока его не позовут: "
    "<code>@бот завтра вечером</code>.\n"
    "Команда /createschedule вешает в чат расписание на неделю."
)


async def _remember(message: Message, db: Database) -> dict:
    user = message.from_user
    return await db.ensure_user(
        user.id,
        user.username,
        user.first_name,
    )


async def show_search(message: Message, db: Database, user: dict, text: str, *, edit: bool = False) -> None:
    parsed, city, found = await collect(db, text, user["city_code"], today_msk())
    subtitle = describe(parsed, text)
    if parsed.city_code and parsed.city_code != user["city_code"]:
        subtitle = "город из запроса · " + subtitle
    await db.save_search(user["telegram_id"], subtitle, city, [row["id"] for row in found])
    page_text, keyboard = await render_results(
        db,
        city_code=city,
        subtitle=subtitle,
        quiz_ids=[row["id"] for row in found],
        page=0,
    )
    if edit:
        await message.edit_text(page_text, reply_markup=keyboard)
    else:
        await message.answer(page_text, reply_markup=keyboard)


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, db: Database) -> None:
    user = await _remember(message, db)
    city = await db.city_name(user["city_code"]) or "Санкт-Петербург"
    await message.answer(
        f"Привет, {esc(message.from_user.first_name)}.\n"
        "Я QuizHub: расписание барных квизов, подписки на темы и поиск команды.\n\n"
        f"Сейчас город: <b>{esc(city)}</b>.\n"
        "Напишите, например, <b>завтра вечером музыка</b> — или нажмите кнопку.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database, settings: Settings) -> None:
    user = await _remember(message, db)
    extra = f"\n\nВаш Telegram ID: <code>{user['telegram_id']}</code>"
    if settings.is_admin(user["telegram_id"]):
        extra += "\nВы администратор: /newquiz добавляет игру в каталог."
    elif not settings.admin_ids:
        extra += (
            "\nЧтобы добавлять квизы, впишите этот ID в ADMIN_IDS в файле .env и перезапустите бота."
        )
    await message.answer(HELP + extra, reply_markup=main_keyboard())


@router.message(Command("city"), F.chat.type == "private")
@router.callback_query(F.data == "pickcity")
async def cmd_city(event: Message | CallbackQuery, db: Database) -> None:
    message = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
        await db.ensure_user(event.from_user.id, event.from_user.username, event.from_user.first_name)
    else:
        await _remember(event, db)
    cities = await db.cities()
    await message.answer("Выберите город. Он сохранится, пока не смените его снова.", reply_markup=cities_keyboard(cities))


@router.callback_query(F.data.startswith("city:"))
async def set_city(callback: CallbackQuery, db: Database) -> None:
    code = callback.data.split(":", 1)[1]
    name = await db.city_name(code)
    if name is None:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await db.ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await db.set_city(callback.from_user.id, code)
    await callback.answer(name)
    await callback.message.answer(f"Город: <b>{esc(name)}</b>. Можно сразу писать запрос.", reply_markup=main_keyboard())


@router.message(Command("today", "tomorrow"), F.chat.type == "private")
async def cmd_day(message: Message, db: Database) -> None:
    user = await _remember(message, db)
    text = "сегодня" if message.text.startswith("/today") else "завтра"
    await show_search(message, db, user, text)


@router.callback_query(F.data.startswith("quick:"))
async def quick_search(callback: CallbackQuery, db: Database) -> None:
    user = await db.ensure_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await callback.answer()
    await show_search(callback.message, db, user, callback.data.split(":", 1)[1])


@router.callback_query(F.data.startswith("page:"))
async def turn_page(callback: CallbackQuery, db: Database) -> None:
    cache = await db.search_cache(callback.from_user.id)
    if cache is None:
        await callback.answer("Поиск устарел, напишите запрос ещё раз", show_alert=True)
        return
    page = int(callback.data.split(":", 1)[1])
    await db.set_search_page(callback.from_user.id, page)
    text, keyboard = await render_results(
        db,
        city_code=cache["city_code"],
        subtitle=cache["query_text"],
        quiz_ids=cache["quiz_ids"],
        page=page,
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.message(Command("table"), F.chat.type == "private")
async def cmd_table(message: Message, db: Database, settings: Settings) -> None:
    user = await _remember(message, db)
    token = await db.get_or_create_table_link(user["telegram_id"], user["city_code"])
    city = await db.city_name(user["city_code"]) or user["city_code"]
    base = settings.public_base_url
    await message.answer(
        f"<b>{esc(city)}</b>\n"
        "Персональная таблица, в ней можно скрыть организаторов:\n"
        f"{base}/t/{token}\n\n"
        "Общая таблица города:\n"
        f"{base}/dashboard/{user['city_code']}\n\n"
        "Ссылка открывается на компьютере, где запущен бот. "
        "Чтобы отправить её другим, укажите в PUBLIC_BASE_URL внешний адрес."
    )


@router.message(Command("stats"), F.chat.type == "private")
async def cmd_stats(message: Message, db: Database) -> None:
    user = await _remember(message, db)
    city = await db.city_name(user["city_code"]) or user["city_code"]
    _, _, found = await collect(db, "", user["city_code"], today_msk())
    subs = await db.subscriptions(user["telegram_id"])
    posts = await db.count_team_posts(user["telegram_id"])
    await message.answer(
        f"<b>{esc(city)}</b>\n"
        f"В ближайшие 3 недели: {len(found)} {plural_quizzes(len(found))}.\n"
        f"Подписок: {len(subs)}.\n"
        f"Ваших объявлений о поиске команды или игрока: {posts}."
    )


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять.")
        return
    await state.clear()
    await message.answer("Остановился. Можно снова искать квизы.")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
