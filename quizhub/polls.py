"""Опрос «кто идёт» по тексту объявления о квизе."""

from __future__ import annotations

import re
from dataclasses import dataclass

_URL = re.compile(r"\s*(?:\(https?://[^)]*\)|https?://\S+)")
_PRICE = re.compile(r"💰\s*(.+)$")
_TIME = re.compile(r"\d{1,2}:\d{2}")
_MONTH = re.compile(r"(янв|фев|мар|апр|мая|май|июн|июл|авг|сен|окт|ноя|дек)", re.IGNORECASE)
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


def _split_when_price(text: str) -> tuple[str, str]:
    match = _PRICE.search(text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), match.group(1).strip()
