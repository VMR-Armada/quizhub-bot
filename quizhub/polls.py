"""Опрос «кто идёт» по тексту объявления о квизе."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

_URL = re.compile(r"\s*(?:\(https?://[^)]*\)|https?://\S+)")
_PRICE = re.compile(r"💰\s*(.+)$")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_MONTH = re.compile(r"(янв|фев|мар|апр|мая|май|июн|июл|авг|сен|окт|ноя|дек)", re.IGNORECASE)
_MONTH_NUM = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_HEADER = "появились новые квизы"

_ORGANIZER = ("👥", "👤")
_TITLE = ("🟢", "🟡", "🟠", "⚪", "🔴", "✅")
_WHEN = ("🗓", "📅")
_PLACE = ("🍻", "📍", "🍺", "🏛")
_MARKS = _ORGANIZER + _TITLE + _WHEN + _PLACE

OPTIONS = ("Иду", "Возможно", "Не иду")
QUESTION_LIMIT = 300


@dataclass
class QuizNotice:
    organizer: str = ""
    title: str = ""
    when: str = ""
    place: str = ""
    price: str = ""

    @property
    def useful(self) -> bool:
        return bool(self.title or self.organizer)


def parse_notices(text: str) -> list[QuizNotice]:
    """Разбирает одно или несколько объявлений из сообщения подписки."""
    notices: list[QuizNotice] = []
    current = QuizNotice()

    def flush() -> None:
        nonlocal current
        if current.useful:
            notices.append(current)
        current = QuizNotice()

    for line in _lines(text):
        kind, payload = _classify(line)
        if not payload:
            continue
        if kind == "other":
            kind = _guess(current, payload)
        if kind == "organizer" and (current.title or current.when or current.place):
            flush()
        if kind == "organizer":
            current.organizer = payload
        elif kind == "title":
            if current.title:
                flush()
            current.title = payload
        elif kind == "when":
            current.when, price = _split_when_price(payload)
            if price:
                current.price = price
        elif kind == "place":
            current.place = payload
            flush()
    flush()
    return notices


def parse_notice_start(when: str, today: date) -> datetime | None:
    """Достаёт дату и время из строки вроде «Сб, 28 ноя. 19:30»."""
    text = when.strip()
    if not text:
        return None
    clock = _TIME.search(text)
    hour = int(clock.group(1)) if clock else 0
    minute = int(clock.group(2)) if clock else 0
    if hour > 23 or minute > 59:
        return None
    numeric = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", text)
    word = re.search(r"\b(\d{1,2})\s+([а-яё]{3,})", text, flags=re.IGNORECASE)
    try:
        if numeric and numeric.group(3):
            year = int(numeric.group(3))
            if year < 100:
                year += 2000
            day = date(year, int(numeric.group(2)), int(numeric.group(1)))
        elif numeric:
            day = _nearest_date(today, int(numeric.group(1)), int(numeric.group(2)))
        elif word:
            month = _MONTH_NUM.get(word.group(2).casefold()[:3])
            if month is None:
                return None
            day = _nearest_date(today, int(word.group(1)), month)
        else:
            return None
    except ValueError:
        return None
    return datetime.combine(day, time(hour, minute))


def format_week(rows: list[dict], start: date, end: date) -> str:
    last = end - timedelta(days=1)
    header = f"<b>{start.strftime('%d.%m')}–{last.strftime('%d.%m')}</b>"
    if not rows:
        return (
            f"{header}\n"
            "На этой неделе ещё нет квизов с опросом.\n"
            "Ответьте /add на опрос или /poll на объявление — здесь будут голоса по каждому варианту."
        )
    lines = [header, ""]
    for row in rows:
        moment = datetime.strptime(row["starts_at"], "%Y-%m-%d %H:%M")
        when = f"{_WEEKDAYS[moment.weekday()]}, {moment.strftime('%d.%m')}"
        if _TIME.search(row.get("when_text") or ""):
            when += f" · {moment.strftime('%H:%M')}"
        title = row.get("title") or ""
        lines.append(f"<b>{_esc(when)}</b>")
        if title and title != row.get("organizer"):
            lines.append(_esc(title))
        place = row.get("place") or ""
        where = " · ".join(part for part in (row.get("organizer") or "", place) if part)
        if where:
            lines.append(_esc(where))
        lines.extend(format_option_lines(row.get("options") or [], int(row.get("going") or 0)))
        lines.append("")
    return "\n".join(lines).strip()


def format_option_lines(options: list[dict], going: int = 0) -> list[str]:
    if not options:
        return [f"Иду — {going}"]
    return [f"{_esc(option.get('text') or 'Вариант')} — {int(option.get('count') or 0)}" for option in options]


def notice_from_question(question: str, today: date) -> QuizNotice:
    """Собирает квиз обратно из текста опроса, который собрал бот."""
    lines = [line.strip() for line in question.splitlines() if line.strip()]
    if lines and lines[-1].casefold().rstrip("?").strip() in {"идём", "идем"}:
        lines.pop()
    notice = QuizNotice()
    if not lines:
        return notice
    notice.title = lines[0]
    for bit in [part.strip() for part in " · ".join(lines[1:]).split("·") if part.strip()]:
        if re.fullmatch(r"\d+\s*₽", bit):
            notice.price = re.sub(r"\D", "", bit)
            continue
        if not notice.when and parse_notice_start(bit, today) is not None:
            notice.when = bit
            continue
        if not notice.organizer:
            notice.organizer = bit
            continue
        if not notice.place:
            notice.place = bit
            continue
        notice.place = f"{notice.place} · {bit}"
    return notice


def poll_question(notice: QuizNotice) -> str:
    title = notice.title or notice.organizer or "Квиз"
    price = f"{notice.price} ₽" if notice.price.isdigit() else notice.price
    bits = [bit for bit in (notice.organizer, notice.when, notice.place, price) if bit and bit != title]
    details = " · ".join(bits)
    tail = "Идём?"
    if not details:
        question = f"{title}\n{tail}"
    else:
        question = f"{title}\n{details}\n{tail}"
    if len(question) <= QUESTION_LIMIT:
        return question
    room = QUESTION_LIMIT - len(title) - len(tail) - 2
    if room < 2 or not details:
        return title[: QUESTION_LIMIT - 1] + "…"
    trimmed = details[: room - 1].rstrip() + "…"
    return f"{title}\n{trimmed}\n{tail}"


def _lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = _URL.sub("", raw).strip()
        if not line:
            continue
        if line.casefold().startswith(_HEADER):
            continue
        lines.append(line)
    return lines


def _classify(line: str) -> tuple[str, str]:
    mark, payload = _peel_mark(line)
    if mark in _ORGANIZER:
        return "organizer", payload
    if mark in _TITLE:
        return "title", payload
    if mark in _WHEN:
        return "when", payload
    if mark in _PLACE:
        return "place", payload
    if _looks_when(payload):
        return "when", payload
    return "other", payload


def _guess(current: QuizNotice, payload: str) -> str:
    if _looks_when(payload):
        return "when"
    if not current.organizer and not current.title:
        return "organizer"
    if not current.title:
        return "title"
    if not current.when:
        return "when"
    if not current.place:
        return "place"
    return "organizer"


def _looks_when(text: str) -> bool:
    return "💰" in text or _TIME.search(text) is not None or _MONTH.search(text) is not None


def _peel_mark(line: str) -> tuple[str, str]:
    text = line.strip()
    for mark in sorted(_MARKS, key=len, reverse=True):
        if text.startswith(mark):
            return mark, text[len(mark) :].strip(" \uFE0F")
    return "", text


def _nearest_date(today: date, day: int, month: int) -> date:
    choices = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            choices.append(date(year, month, day))
        except ValueError:
            continue
    if not choices:
        raise ValueError
    return min(choices, key=lambda item: abs((item - today).days))


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def _split_when_price(text: str) -> tuple[str, str]:
    match = _PRICE.search(text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), match.group(1).strip()
