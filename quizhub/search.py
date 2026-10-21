from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from quizhub.textutil import normalize
from quizhub.timeutil import EVENING_HOUR

CITY_ALIASES = {
    "спб": "spb",
    "питер": "spb",
    "петербург": "spb",
    "москва": "msk",
    "мск": "msk",
    "казань": "kzn",
    "калининград": "klgd",
    "шушары": "spbs",
    "пушкин": "spbs",
    "петергоф": "spbs",
    "колпино": "spbs",
}

WEEKDAYS = {
    "пн": 0,
    "понедельник": 0,
    "вторник": 1,
    "вт": 1,
    "среда": 2,
    "среду": 2,
    "ср": 2,
    "четверг": 3,
    "чт": 3,
    "пятница": 4,
    "пятницу": 4,
    "пт": 4,
    "суббота": 5,
    "субботу": 5,
    "сб": 5,
    "воскресенье": 6,
    "вс": 6,
}

PART_WORDS = {
    "утром": "day",
    "утро": "day",
    "днем": "day",
    "дневной": "day",
    "дневные": "day",
    "вечером": "evening",
    "вечер": "evening",
    "вечерний": "evening",
    "вечерние": "evening",
}

_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")

# Служебные слова запроса. «игра» не входит: иначе пропадёт «игра престолов».
FILLER = {
    "на",
    "в",
    "во",
    "по",
    "квиз",
    "квизы",
    "квиза",
    "игры",
    "какие",
    "какой",
    "какое",
    "какая",
    "что",
    "чем",
    "это",
    "есть",
    "будет",
    "будут",
    "расписание",
    "афиша",
    "покажи",
    "показать",
    "найти",
    "найди",
    "хочу",
    "можно",
    "где",
    "когда",
    "все",
    "ближайшие",
    "ближайший",
    "мне",
    "нам",
    "пожалуйста",
    "список",
    "сегодняшние",
    "завтрашние",
}


@dataclass
class SearchQuery:
    tokens: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    part: str | None = None
    city_code: str | None = None
    relaxed: bool = False

    @property
    def is_open(self) -> bool:
        return not self.tokens and self.date_from is None and self.part is None and self.city_code is None


def parse_search(text: str, today: date | None = None) -> SearchQuery:
    today = today or date.today()
    raw = text.lower().replace("ё", "е")
    query = SearchQuery()

    if re.search(r"\bпослезавтра\b", raw):
        day = today + timedelta(days=2)
        query.date_from = query.date_to = day
        raw = re.sub(r"\bпослезавтра\b", " ", raw)
    elif re.search(r"\bзавтра\b", raw):
        day = today + timedelta(days=1)
        query.date_from = query.date_to = day
        raw = re.sub(r"\bзавтра\b", " ", raw)
    elif re.search(r"\bсегодня\b", raw):
        query.date_from = query.date_to = today
        raw = re.sub(r"\bсегодня\b", " ", raw)

    dated = _DATE.search(raw)
    if dated and query.date_from is None:
        day_n = int(dated.group(1))
        month_n = int(dated.group(2))
        year_raw = dated.group(3)
        year = today.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            picked = date(year, month_n, day_n)
        except ValueError:
            picked = None
        if picked is not None:
            if not year_raw and picked < today - timedelta(days=1):
                try:
                    picked = date(year + 1, month_n, day_n)
                except ValueError:
                    picked = None
        if picked is not None:
            query.date_from = query.date_to = picked
            raw = raw[: dated.start()] + " " + raw[dated.end() :]

    tokens = normalize(raw).split()
    kept: list[str] = []
    weekend = False
    weekday: int | None = None

    for index, token in enumerate(tokens):
        if token == "день":
            if index + 1 < len(tokens) and tokens[index + 1].startswith("рожден"):
                kept.append(token)
                continue
            if query.part is None:
                query.part = "day"
            continue
        if token in {"выходные", "выходных"}:
            weekend = True
            continue
        if token in CITY_ALIASES:
            query.city_code = CITY_ALIASES[token]
            continue
        if token in WEEKDAYS and weekday is None and query.date_from is None:
            weekday = WEEKDAYS[token]
            continue
        if token in PART_WORDS and query.part is None:
            query.part = PART_WORDS[token]
            continue
        if token in FILLER:
            continue
        kept.append(token)

    if weekend and query.date_from is None:
        query.date_from, query.date_to = _weekend_span(today)
    elif weekday is not None and query.date_from is None:
        delta = (weekday - today.weekday()) % 7
        query.date_from = query.date_to = today + timedelta(days=delta)

    query.tokens = kept
    return query


def _weekend_span(today: date) -> tuple[date, date]:
    if today.weekday() == 5:
        return today, today + timedelta(days=1)
    if today.weekday() == 6:
        return today, today
    saturday = today + timedelta(days=(5 - today.weekday()))
    return saturday, saturday + timedelta(days=1)


def quiz_blob(quiz: dict) -> str:
    tags = quiz.get("tags") or ""
    return normalize(
        " ".join(
            [
                str(quiz.get("title") or ""),
                str(quiz.get("organizer") or ""),
                str(quiz.get("place") or ""),
                str(quiz.get("description") or ""),
                str(tags),
            ]
        )
    )


def token_matches(token: str, blob: str) -> bool:
    if token == "ким":
        return "ким" in blob or ("кино" in blob and "музыка" in blob)
    options = {
        "гп": ("гарри поттер", "гаррипоттер"),
        "поттер": ("поттер",),
        "киномузыка": ("ким",),
    }.get(token, (token,))
    return any(option in blob for option in options)


def matches(quiz: dict, query: SearchQuery) -> bool:
    if query.city_code and quiz.get("city_code") != query.city_code:
        return False
    starts = datetime.strptime(quiz["starts_at"], "%Y-%m-%d %H:%M")
    if query.date_from and starts.date() < query.date_from:
        return False
    if query.date_to and starts.date() > query.date_to:
        return False
    if query.part == "day" and starts.hour >= EVENING_HOUR:
        return False
    if query.part == "evening" and starts.hour < EVENING_HOUR:
        return False
    blob = quiz_blob(quiz)
    return all(token_matches(token, blob) for token in query.tokens)
