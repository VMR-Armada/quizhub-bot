from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from quizhub.db import Database
from quizhub.format import digest_header, esc, format_quiz_line
from quizhub.keyboards import results_keyboard
from quizhub.live import fetch_quiz, fetch_schedule
from quizhub.search import SearchQuery, matches, parse_search
from quizhub.textutil import plural_quizzes
from quizhub.timeutil import today_msk

PAGE_SIZE = 8
MAX_RESULTS = 40


async def collect(
    db: Database,
    text: str,
    user_city: str,
    today=None,
    *,
    source=None,
) -> tuple[SearchQuery, str, list[dict]]:
    today = today or today_msk()
    parsed = parse_search(text, today)
    city = parsed.city_code or user_city
    if parsed.date_from is not None and parsed.date_to is not None:
        start = parsed.date_from
        days = (parsed.date_to - parsed.date_from).days + 1
    else:
        start = today
        days = 21
    load = source or fetch_schedule
    rows = await load(city, start, days)
    found = [row for row in rows if matches(row, parsed)]
    if not found and parsed.tokens:
        relaxed = SearchQuery(
            date_from=parsed.date_from,
            date_to=parsed.date_to,
            part=parsed.part,
        )
        found = [row for row in rows if matches(row, relaxed)]
        parsed.relaxed = bool(found)
    found.sort(key=lambda row: (row["starts_at"], row["organizer"], row["title"]))
    return parsed, city, found[:MAX_RESULTS]


def describe(parsed: SearchQuery, source_text: str) -> str:
    bits: list[str] = []
    if parsed.date_from and parsed.date_from == parsed.date_to:
        bits.append(parsed.date_from.strftime("%d.%m"))
    elif parsed.date_from and parsed.date_to:
        bits.append(f"{parsed.date_from.strftime('%d.%m')}–{parsed.date_to.strftime('%d.%m')}")
    else:
        bits.append("ближайшие 3 недели")
    if parsed.part == "day":
        bits.append("до 18:00")
    elif parsed.part == "evening":
        bits.append("после 18:00")
    if parsed.tokens:
        bits.append("«" + " ".join(parsed.tokens) + "»")
    elif not bits:
        bits.append(source_text.strip())
    return " · ".join(bits)


def cached_quiz(items: list, quiz_id: object) -> dict | None:
    wanted = str(quiz_id)
    for item in items or []:
        if isinstance(item, dict) and str(item.get("id")) == wanted:
            return item
    return None


async def resolve_quiz(db: Database, telegram_id: int, raw_id: str) -> dict | None:
    if str(raw_id).isdigit():
        stored = await db.get_quiz(int(raw_id))
        if stored is not None:
            return stored
    cache = await db.search_cache(telegram_id)
    found = cached_quiz(cache["quiz_ids"] if cache else [], raw_id)
    if found is not None:
        return found
    if cache is None:
        return None
    return await fetch_quiz(cache["city_code"], raw_id)


async def _materialize(db: Database, items: list) -> list[dict]:
    if not items:
        return []
    if isinstance(items[0], dict):
        return list(items)
    return await db.get_quizzes([int(item) for item in items])


async def render_results(
    db: Database,
    *,
    city_code: str,
    subtitle: str,
    quiz_ids: list,
    page: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    city_name = await db.city_name(city_code) or city_code
    quizzes_all = await _materialize(db, quiz_ids)
    if not quizzes_all:
        text = (
            f"<b>{esc(city_name)}</b>\n{esc(subtitle)}\n\n"
            "Ничего не нашёл. Попробуйте убрать время суток или поискать по другому слову: "
            "музыка, кино, классика, рок, литература."
        )
        return text, None

    pages = max(1, (len(quizzes_all) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    quizzes = quizzes_all[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    counts = await db.team_counts([quiz["id"] for quiz in quizzes])
    lines = [
        digest_header(city_name, subtitle, len(quizzes_all), plural_quizzes(len(quizzes_all))),
        f"Страница {page + 1} из {pages}. Номер открывает карточку.",
        "",
    ]
    for index, quiz in enumerate(quizzes, start=1):
        lines.append(format_quiz_line(index, quiz, counts.get(quiz["id"])))
        lines.append("")
    keyboard = results_keyboard(
        [quiz["id"] for quiz in quizzes],
        page,
        page > 0,
        page < pages - 1,
    )
    return "\n".join(lines).strip(), keyboard
