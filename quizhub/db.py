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
                """
            )
            await self._ensure_cities(db)

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
            result: dict[int, dict[str, int]] = {}
            for row in await cursor.fetchall():
                bucket = result.setdefault(int(row["quiz_id"]), {"team": 0, "player": 0})
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

    async def chat_schedule(self, chat_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM chat_schedules WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            return None if row is None else dict(row)
