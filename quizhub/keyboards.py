from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from quizhub.format import status_icon


def cities_keyboard(cities: list[dict], prefix: str = "city") -> InlineKeyboardMarkup:
    rows = []
    for city in cities:
        rows.append(
            [InlineKeyboardButton(text=city["name"], callback_data=f"{prefix}:{city['code']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="quick:сегодня"),
                InlineKeyboardButton(text="Завтра", callback_data="quick:завтра"),
            ],
            [
                InlineKeyboardButton(text="Вечером", callback_data="quick:завтра вечером"),
                InlineKeyboardButton(text="Выходные", callback_data="quick:выходные"),
            ],
            [
                InlineKeyboardButton(text="Сменить город", callback_data="pickcity"),
                InlineKeyboardButton(text="Подписки", callback_data="subs"),
            ],
        ]
    )


def results_keyboard(page_ids: list[int], page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    number_row = [
        InlineKeyboardButton(text=str(index + 1), callback_data=f"quiz:{quiz_id}")
        for index, quiz_id in enumerate(page_ids)
    ]
    rows = [number_row] if number_row else []
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"page:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Дальше →", callback_data=f"page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="Найти команду или игрока", callback_data="findmenu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_keyboard(quiz: dict) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Ищу игрока", callback_data=f"want:player:{quiz['id']}"),
            InlineKeyboardButton(text="Ищу команду", callback_data=f"want:team:{quiz['id']}"),
        ]
    ]
    if quiz.get("url"):
        rows.append([InlineKeyboardButton(text="Регистрация", url=quiz["url"])])
    tags = [tag.strip() for tag in (quiz.get("tags") or "").split(",") if tag.strip()]
    if tags:
        payload = f"subadd:{tags[0]}"
        if len(payload.encode("utf-8")) <= 64:
            rows.append([InlineKeyboardButton(text=f"Подписка: {tags[0]}", callback_data=payload)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscriptions_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"✕ {item['query']} · {item['city_name']}", callback_data=f"unsub:{item['id']}")]
        for item in items
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Пока пусто", callback_data="noop")]])


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{status_icon('open')} Есть места", callback_data="status:open"),
                InlineKeyboardButton(text=f"{status_icon('few')} Мало мест", callback_data="status:few"),
            ],
            [
                InlineKeyboardButton(text=f"{status_icon('full')} Мест нет", callback_data="status:full"),
                InlineKeyboardButton(text=f"{status_icon('announce')} Анонс", callback_data="status:announce"),
            ],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сохранить", callback_data="quizsave"),
                InlineKeyboardButton(text="Отмена", callback_data="quizdrop"),
            ]
        ]
    )


def skip_keyboard(data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data=data)]]
    )
