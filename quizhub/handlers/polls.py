from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, Poll, PollAnswer, ReplyParameters

from quizhub.db import Database
from quizhub.format import esc
from quizhub.polls import (
    OPTIONS,
    format_week,
    notice_from_question,
    parse_notice_start,
    parse_notices,
    poll_question,
)
from quizhub.timeutil import today_msk, week_bounds

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
async def cmd_poll(message: Message, db: Database) -> None:
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
    await _publish(message, notices, db)


@router.message(Command("week"))
async def cmd_week(message: Message, db: Database) -> None:
    await db.delete_expired_polls(today_msk())
    start, end = week_bounds(today_msk())
    rows = await db.week_polls(message.chat.id, start, end)
    await message.answer(format_week(rows, start, end))


@router.message(Command("add"))
async def cmd_add(message: Message, db: Database) -> None:
    await db.delete_expired_polls(today_msk())
    poll = _selected_poll(message)
    if poll is None:
        await message.answer(
            "Ответьте командой /add на опрос, который нужно добавить в список недели."
        )
        return
    today = today_msk()
    notice = notice_from_question(poll.question, today)
    starts = parse_notice_start(notice.when, today)
    if starts is not None and starts.date() < today:
        await message.answer(
            "Этот квиз уже прошёл. На следующий день после проведения запись удаляется, "
            "поэтому в список его не добавляю."
        )
        return
    going_option_id, going_count = _going_choice(poll)
    existed = await db.poll_quiz(poll.id)
    if existed is None:
        await db.save_poll_quiz(
            poll_id=poll.id,
            chat_id=message.chat.id,
            organizer=notice.organizer,
            title=notice.title or notice.organizer or "Квиз",
            place=notice.place,
            starts_at=starts.strftime("%Y-%m-%d %H:%M") if starts else None,
            when_text=notice.when,
            going_option_id=going_option_id,
            going_snapshot=going_count,
        )
    else:
        await db.set_poll_snapshot(poll.id, going_option_id or existed["going_option_id"], going_count)
    await db.save_poll_options(poll.id, _poll_option_rows(poll), replace_counts=True)
    await message.answer(
        _added_text(await db.poll_quiz(poll.id), existed is not None, await db.shown_going(poll.id))
    )


@router.poll_answer()
async def on_poll_answer(answer: PollAnswer, db: Database) -> None:
    user = answer.user
    if user is None:
        return
    going_option_id = await db.poll_going_option(answer.poll_id)
    if going_option_id is None:
        return
    previous_going = await db.poll_vote_going(answer.poll_id, user.id)
    previous_options = await db.poll_vote_options(answer.poll_id, user.id)
    chosen = [option_id for option_id in (answer.option_persistent_ids or []) if option_id]
    going = bool(going_option_id) and going_option_id in chosen
    await db.save_poll_vote(
        poll_id=answer.poll_id,
        telegram_id=user.id,
        going=going,
        name=user.full_name,
        username=user.username,
        option_ids=chosen,
    )
    await db.apply_option_vote(answer.poll_id, previous_options, chosen)
    await db.adjust_going_snapshot(answer.poll_id, previous_going, going)


@router.poll()
async def on_poll(poll: Poll, db: Database) -> None:
    if await db.poll_quiz(poll.id) is None:
        return
    await db.save_poll_options(poll.id, _poll_option_rows(poll), replace_counts=False)


@router.message(F.forward_origin)
async def forwarded_notice(message: Message, db: Database) -> None:
    notices = parse_notices(_message_text(message))
    if not notices:
        raise SkipHandler()
    await _publish(message, notices, db, reply_to=message)


async def _publish(
    message: Message,
    notices: list,
    db: Database,
    *,
    reply_to: Message | None = None,
) -> None:
    origin = reply_to if reply_to is not None else message.reply_to_message
    reply = (
        ReplyParameters(message_id=origin.message_id, allow_sending_without_reply=True)
        if origin is not None
        else None
    )
    count = 0
    for notice in notices[:_MAX_POLLS]:
        if count > 0:
            reply = None
        sent, error = await _send_poll(message, poll_question(notice), reply=reply)
        if sent is not None and sent.poll is not None:
            await _remember_poll(db, message.chat.id, notice, sent.poll)
        if error is not None:
            if count == 0:
                await message.answer(error)
            return
        count += 1
    if len(notices) > _MAX_POLLS:
        await message.answer(f"Дальше в сообщении ещё {len(notices) - _MAX_POLLS}. Пришлите их отдельно.")


async def _remember_poll(db: Database, chat_id: int, notice, poll) -> None:
    going_option_id = ""
    for option in poll.options:
        if option.text == OPTIONS[0]:
            going_option_id = option.persistent_id
            break
    starts = parse_notice_start(notice.when, today_msk())
    await db.save_poll_quiz(
        poll_id=poll.id,
        chat_id=chat_id,
        organizer=notice.organizer,
        title=notice.title or notice.organizer or "Квиз",
        place=notice.place,
        starts_at=starts.strftime("%Y-%m-%d %H:%M") if starts else None,
        when_text=notice.when,
        going_option_id=going_option_id,
    )
    await db.save_poll_options(poll.id, _poll_option_rows(poll), replace_counts=True)


async def _send_poll(message: Message, question: str, *, reply: ReplyParameters | None) -> tuple[Message | None, str | None]:
    """Открытый опрос: голоса видны, участники могут добавить свой вариант."""
    replies = [reply] if reply is not None else [None]
    if reply is not None:
        replies.append(None)
    last_error = ""
    for poll_reply in replies:
        try:
            sent = await message.answer_poll(
                question,
                list(OPTIONS),
                is_anonymous=False,
                allows_multiple_answers=False,
                allow_adding_options=True,
                question_parse_mode=None,
                reply_parameters=poll_reply,
            )
            return sent, None
        except TelegramBadRequest as error:
            last_error = str(error)
    return None, _poll_error_text(last_error)


def _selected_poll(message: Message):
    origin = message.reply_to_message
    if origin is not None and origin.poll is not None:
        return origin.poll
    return message.poll


def _poll_option_rows(poll) -> list[tuple[str, str, int]]:
    return [
        (option.persistent_id, option.text, int(option.voter_count or 0))
        for option in poll.options
        if option.persistent_id
    ]


def _going_choice(poll) -> tuple[str, int]:
    chosen = None
    for option in poll.options:
        if option.text.strip().casefold() == OPTIONS[0].casefold():
            chosen = option
            break
    if chosen is None and poll.options:
        chosen = poll.options[0]
    if chosen is None:
        return "", 0
    return chosen.persistent_id, int(chosen.voter_count or 0)


def _added_text(row: dict | None, existed: bool, going: int) -> str:
    if row is None:
        return "Не удалось добавить опрос."
    head = (
        "Этот опрос уже был в списке. Обновил, сколько человек ответили «Иду»."
        if existed
        else "Опрос добавлен в список недели."
    )
    lines = [head]
    moment_text = row.get("starts_at") or ""
    if len(moment_text) < 16:
        lines.append("В тексте опроса нет даты, поэтому в /week он не попадёт.")
    else:
        label = f"{moment_text[8:10]}.{moment_text[5:7]}"
        if re.search(r"\d{1,2}:\d{2}", row.get("when_text") or ""):
            label += f" · {moment_text[11:16]}"
        lines.append(f"<b>{esc(label)}</b>")
    title = row.get("title") or ""
    if title:
        lines.append(esc(title))
    where = " · ".join(part for part in (row.get("organizer") or "", row.get("place") or "") if part)
    if where and where != title:
        lines.append(esc(where))
    lines.append(f"Идут: {going}")
    if len(moment_text) >= 16:
        lines.append("На следующий день после квиза запись удалится из базы.")
    return "\n".join(lines)


def _poll_error_text(detail: str) -> str:
    folded = detail.casefold()
    if "private" in folded or "anonymous" in folded:
        return (
            "Такой опрос можно создать в группе: там видны голоса и можно добавить свой вариант. "
            "Ответьте в группе командой /poll на объявление о квизе."
        )
    return "Не удалось создать опрос. Проверьте, что бот может писать в этот чат."
