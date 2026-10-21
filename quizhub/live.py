"""Живое расписание с публичной афиши quiztoday.ru.

Время в ответе записано как локальное, хотя у метки стоит суффикс Z.
Сайт показывает именно эти часы, без перевода в другой пояс.
"""

from __future__ import annotations

from datetime import date, datetime

import aiohttp

API_DAYS = "https://quiztoday.ru/api/quizzes/{city}/days/{day}/{days}"
API_QUIZ = "https://quiztoday.ru/api/quiz/{city}/{quiz_id}"


class ScheduleUnavailable(Exception):
    """Публичная афиша сейчас не ответила."""


def quizzes_from_payload(payload: dict, city_code: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    table = data.get("table") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        raise ScheduleUnavailable
    found: list[dict] = []
    seen: set[str] = set()
    for organizer_name, days in table.items():
        if not isinstance(days, dict):
            continue
        for cell in days.values():
            if not isinstance(cell, dict):
                continue
            for bucket in ("dayQuizzes", "eveningQuizzes"):
                items = cell.get(bucket) or []
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    quiz = _normalize(item, city_code, str(organizer_name))
                    if quiz is None or quiz["id"] in seen:
                        continue
                    seen.add(quiz["id"])
                    found.append(quiz)
    found.sort(key=lambda row: (row["starts_at"], row["organizer"], row["title"]))
    return found


def quiz_from_payload(payload: dict, city_code: str) -> dict | None:
    quiz = payload.get("quiz") if isinstance(payload, dict) else None
    if not isinstance(quiz, dict):
        return None
    organizer = str(quiz.get("Организатор") or "")
    return _normalize(quiz, city_code, organizer)


async def fetch_schedule(city_code: str, start: date, days: int) -> list[dict]:
    url = API_DAYS.format(city=city_code, day=start.isoformat(), days=max(1, days))
    payload = await _get_json(url)
    if not payload.get("success"):
        raise ScheduleUnavailable
    return quizzes_from_payload(payload, city_code)


async def fetch_quiz(city_code: str, quiz_id: str) -> dict | None:
    url = API_QUIZ.format(city=city_code, quiz_id=quiz_id)
    try:
        payload = await _get_json(url)
    except ScheduleUnavailable:
        return None
    if not payload.get("success"):
        return None
    return quiz_from_payload(payload, city_code)


async def _get_json(url: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers={"User-Agent": "quizhub-bot"},
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise ScheduleUnavailable
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise ScheduleUnavailable from error
    if not isinstance(payload, dict):
        raise ScheduleUnavailable
    return payload


def _normalize(item: dict, city_code: str, organizer_name: str) -> dict | None:
    quiz_id = str(item.get("ID") or "").strip()
    starts_at = _starts_at(item.get("Дата"))
    title = str(item.get("Название") or "").strip()
    if not quiz_id or starts_at is None or not title:
        return None
    organizer = str(item.get("Организатор") or organizer_name).strip() or organizer_name
    url = str(item.get("Ссылка") or "").strip()
    if not url.startswith(("http://", "https://")):
        url = ""
    return {
        "id": quiz_id,
        "city_code": city_code,
        "organizer": organizer,
        "title": title,
        "starts_at": starts_at,
        "place": str(item.get("Место") or "").strip(),
        "price": _price(item.get("Стоимость")),
        "max_team": _int_or_none(item.get("Максимум в команде")),
        "description": str(item.get("Описание") or "").strip(),
        "url": url,
        "status": _status(item),
        "tags": _tags(item.get("Теги")),
    }


def _starts_at(value: object) -> str | None:
    text = str(value or "")
    if len(text) < 16 or text[10] != "T":
        return None
    stored = f"{text[:10]} {text[11:16]}"
    try:
        datetime.strptime(stored, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return stored


def _price(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return f"{int(value)} ₽"
    text = str(value).strip()
    if text.isdigit():
        return f"{text} ₽"
    return text


def _tags(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _status(item: dict) -> str:
    raw = f"{item.get('Внешний статус') or ''} {item.get('Статус') or ''}".casefold()
    if "🟠" in raw or "full" in raw or "мест нет" in raw:
        return "full"
    if "🟡" in raw or "few" in raw or "мало" in raw:
        return "few"
    if "⚪" in raw or "announce" in raw or "анонс" in raw:
        return "announce"
    return "open"


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
