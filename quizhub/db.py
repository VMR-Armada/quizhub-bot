from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from quizhub.timeutil import format_stored, shift_days


class Database:
    def __init__(self, path: str):
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute("PRAGMA busy_timeout=5000")
            await connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cities (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    city_code TEXT NOT NULL DEFAULT 'spb',
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quizzes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_code TEXT NOT NULL,
                    organizer TEXT NOT NULL,
                    title TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    place TEXT NOT NULL,
                    price TEXT,
                    max_team INTEGER,
                    description TEXT,
                    url TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    tags TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_quizzes_city_time
                    ON quizzes (city_code, starts_at);

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    city_code TEXT NOT NULL,
                    query TEXT NOT NULL,
                    UNIQUE (telegram_id, city_code, query)
                );

                CREATE TABLE IF NOT EXISTS subscription_sent (
                    subscription_id INTEGER NOT NULL,
                    quiz_id INTEGER NOT NULL,
                    PRIMARY KEY (subscription_id, quiz_id)
                );

                CREATE TABLE IF NOT EXISTS team_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    note TEXT,
                    username TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (quiz_id, telegram_id, kind)
                );

                CREATE TABLE IF NOT EXISTS table_links (
                    token TEXT PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    city_code TEXT NOT NULL,
                    filter_mode TEXT NOT NULL DEFAULT 'blacklist',
                    organizers_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS chat_schedules (
                    chat_id INTEGER PRIMARY KEY,
                    city_code TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    message_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_cache (
                    telegram_id INTEGER PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    city_code TEXT NOT NULL,
                    quiz_ids TEXT NOT NULL,
                    page INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS poll_quizzes (
                    poll_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    organizer TEXT NOT NULL,
                    title TEXT NOT NULL,
                    place TEXT NOT NULL DEFAULT '',
                    starts_at TEXT,
                    when_text TEXT NOT NULL DEFAULT '',
                    going_option_id TEXT NOT NULL DEFAULT '',
                    going_snapshot INTEGER NOT NULL DEFAULT 0,
                    message_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_poll_quizzes_chat_time
                    ON poll_quizzes (chat_id, starts_at);

                CREATE TABLE IF NOT EXISTS poll_votes (
                    poll_id TEXT NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    going INTEGER NOT NULL DEFAULT 0,
                    option_ids TEXT NOT NULL DEFAULT '[]',
                    name TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (poll_id, telegram_id)
                );

                CREATE TABLE IF NOT EXISTS poll_options (
                    poll_id TEXT NOT NULL,
                    option_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    voter_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (poll_id, option_id)
                );
                """
            )
            await self._ensure_cities(db)
            await self._ensure_poll_columns(db)

    async def _ensure_cities(self, db: aiosqlite.Connection) -> None:
        cities = [
            ("spb", "Санкт-Петербург"),
            ("msk", "Москва"),
            ("kzn", "Казань"),
            ("klgd", "Калининград"),
            ("spbs", "СПб — Юг"),
        ]
        await db.executemany(
            "INSERT OR IGNORE INTO cities (code, name) VALUES (?, ?)",
            cities,
        )

    async def _ensure_poll_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(poll_quizzes)")
        names = {row["name"] for row in await cursor.fetchall()}
        if "going_snapshot" not in names:
            await db.execute(
                "ALTER TABLE poll_quizzes ADD COLUMN going_snapshot INTEGER NOT NULL DEFAULT 0"
            )
        cursor = await db.execute("PRAGMA table_info(poll_votes)")
        vote_columns = {row["name"] for row in await cursor.fetchall()}
        if "option_ids" not in vote_columns:
            await db.execute("ALTER TABLE poll_votes ADD COLUMN option_ids TEXT NOT NULL DEFAULT '[]'")
        if "message_id" not in names:
            await db.execute("ALTER TABLE poll_quizzes ADD COLUMN message_id INTEGER")

    async def cities(self) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute("SELECT code, name FROM cities ORDER BY rowid")
            return [dict(row) for row in await cursor.fetchall()]

    async def city_name(self, code: str) -> str | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT name FROM cities WHERE code = ?", (code,))
            row = await cursor.fetchone()
            return None if row is None else str(row["name"])

    async def ensure_user(self, telegram_id: int, username: str | None, first_name: str | None) -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (telegram_id, username, first_name, now),
            )
            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return dict(await cursor.fetchone())

    async def set_city(self, telegram_id: int, city_code: str) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET city_code = ? WHERE telegram_id = ?",
                (city_code, telegram_id),
            )

    async def count_quizzes(self) -> int:
        async with self.connect() as db:
            cursor = await db.execute("SELECT COUNT(*) AS n FROM quizzes")
            row = await cursor.fetchone()
            return int(row["n"])

    async def add_quiz(
        self,
        *,
        city_code: str,
        organizer: str,
        title: str,
        starts_at: str,
        place: str,
        price: str | None,
        max_team: int | None,
        description: str | None,
        url: str | None,
        status: str,
        tags: list[str],
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO quizzes (
                    city_code, organizer, title, starts_at, place, price, max_team,
                    description, url, status, tags, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    city_code,
                    organizer,
                    title,
                    starts_at,
                    place,
                    price,
                    max_team,
                    description,
                    url,
                    status,
                    ", ".join(tags),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    async def count_from(self, start: date) -> int:
        begin, _ = shift_days(start, 1)
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) AS n FROM quizzes WHERE starts_at >= ?",
                (begin,),
            )
            return int((await cursor.fetchone())["n"])

    async def quiz_exists(self, city_code: str, organizer: str, title: str, starts_at: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT 1 FROM quizzes
                WHERE city_code = ? AND organizer = ? AND title = ? AND starts_at = ?
                """,
                (city_code, organizer, title, starts_at),
            )
            return await cursor.fetchone() is not None

    async def quizzes_between(self, city_code: str, start: date, days: int) -> list[dict]:
        begin, end = shift_days(start, days)
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM quizzes
                WHERE city_code = ? AND starts_at >= ? AND starts_at < ?
                ORDER BY starts_at, organizer, title
                """,
                (city_code, begin, end),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get_quizzes(self, quiz_ids: list[int]) -> list[dict]:
        if not quiz_ids:
            return []
        placeholders = ",".join("?" for _ in quiz_ids)
        async with self.connect() as db:
            cursor = await db.execute(
                f"SELECT * FROM quizzes WHERE id IN ({placeholders})",
                quiz_ids,
            )
            by_id = {int(row["id"]): dict(row) for row in await cursor.fetchall()}
        return [by_id[quiz_id] for quiz_id in quiz_ids if quiz_id in by_id]

    async def get_quiz(self, quiz_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
            row = await cursor.fetchone()
            return None if row is None else dict(row)

    async def organizers(self, city_code: str, start: date, days: int) -> list[str]:
        rows = await self.quizzes_between(city_code, start, days)
        return sorted({row["organizer"] for row in rows}, key=lambda name: name.casefold())

    async def save_search(self, telegram_id: int, query_text: str, city_code: str, quiz_ids: list[int]) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO search_cache (telegram_id, query_text, city_code, quiz_ids, page)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    query_text = excluded.query_text,
                    city_code = excluded.city_code,
                    quiz_ids = excluded.quiz_ids,
                    page = 0
                """,
                (telegram_id, query_text, city_code, json.dumps(quiz_ids)),
            )

    async def search_cache(self, telegram_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM search_cache WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            data["quiz_ids"] = json.loads(data["quiz_ids"])
            return data

    async def set_search_page(self, telegram_id: int, page: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE search_cache SET page = ? WHERE telegram_id = ?",
                (page, telegram_id),
            )

    async def add_subscription(self, telegram_id: int, city_code: str, query: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO subscriptions (telegram_id, city_code, query)
                VALUES (?, ?, ?)
                """,
                (telegram_id, city_code, query),
            )
            return cursor.rowcount > 0

    async def subscriptions(self, telegram_id: int) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT s.*, c.name AS city_name
                FROM subscriptions s
                JOIN cities c ON c.code = s.city_code
                WHERE s.telegram_id = ?
                ORDER BY s.id
                """,
                (telegram_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def delete_subscription(self, telegram_id: int, subscription_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "DELETE FROM subscriptions WHERE id = ? AND telegram_id = ?",
                (subscription_id, telegram_id),
            )

    async def subscriptions_for_city(self, city_code: str) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM subscriptions WHERE city_code = ?",
                (city_code,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def already_sent(self, subscription_id: int, quiz_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT 1 FROM subscription_sent
                WHERE subscription_id = ? AND quiz_id = ?
                """,
                (subscription_id, quiz_id),
            )
            return await cursor.fetchone() is not None

    async def mark_sent(self, subscription_id: int, quiz_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "INSERT OR IGNORE INTO subscription_sent (subscription_id, quiz_id) VALUES (?, ?)",
                (subscription_id, quiz_id),
            )

    async def add_team_post(
        self,
        *,
        quiz_id: int,
        telegram_id: int,
        kind: str,
        name: str,
        note: str | None,
        username: str | None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO team_posts (quiz_id, telegram_id, kind, name, note, username, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(quiz_id, telegram_id, kind) DO UPDATE SET
                    name = excluded.name,
                    note = excluded.note,
                    username = excluded.username,
                    created_at = excluded.created_at
                """,
                (quiz_id, telegram_id, kind, name, note, username, now),
            )

    async def team_posts(self, quiz_id: int) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM team_posts WHERE quiz_id = ? ORDER BY created_at",
                (quiz_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def team_counts(self, quiz_ids: list[int]) -> dict[int, dict[str, int]]:
        if not quiz_ids:
            return {}
        placeholders = ",".join("?" for _ in quiz_ids)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT quiz_id, kind, COUNT(*) AS n
                FROM team_posts
                WHERE quiz_id IN ({placeholders})
                GROUP BY quiz_id, kind
                """,
                quiz_ids,
            )
            result: dict[int | str, dict[str, int]] = {}
            for row in await cursor.fetchall():
                key: int | str = row["quiz_id"]
                if not isinstance(key, int):
                    text = str(key)
                    key = int(text) if text.isdigit() else text
                bucket = result.setdefault(key, {"team": 0, "player": 0})
                bucket[str(row["kind"])] = int(row["n"])
            return result

    async def count_team_posts(self, telegram_id: int) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) AS n FROM team_posts WHERE telegram_id = ?",
                (telegram_id,),
            )
            return int((await cursor.fetchone())["n"])

    async def get_or_create_table_link(self, telegram_id: int, city_code: str) -> str:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT token FROM table_links WHERE telegram_id = ? AND city_code = ?",
                (telegram_id, city_code),
            )
            row = await cursor.fetchone()
            if row is not None:
                return str(row["token"])
            import secrets

            token = secrets.token_urlsafe(12)
            await db.execute(
                """
                INSERT INTO table_links (token, telegram_id, city_code)
                VALUES (?, ?, ?)
                """,
                (token, telegram_id, city_code),
            )
            return token

    async def table_link(self, token: str) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM table_links WHERE token = ?", (token,))
            row = await cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            data["organizers"] = json.loads(data["organizers_json"])
            return data

    async def save_table_filter(self, token: str, mode: str, organizers: list[str]) -> None:
        if mode not in {"whitelist", "blacklist"}:
            mode = "blacklist"
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE table_links
                SET filter_mode = ?, organizers_json = ?
                WHERE token = ?
                """,
                (mode, json.dumps(organizers, ensure_ascii=False), token),
            )

    async def save_chat_schedule(self, chat_id: int, city_code: str, owner_id: int, message_id: int | None) -> None:
        now = format_stored(datetime.now())
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO chat_schedules (chat_id, city_code, owner_id, message_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    city_code = excluded.city_code,
                    message_id = COALESCE(excluded.message_id, chat_schedules.message_id)
                """,
                (chat_id, city_code, owner_id, message_id, now),
            )

    async def save_poll_quiz(
        self,
        *,
        poll_id: str,
        chat_id: int,
        organizer: str,
        title: str,
        place: str,
        starts_at: str | None,
        when_text: str,
        going_option_id: str,
        going_snapshot: int = 0,
        message_id: int | None = None,
    ) -> None:
        now = format_stored(datetime.now())
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO poll_quizzes (
                    poll_id, chat_id, organizer, title, place, starts_at,
                    when_text, going_option_id, going_snapshot, message_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(poll_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    organizer = excluded.organizer,
                    title = excluded.title,
                    place = excluded.place,
                    starts_at = excluded.starts_at,
                    when_text = excluded.when_text,
                    going_option_id = excluded.going_option_id,
                    going_snapshot = excluded.going_snapshot,
                    message_id = COALESCE(excluded.message_id, poll_quizzes.message_id)
                """,
                (
                    poll_id,
                    chat_id,
                    organizer,
                    title,
                    place,
                    starts_at,
                    when_text,
                    going_option_id,
                    max(0, going_snapshot),
                    message_id,
                    now,
                ),
            )

    async def poll_quiz_by_message(self, chat_id: int, message_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM poll_quizzes
                WHERE chat_id = ? AND message_id = ?
                """,
                (chat_id, message_id),
            )
            row = await cursor.fetchone()
            return None if row is None else dict(row)

    async def poll_quiz(self, poll_id: str) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM poll_quizzes WHERE poll_id = ?",
                (poll_id,),
            )
            row = await cursor.fetchone()
            return None if row is None else dict(row)

    async def shown_going(self, poll_id: str) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT CASE
                    WHEN q.going_snapshot > 0 THEN q.going_snapshot
                    ELSE (
                        SELECT COUNT(*) FROM poll_votes v
                        WHERE v.poll_id = q.poll_id AND v.going = 1
                    )
                END AS going
                FROM poll_quizzes q
                WHERE q.poll_id = ?
                """,
                (poll_id,),
            )
            row = await cursor.fetchone()
            return 0 if row is None else int(row["going"])

    async def set_poll_snapshot(self, poll_id: str, going_option_id: str, going_snapshot: int) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE poll_quizzes
                SET going_option_id = ?, going_snapshot = ?
                WHERE poll_id = ?
                """,
                (going_option_id, max(0, going_snapshot), poll_id),
            )

    async def poll_vote_going(self, poll_id: str, telegram_id: int) -> bool | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT going FROM poll_votes WHERE poll_id = ? AND telegram_id = ?",
                (poll_id, telegram_id),
            )
            row = await cursor.fetchone()
            return None if row is None else bool(row["going"])

    async def adjust_going_snapshot(self, poll_id: str, previous: bool | None, going: bool) -> None:
        """Двигаёт снимок «Иду», если опрос добавили уже с голосами."""
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT going_snapshot FROM poll_quizzes WHERE poll_id = ?",
                (poll_id,),
            )
            row = await cursor.fetchone()
            if row is None or int(row["going_snapshot"]) <= 0:
                return
            delta = (1 if going else 0) if previous is None else int(going) - int(previous)
            if not delta:
                return
            await db.execute(
                """
                UPDATE poll_quizzes
                SET going_snapshot = MAX(0, going_snapshot + ?)
                WHERE poll_id = ?
                """,
                (delta, poll_id),
            )

    async def delete_expired_polls(self, today: date) -> int:
        """Удаляет квиз на следующий день после даты проведения."""
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT poll_id FROM poll_quizzes
                WHERE starts_at IS NOT NULL AND substr(starts_at, 1, 10) < ?
                """,
                (today.isoformat(),),
            )
            ids = [str(row["poll_id"]) for row in await cursor.fetchall()]
            if not ids:
                return 0
            marks = ",".join("?" * len(ids))
            await db.execute(f"DELETE FROM poll_votes WHERE poll_id IN ({marks})", ids)
            await db.execute(f"DELETE FROM poll_options WHERE poll_id IN ({marks})", ids)
            await db.execute(f"DELETE FROM poll_quizzes WHERE poll_id IN ({marks})", ids)
            return len(ids)

    async def poll_going_option(self, poll_id: str) -> str | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT going_option_id FROM poll_quizzes WHERE poll_id = ?",
                (poll_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return str(row["going_option_id"])

    async def save_poll_options(
        self,
        poll_id: str,
        options: list[tuple[str, str, int]],
        *,
        replace_counts: bool,
    ) -> None:
        async with self.connect() as db:
            for position, (option_id, text, voter_count) in enumerate(options):
                if not option_id:
                    continue
                if replace_counts:
                    await db.execute(
                        """
                        INSERT INTO poll_options (poll_id, option_id, text, position, voter_count)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(poll_id, option_id) DO UPDATE SET
                            text = excluded.text,
                            position = excluded.position,
                            voter_count = excluded.voter_count
                        """,
                        (poll_id, option_id, text, position, max(0, voter_count)),
                    )
                else:
                    await db.execute(
                        """
                        INSERT INTO poll_options (poll_id, option_id, text, position, voter_count)
                        VALUES (?, ?, ?, ?, 0)
                        ON CONFLICT(poll_id, option_id) DO UPDATE SET
                            text = excluded.text,
                            position = excluded.position
                        """,
                        (poll_id, option_id, text, position),
                    )
            if not replace_counts:
                return
            ids = [option_id for option_id, _, _ in options if option_id]
            if not ids:
                return
            marks = ",".join("?" * len(ids))
            await db.execute(
                f"DELETE FROM poll_options WHERE poll_id = ? AND option_id NOT IN ({marks})",
                (poll_id, *ids),
            )

    async def poll_vote_options(self, poll_id: str, telegram_id: int) -> list[str] | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT option_ids FROM poll_votes WHERE poll_id = ? AND telegram_id = ?",
                (poll_id, telegram_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            try:
                chosen = json.loads(row["option_ids"] or "[]")
            except json.JSONDecodeError:
                return []
            return [str(item) for item in chosen] if isinstance(chosen, list) else []

    async def apply_option_vote(self, poll_id: str, previous: list[str] | None, chosen: list[str]) -> None:
        old = previous or []
        removed = [option_id for option_id in old if option_id not in chosen]
        added = [option_id for option_id in chosen if option_id not in old]
        if not removed and not added:
            return
        async with self.connect() as db:
            for option_id in added:
                await db.execute(
                    """
                    INSERT INTO poll_options (poll_id, option_id, text, position, voter_count)
                    VALUES (?, ?, 'Свой вариант', 1000, 0)
                    ON CONFLICT(poll_id, option_id) DO NOTHING
                    """,
                    (poll_id, option_id),
                )
                await db.execute(
                    """
                    UPDATE poll_options
                    SET voter_count = voter_count + 1
                    WHERE poll_id = ? AND option_id = ?
                    """,
                    (poll_id, option_id),
                )
            for option_id in removed:
                await db.execute(
                    """
                    UPDATE poll_options
                    SET voter_count = MAX(0, voter_count - 1)
                    WHERE poll_id = ? AND option_id = ?
                    """,
                    (poll_id, option_id),
                )

    async def save_poll_vote(
        self,
        *,
        poll_id: str,
        telegram_id: int,
        going: bool,
        name: str,
        username: str | None,
        option_ids: list[str] | None = None,
    ) -> None:
        now = format_stored(datetime.now())
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO poll_votes (
                    poll_id, telegram_id, going, option_ids, name, username, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(poll_id, telegram_id) DO UPDATE SET
                    going = excluded.going,
                    option_ids = excluded.option_ids,
                    name = excluded.name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (
                    poll_id,
                    telegram_id,
                    1 if going else 0,
                    json.dumps(option_ids or []),
                    name,
                    username,
                    now,
                ),
            )

    async def week_polls(self, chat_id: int, start: date, end: date) -> list[dict]:
        begin = format_stored(datetime.combine(start, datetime.min.time()))
        until = format_stored(datetime.combine(end, datetime.min.time()))
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT q.poll_id, q.organizer, q.title, q.place, q.starts_at, q.when_text,
                    CASE
                        WHEN q.going_snapshot > 0 THEN q.going_snapshot
                        ELSE (
                            SELECT COUNT(*) FROM poll_votes v
                            WHERE v.poll_id = q.poll_id AND v.going = 1
                        )
                    END AS going
                FROM poll_quizzes q
                WHERE q.chat_id = ? AND q.starts_at >= ? AND q.starts_at < ?
                ORDER BY q.starts_at, q.organizer, q.title
                """,
                (chat_id, begin, until),
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            await self._attach_option_results(db, rows)
            return rows

    async def _attach_option_results(self, db: aiosqlite.Connection, rows: list[dict]) -> None:
        if not rows:
            return
        ids = [row["poll_id"] for row in rows]
        marks = ",".join("?" * len(ids))
        cursor = await db.execute(
            f"""
            SELECT poll_id, text, voter_count
            FROM poll_options
            WHERE poll_id IN ({marks})
            ORDER BY position, text
            """,
            ids,
        )
        grouped: dict[str, list[dict]] = {}
        for option in await cursor.fetchall():
            grouped.setdefault(str(option["poll_id"]), []).append(
                {"text": option["text"], "count": int(option["voter_count"])}
            )
        for row in rows:
            row["options"] = grouped.get(str(row["poll_id"]), [])

    async def chat_schedule(self, chat_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM chat_schedules WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            return None if row is None else dict(row)
