"""Опрос «кто идёт» по тексту объявления о квизе."""

from __future__ import annotations

import re
from dataclasses import dataclass

_URL = re.compile(r"\s*\(https?://[^)]*\)")
_PRICE = re.compile(r"💰\s*(.+)$")
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
    current: QuizNotice | None = None
    for line in _lines(text):
        kind, payload = _classify(line)
        if kind == "organizer":
            if current is not None and current.useful:
                notices.append(current)
            current = QuizNotice(organizer=payload)
            continue
        if current is None:
            current = QuizNotice()
        if kind == "title":
            if current.title:
                if current.useful:
                    notices.append(current)
                current = QuizNotice(title=payload)
            else:
                current.title = payload
        elif kind == "when":
            current.when, current.price = _split_when_price(payload)
        elif kind == "place":
            current.place = payload
            if current.useful:
                notices.append(current)
            current = None
        elif not current.title:
            current.title = payload
    if current is not None and current.useful:
        notices.append(current)
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
    if line.startswith(_ORGANIZER):
        return "organizer", _strip_mark(line)
    if line.startswith(_TITLE):
        return "title", _strip_mark(line)
    if line.startswith(_WHEN):
        return "when", _strip_mark(line)
    if line.startswith(_PLACE):
        return "place", _strip_mark(line)
    return "other", line.strip()


def _strip_mark(line: str) -> str:
    text = line.strip()
    for mark in _MARKS:
        if text.startswith(mark):
            return text[len(mark) :].strip()
    return text


def _split_when_price(text: str) -> tuple[str, str]:
    match = _PRICE.search(text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), match.group(1).strip()
