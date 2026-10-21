from __future__ import annotations

import html
from datetime import datetime

from quizhub.timeutil import EVENING_HOUR, parse_stored

WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAY_LONG = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

STATUS_ICON = {
    "open": "🟢",
    "few": "🟡",
    "full": "🟠",
    "announce": "⚪",
}
STATUS_LABEL = {
    "open": "есть места",
    "few": "мало мест",
    "full": "мест нет",
    "announce": "анонс",
}


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def status_icon(status: str) -> str:
    return STATUS_ICON.get(status, "🟢")


def format_when(starts_at: str) -> str:
    moment = parse_stored(starts_at)
    weekday = WEEKDAY_SHORT[moment.weekday()]
    month = MONTHS[moment.month - 1]
    part = "вечер" if moment.hour >= EVENING_HOUR else "день"
    return f"{weekday}, {moment.day} {month} · {moment.strftime('%H:%M')} · {part}"


def format_day_label(moment: datetime) -> str:
    weekday = WEEKDAY_LONG[moment.weekday()]
    return f"{weekday}, {moment.day} {MONTHS[moment.month - 1]}"


def short_day(moment: datetime) -> str:
    return f"{WEEKDAY_SHORT[moment.weekday()]}, {moment.strftime('%d.%m')}"


def format_quiz_line(index: int, quiz: dict, counts: dict[str, int] | None = None) -> str:
    moment = parse_stored(quiz["starts_at"])
    lines = [
        f"<b>{index}. {status_icon(quiz['status'])} {short_day(moment)} {moment.strftime('%H:%M')} · {esc(quiz['title'])}</b>",
        f"{esc(quiz['organizer'])} · {esc(quiz['place'])}"
        + (f" · {esc(quiz['price'])}" if quiz.get("price") else ""),
    ]
    if counts and (counts.get("team") or counts.get("player")):
        bits = []
        if counts.get("team"):
            bits.append(f"команд: {counts['team']}")
        if counts.get("player"):
            bits.append(f"игроков: {counts['player']}")
        lines.append("Ищут " + ", ".join(bits))
    return "\n".join(lines)


def format_quiz_card(quiz: dict, city_name: str, posts: list[dict]) -> str:
    price = f"\nСтоимость: {esc(quiz['price'])}" if quiz.get("price") else ""
    team = f"\nВ команде до {int(quiz['max_team'])} человек" if quiz.get("max_team") else ""
    description = f"\n\n{esc(quiz['description'])}" if quiz.get("description") else ""
    tags = quiz.get("tags") or ""
    tag_line = f"\nТеги: {esc(tags)}" if tags else ""
    looking = _format_posts(posts)
    return (
        f"{status_icon(quiz['status'])} <b>{esc(quiz['title'])}</b>\n"
        f"{esc(STATUS_LABEL.get(quiz['status'], ''))}\n\n"
        f"{esc(format_when(quiz['starts_at']))}\n"
        f"Город: {esc(city_name)}\n"
        f"Организатор: {esc(quiz['organizer'])}\n"
        f"Место: {esc(quiz['place'])}"
        f"{price}{team}{tag_line}{description}{looking}"
    )


def _format_posts(posts: list[dict]) -> str:
    if not posts:
        return ""
    teams = [post for post in posts if post["kind"] == "team"]
    players = [post for post in posts if post["kind"] == "player"]
    chunks: list[str] = []
    if players:
        chunks.append("<b>Ищут игрока:</b>\n" + "\n".join(_post_line(post) for post in players))
    if teams:
        chunks.append("<b>Ищут команду:</b>\n" + "\n".join(_post_line(post) for post in teams))
    return "\n\n" + "\n\n".join(chunks)


def _post_line(post: dict) -> str:
    who = esc(post["name"])
    if post.get("username"):
        who += f" (@{esc(post['username'])})"
    note = f" — {esc(post['note'])}" if post.get("note") else ""
    return f"• {who}{note}"


def digest_header(city_name: str, subtitle: str, total: int, quiz_word: str) -> str:
    return f"<b>{esc(city_name)}</b>\n{esc(subtitle)}\nНашёл {total} {quiz_word}."
