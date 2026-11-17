from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, ReplyParameters

from quizhub.polls import OPTIONS, parse_notices, poll_question

router = Router()

_MAX_POLLS = 10


def _announcement_text(message: Message) -> str:
    origin = message.reply_to_message
    if origin is not None and (origin.text or origin.caption):
        return origin.text or origin.caption or ""
    body = message.text or message.caption or ""
    parts = body.split(maxsplit=1)
    if parts and parts[0].split("@", 1)[0] == "/poll":
        return parts[1] if len(parts) > 1 else ""
    return body


@router.message(Command("poll"))
async def cmd_poll(message: Message) -> None:
    text = _announcement_text(message)
    if not text.strip():
        await message.answer(
            "Ответьте командой /poll на объявление о квизе "
            "или пришлите его текст сразу после команды."
        )
        return
    notices = parse_notices(text)
    if not notices:
        await message.answer(
            "Не разобрал квиз в этом сообщении. "
            "Нужны строки с организатором, названием, датой и местом."
        )
        return
    origin = message.reply_to_message
    reply = ReplyParameters(message_id=origin.message_id) if origin is not None else None
    anonymous = message.chat.type == "private"
    sent = 0
    for notice in notices[:_MAX_POLLS]:
        if sent > 0:
            reply = None
        ok = await _send_poll(message, poll_question(notice), anonymous=anonymous, reply=reply)
        if not ok:
            if sent == 0:
                await message.answer("Не удалось создать опрос. Проверьте, что бот может писать в этот чат.")
            return
        sent += 1
    if len(notices) > _MAX_POLLS:
        await message.answer(f"Дальше в сообщении ещё {len(notices) - _MAX_POLLS}. Пришлите их отдельно.")


async def _send_poll(message: Message, question: str, *, anonymous: bool, reply: ReplyParameters | None) -> bool:
    try:
        await message.answer_poll(
            question,
            list(OPTIONS),
            is_anonymous=anonymous,
            allows_multiple_answers=False,
            reply_parameters=reply,
        )
        return True
    except TelegramBadRequest:
        if anonymous:
            return False
    try:
        await message.answer_poll(
            question,
            list(OPTIONS),
            is_anonymous=True,
            allows_multiple_answers=False,
            reply_parameters=reply,
        )
        return True
    except TelegramBadRequest:
        return False
