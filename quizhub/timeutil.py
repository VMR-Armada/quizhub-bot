from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
EVENING_HOUR = 18


def now_msk() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


def today_msk() -> date:
    return datetime.now(MSK).date()


def parse_stored(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def format_stored(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def shift_days(start: date, days: int) -> tuple[str, str]:
    """Полуинтервал [start, start+days) в строках хранилища."""
    begin = datetime.combine(start, datetime.min.time())
    end = begin + timedelta(days=days)
    return format_stored(begin), format_stored(end)
