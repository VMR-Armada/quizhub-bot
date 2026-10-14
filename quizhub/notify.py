from __future__ import annotations

import logging

from aiogram import Bot

from quizhub.db import Database
from quizhub.format import esc, format_quiz_card, status_icon
from quizhub.search import matches, parse_search
from quizhub.timeutil import today_msk

log = logging.getLogger(__name__)


async def notify_new_quiz(bot: Bot, db: Database, quiz_id: int) -> None:
    quiz = await db.get_quiz(quiz_id)
    if quiz is None:
        return
    city_name = await db.city_name(quiz["city_code"]) or quiz["city_code"]
    posts = await db.team_posts(quiz_id)
    card = format_quiz_card(quiz, city_name, posts)
    for sub in await db.subscriptions_for_city(quiz["city_code"]):
        parsed = parse_search(sub["query"], today_msk())
        parsed.date_from = None
        parsed.date_to = None
        parsed.city_code = None
        if not matches(quiz, parsed):
            continue
        if await db.already_sent(sub["id"], quiz_id):
            continue
        text = f"Новый квиз по подписке «{esc(sub['query'])}»\n\n{card}"
        try:
            await bot.send_message(sub["telegram_id"], text[:4000])
            await db.mark_sent(sub["id"], quiz_id)
        except Exception:
            log.exception("Не удалось отправить подписку %s", sub["id"])
