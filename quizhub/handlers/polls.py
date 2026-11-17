from __future__ import annotations

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, ReplyParameters

from quizhub.polls import OPTIONS, parse_notices, poll_question

router = Router()

_MAX_POLLS = 10


def _message_text(message: Message | None) -> str:
    if message is None:
        return ""
    return message.text or message.caption or ""


def _announcement_text(message: Message) -> str:
    """Берёт текст объявления из ответа, цитаты или хвоста команды.

    У пересланного сообщения полный текст иногда есть только в цитате ответа.
    """
    candidates = [
        _message_text(message.reply_to_message),
        message.quote.text if message.quote is not None else "",
    ]
    body = _message_text(message)
    parts = body.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].casefold() if parts else ""
    if command == "/poll":
        if len(parts) > 1:
            candidates.append(parts[1])
    elif body:
        candidates.append(body)
    best = ""
    best_count = -1
    for candidate in candidates:
        if not candidate.strip():
            continue
        count = len(parse_notices(candidate))
        if count > best_count or (count == best_count and len(candidate) > len(best)):
            best = candidate
            best_count = count
    return best


@router.message(Command("poll"))
async def cmd_poll(message: Message) -> None:
    text = _announcement_text(message)
    notices = parse_notices(text) if text.strip() else []
    if not notices:
        if message.reply_to_message is not None or message.quote is not None:
            await message.answer(
                "Не вижу текст этого сообщения. Ответьте командой /poll прямо в группе "
                "или вставьте объявление сразу после команды."
            )
            return
        await message.answer(
            "В группе ответьте командой /poll на объявление о квизе. "
            "Голоса будут видны, участники смогут добавить свой вариант."
        )
        return
    await _publish(message, notices)


@router.message(F.forward_origin)
async def forwarded_notice(message: Message) -> None:
    notices = parse_notices(_message_text(message))
    if not notices:
        raise SkipHandler()
    await _publish(message, notices, reply_to=message)


async def _publish(message: Message, notices: list, *, reply_to: Message | None = None) -> None:
    origin = reply_to if reply_to is not None else message.reply_to_message
    reply = (
        ReplyParameters(message_id=origin.message_id, allow_sending_without_reply=True)
        if origin is not None
        else None
    )
    sent = 0
    for notice in notices[:_MAX_POLLS]:
        if sent > 0:
            reply = None
        error = await _send_poll(message, poll_question(notice), reply=reply)
        if error is not None:
            if sent == 0:
                await message.answer(error)
            return
        sent += 1
    if len(notices) > _MAX_POLLS:
        await message.answer(f"Дальше в сообщении ещё {len(notices) - _MAX_POLLS}. Пришлите их отдельно.")


async def _send_poll(message: Message, question: str, *, reply: ReplyParameters | None) -> str | None:
    """Открытый опрос: голоса видны, участники могут добавить свой вариант."""
    replies = [reply] if reply is not None else [None]
    if reply is not None:
        replies.append(None)
    last_error = ""
    for poll_reply in replies:
        try:
            await message.answer_poll(
                question,
                list(OPTIONS),
                is_anonymous=False,
                allows_multiple_answers=False,
                allow_adding_options=True,
                question_parse_mode=None,
                reply_parameters=poll_reply,
            )
            return None
        except TelegramBadRequest as error:
            last_error = str(error)
    return _poll_error_text(last_error)


def _poll_error_text(detail: str) -> str:
    folded = detail.casefold()
    if "private" in folded or "anonymous" in folded:
        return (
            "Такой опрос можно создать в группе: там видны голоса и можно добавить свой вариант. "
            "Ответьте в группе командой /poll на объявление о квизе."
        )
    return "Не удалось создать опрос. Проверьте, что бот может писать в этот чат."
