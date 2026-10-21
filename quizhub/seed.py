from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from quizhub.db import Database
from quizhub.tags import merge_tags
from quizhub.timeutil import format_stored, today_msk

STATUSES = ("open", "open", "few", "full", "announce")


@dataclass(frozen=True)
class Slot:
    weekday: int
    hour: int
    organizer: str
    title: str
    place: str
    price: str
    max_team: int
    tags: tuple[str, ...]
    blurb: str
    url: str = ""


def _week(organizer: str, place: str, rows: list[tuple]) -> list[Slot]:
    slots: list[Slot] = []
    for weekday, hour, title, price, tags, blurb, url in rows:
        slots.append(
            Slot(
                weekday=weekday,
                hour=hour,
                organizer=organizer,
                title=title,
                place=place,
                price=price,
                max_team=8,
                tags=tags,
                blurb=blurb,
                url=url,
            )
        )
    return slots


_REGISTER = "https://example.com/register"

SLOTS: dict[str, list[Slot]] = {
    "spb": [
        *_week(
            "Северный квиз",
            "Бар «Лампа», ул. Рубинштейна, 12",
            [
                (0, 20, "Классика", "500 ₽", ("классика",), "Семь туров обо всём понемногу.", _REGISTER),
                (3, 20, "Кино и музыка", "600 ₽", ("кино", "музыка"), "Кадры, саундтреки и цитаты.", _REGISTER),
                (5, 16, "Литературная гостиная", "450 ₽", ("литература",), "Книги, авторы и герои.", ""),
                (5, 20, "Русский рок", "600 ₽", ("рок", "музыка"), "От подвалов до стадионов.", _REGISTER),
            ],
        ),
        *_week(
            "Барная полка",
            "Паб «Якорь», наб. Фонтанки, 50",
            [
                (1, 19, "Новички", "400 ₽", ("новички",), "Короткий квиз, если играете в первый раз.", _REGISTER),
                (4, 20, "Караоке-раунд", "550 ₽", ("караоке", "музыка"), "Узнать песню по куску припева.", ""),
                (6, 18, "Аниме-вечер", "500 ₽", ("аниме",), "Студии, опенинги и герои.", ""),
            ],
        ),
        *_week(
            "Мелодия",
            "Клуб «Север», Лиговский пр., 30",
            [
                (2, 20, "Угадай мелодию", "500 ₽", ("музыка",), "Пятнадцать секунд на трек.", _REGISTER),
                (5, 21, "Хиты 2000-х", "650 ₽", ("музыка",), "Попса и рок нулевых.", ""),
            ],
        ),
        *_week(
            "Книжный раунд",
            "Кафе «Полка», ул. Достоевского, 19",
            [
                (6, 16, "Гарри Поттер", "500 ₽", ("гарри поттер",), "Факультеты, заклинания и второстепенные герои.", _REGISTER),
                (4, 19, "Игра престолов", "550 ₽", ("сериалы",), "Дома, девизы и карта Вестероса.", ""),
            ],
        ),
    ],
    "msk": [
        *_week(
            "Столичный квиз",
            "Бар «Честер», ул. Покровка, 21",
            [
                (0, 20, "Классика", "700 ₽", ("классика",), "Большая городская игра.", _REGISTER),
                (2, 20, "Кино и музыка", "800 ₽", ("кино", "музыка"), "Фильмы и песни вперемешку.", _REGISTER),
                (5, 16, "Новички", "500 ₽", ("новички",), "Дневная игра с простыми вопросами.", ""),
                (5, 20, "Русский рок", "800 ₽", ("рок",), "Квартирники и главные альбомы.", _REGISTER),
            ],
        ),
        *_week(
            "Пабная лига",
            "Паб «Лев», Цветной бульвар, 11",
            [
                (1, 19, "Угадай мелодию", "600 ₽", ("музыка",), "Только припевы.", ""),
                (3, 20, "Караоке-раунд", "700 ₽", ("караоке",), "Текст, исполнитель, год.", _REGISTER),
                (6, 18, "Гарри Поттер", "700 ₽", ("гарри поттер",), "Турнир для тех, кто перечитывал.", ""),
            ],
        ),
        *_week(
            "Читальный зал",
            "Кафе «Обложка», ул. Арбат, 14",
            [
                (4, 19, "Литературный четверг", "650 ₽", ("литература",), "Русская и переводная проза.", ""),
                (6, 15, "Игра престолов", "650 ₽", ("сериалы",), "Книги и сериал, без спойлеров финала.", _REGISTER),
            ],
        ),
    ],
    "kzn": [
        *_week(
            "Казанский раунд",
            "Бар «Кремлёвский», ул. Баумана, 9",
            [
                (0, 19, "Классика", "400 ₽", ("классика",), "Городской набор вопросов.", _REGISTER),
                (3, 20, "Кино и музыка", "450 ₽", ("кино", "музыка"), "Саундтреки и актёры.", ""),
                (5, 20, "Хиты 2010-х", "450 ₽", ("музыка",), "То, что играло из каждой машины.", _REGISTER),
            ],
        ),
        *_week(
            "Волга квиз",
            "Лофт «Волга», ул. Островского, 4",
            [
                (1, 20, "Угадай мелодию", "350 ₽", ("музыка",), "Короткий музыкальный сет.", ""),
                (2, 19, "Новички", "350 ₽", ("новички",), "Можно прийти без своей команды.", ""),
                (4, 20, "Русский рок", "400 ₽", ("рок",), "От «Кино» до новых имён.", ""),
                (6, 16, "Литературный стол", "350 ₽", ("литература",), "Школьная классика и то, что читают сейчас.", ""),
            ],
        ),
    ],
    "klgd": [
        *_week(
            "Балтийский квиз",
            "Бар «Маяк», наб. Петра Великого, 1",
            [
                (0, 19, "Новички", "350 ₽", ("новички",), "Первая игра — с подсказками ведущего.", ""),
                (1, 19, "Классика", "400 ₽", ("классика",), "Вопросы без домашней подготовки.", _REGISTER),
                (2, 20, "Литературный стол", "400 ₽", ("литература",), "Книги, которые обсуждают в баре.", ""),
                (4, 20, "Кино и музыка", "450 ₽", ("кино", "музыка"), "Европейское кино и местные хиты.", ""),
                (5, 18, "Караоке-раунд", "450 ₽", ("караоке",), "Поём тихо, отвечаем громко.", _REGISTER),
            ],
        ),
        *_week(
            "Янтарный вечер",
            "Паб «Янтарь», ул. Театральная, 8",
            [
                (3, 20, "Угадай мелодию", "400 ₽", ("музыка",), "Десять секунд и четыре варианта.", ""),
                (6, 16, "Гарри Поттер", "400 ₽", ("гарри поттер",), "Для тех, кто помнит имена деканов.", ""),
                (6, 20, "Аниме-вечер", "400 ₽", ("аниме",), "Сезон короче, чем список вопросов.", ""),
            ],
        ),
    ],
    "spbs": [
        *_week(
            "Южный квиз",
            "Бар «Шушары», ул. Валдайская, 3",
            [
                (1, 19, "Угадай мелодию", "400 ₽", ("музыка",), "Соседний зал, если не хотите ехать в центр.", ""),
                (2, 19, "Классика", "400 ₽", ("классика",), "Игра ближе к дому, без поездки в центр.", _REGISTER),
                (3, 20, "Караоке-раунд", "400 ₽", ("караоке",), "Можно подпевать шёпотом.", ""),
                (4, 20, "Кино и музыка", "450 ₽", ("кино", "музыка"), "Семейный зал, вопросы 16+.", ""),
                (5, 17, "Новички", "350 ₽", ("новички",), "Дневной заход для новых команд.", _REGISTER),
            ],
        ),
        *_week(
            "Петергофская лига",
            "Кафе «Фонтан», Санкт-Петербургский пр., 40",
            [
                (0, 19, "Литературный понедельник", "400 ₽", ("литература",), "Короткие тексты и длинные споры.", ""),
                (5, 20, "Русский рок", "450 ₽", ("рок",), "Гитары и правильные года альбомов.", ""),
                (6, 18, "Игра престолов", "450 ₽", ("сериалы",), "Кто чей знаменосец.", _REGISTER),
            ],
        ),
    ],
}


def build_demo(start: date | None = None, days: int = 21) -> list[dict]:
    start = start or today_msk()
    items: list[dict] = []
    for city_code, slots in SLOTS.items():
        for offset in range(days):
            day = start + timedelta(days=offset)
            for slot in slots:
                if slot.weekday != day.weekday():
                    continue
                starts = datetime.combine(day, time(slot.hour, 0))
                items.append(
                    {
                        "city_code": city_code,
                        "organizer": slot.organizer,
                        "title": slot.title,
                        "starts_at": format_stored(starts),
                        "place": slot.place,
                        "price": slot.price,
                        "max_team": slot.max_team,
                        "description": slot.blurb,
                        "url": slot.url or None,
                        "status": STATUSES[(offset + slot.hour) % len(STATUSES)],
                        "tags": merge_tags(list(slot.tags), slot.title, slot.blurb),
                    }
                )
    return items


async def delete_demo_quizzes(db: Database) -> int:
    """Убирает учебные игры. Их названия выдуманы и не совпадают с живой афишей."""
    names = sorted({slot.organizer for slots in SLOTS.values() for slot in slots})
    if not names:
        return 0
    placeholders = ",".join("?" for _ in names)
    async with db.connect() as connection:
        cursor = await connection.execute(
            f"DELETE FROM quizzes WHERE organizer IN ({placeholders})",
            names,
        )
        return int(cursor.rowcount or 0)


async def seed_if_empty(db: Database) -> int:
    if await db.count_quizzes():
        return 0
    return await _insert_demo(db, build_demo())


async def ensure_horizon(db: Database, days: int = 21) -> int:
    """Дописывает демо-игры, если впереди почти пусто. Уже прошедшие даты сами не показываются."""
    if await db.count_from(today_msk()) >= 8:
        return 0
    rows = []
    for row in build_demo(today_msk(), days):
        exists = await db.quiz_exists(row["city_code"], row["organizer"], row["title"], row["starts_at"])
        if not exists:
            rows.append(row)
    return await _insert_demo(db, rows)


async def _insert_demo(db: Database, rows: list[dict]) -> int:
    for row in rows:
        await db.add_quiz(**row)
    return len(rows)
