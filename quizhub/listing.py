from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from quizhub.db import Database
from quizhub.format import digest_header, esc, format_quiz_line
from quizhub.keyboards import results_keyboard
from quizhub.search import SearchQuery, matches, parse_search
from quizhub.textutil import plural_quizzes
from quizhub.timeutil import today_msk

PAGE_SIZE = 8
MAX_RESULTS = 40


async def collect(db: Database, text: str, user_city: str, today=None) -> tuple[SearchQuery, str, list[dict]]:
    today = today or today_msk()
    parsed = parse_search(text, today)
    city = parsed.city_code or user_city
    if parsed.date_from is not None and parsed.date_to is not None:
        start = parsed.date_from
        days = (parsed.date_to - parsed.date_from).days + 1
    else:
        start = today
        days = 21
    rows = await db.quizzes_between(city, start, days)
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


async def render_results(
    db: Database,
    *,
    city_code: str,
    subtitle: str,
    quiz_ids: list[int],
    page: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    city_name = await db.city_name(city_code) or city_code
    if not quiz_ids:
        text = (
            f"<b>{esc(city_name)}</b>\n{esc(subtitle)}\n\n"
            "Ничего не нашёл. Попробуйте убрать время суток или поискать по другому слову: "
            "музыка, кино, классика, рок, литература."
        )
        return text, None

    pages = max(1, (len(quiz_ids) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk_ids = quiz_ids[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    quizzes = await db.get_quizzes(chunk_ids)
    counts = await db.team_counts(chunk_ids)
    lines = [
        digest_header(city_name, subtitle, len(quiz_ids), plural_quizzes(len(quiz_ids))),
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
