from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from quizhub.db import Database
from quizhub.listing import collect
from quizhub.search import matches, parse_search
from quizhub.seed import build_demo, seed_if_empty
from quizhub.timeutil import today_msk
from quizhub.web import create_web_app

TODAY = date(2026, 10, 14)  # среда


class DotenvTests(unittest.TestCase):
    def test_utf16_env_file(self) -> None:
        from quizhub.config import _load_dotenv

        key = "QUIZHUB_DOTENV_TEST"
        os.environ.pop(key, None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{key}=ok\n", encoding="utf-16")
            _load_dotenv(path)
        self.assertEqual(os.environ.get(key), "ok")
        os.environ.pop(key, None)


class SearchTests(unittest.TestCase):
    def test_tomorrow_evening_music(self) -> None:
        parsed = parse_search("завтра вечером музыка", TODAY)
        self.assertEqual(parsed.date_from, date(2026, 10, 15))
        self.assertEqual(parsed.part, "evening")
        self.assertEqual(parsed.tokens, ["музыка"])

    def test_birthday_is_not_a_day_filter(self) -> None:
        parsed = parse_search("день рождения", TODAY)
        self.assertIsNone(parsed.part)
        self.assertEqual(parsed.tokens, ["день", "рождения"])

    def test_kim_means_cinema_and_music(self) -> None:
        parsed = parse_search("ким", TODAY)
        rows = [row for row in build_demo(TODAY, 21) if matches(row, parsed)]
        self.assertTrue(rows)
        self.assertTrue(all("кино" in row["title"].lower() and "музыка" in row["title"].lower() for row in rows))

    def test_saturday_daytime_excludes_evening(self) -> None:
        parsed = parse_search("суббота день", TODAY)
        self.assertEqual(parsed.date_from, date(2026, 10, 17))
        self.assertEqual(parsed.part, "day")
        rows = [row for row in build_demo(TODAY, 21) if matches(row, parsed)]
        self.assertTrue(rows)
        self.assertTrue(all(int(row["starts_at"][11:13]) < 18 for row in rows))

    def test_city_in_query(self) -> None:
        parsed = parse_search("москва завтра рок", TODAY)
        self.assertEqual(parsed.city_code, "msk")
        self.assertEqual(parsed.tokens, ["рок"])
        self.assertNotIn("квиз", parsed.tokens)

    def test_game_of_thrones_phrase(self) -> None:
        parsed = parse_search("игра престолов", TODAY)
        self.assertEqual(parsed.tokens, ["игра", "престолов"])
        rows = [row for row in build_demo(TODAY, 21) if matches(row, parsed)]
        self.assertTrue(rows)
        self.assertTrue(all("престолов" in row["title"].lower() for row in rows))

    def test_weekend_and_date(self) -> None:
        parsed = parse_search("выходные", TODAY)
        self.assertEqual(parsed.date_from, date(2026, 10, 17))
        self.assertEqual(parsed.date_to, date(2026, 10, 18))

    def test_every_city_has_a_quiz_each_weekday(self) -> None:
        rows = build_demo(TODAY, 7)
        for city in ("spb", "msk", "kzn", "klgd", "spbs"):
            covered = {date.fromisoformat(row["starts_at"][:10]).weekday() for row in rows if row["city_code"] == city}
            self.assertEqual(covered, set(range(7)), city)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "quiz.db"))
        await self.db.init()
        added = await seed_if_empty(self.db)
        self.assertGreater(added, 0)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_today_search_in_spb(self) -> None:
        today = today_msk()
        parsed, city, found = await collect(self.db, "сегодня", "spb", today)
        self.assertEqual(city, "spb")
        self.assertEqual(parsed.date_from, today)
        self.assertTrue(found)
        self.assertTrue(all(row["starts_at"].startswith(today.isoformat()) for row in found))

    async def test_team_post_and_personal_filter(self) -> None:
        _, _, found = await collect(self.db, "сегодня", "spb", TODAY)
        quiz_id = found[0]["id"]
        await self.db.add_team_post(
            quiz_id=quiz_id,
            telegram_id=7,
            kind="player",
            name="Анна",
            note="играем вчетвером",
            username="anna",
        )
        posts = await self.db.team_posts(quiz_id)
        self.assertEqual(posts[0]["name"], "Анна")
        await self.db.ensure_user(7, "anna", "Анна")
        await self.db.set_city(7, "spb")
        token = await self.db.get_or_create_table_link(7, "spb")
        await self.db.save_table_filter(token, "whitelist", ["Северный квиз"])
        link = await self.db.table_link(token)
        self.assertEqual(link["filter_mode"], "whitelist")
        self.assertEqual(link["organizers"], ["Северный квиз"])

    async def test_personal_table_filter(self) -> None:
        await self.db.ensure_user(7, None, "Анна")
        token = await self.db.get_or_create_table_link(7, "spb")
        app = create_web_app(self.db)
        async with TestClient(TestServer(app)) as client:
            page = await client.get(f"/t/{token}")
            self.assertEqual(page.status, 200)
            self.assertIn("Северный квиз", await page.text())
            saved = await client.post(
                f"/t/{token}/filter",
                data={"mode": "whitelist", "organizer": "Северный квиз"},
                allow_redirects=False,
            )
            self.assertEqual(saved.status, 302)
        link = await self.db.table_link(token)
        self.assertEqual(link["filter_mode"], "whitelist")
        self.assertEqual(link["organizers"], ["Северный квиз"])

    async def test_dashboard_renders(self) -> None:
        app = create_web_app(self.db)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/dashboard/spb")
            text = await response.text()
            self.assertEqual(response.status, 200)
            self.assertIn("Северный квиз", text)
            missing = await client.get("/dashboard/nope")
            self.assertEqual(missing.status, 404)

    async def test_seed_is_not_duplicated(self) -> None:
        again = await seed_if_empty(self.db)
        self.assertEqual(again, 0)


if __name__ == "__main__":
    unittest.main()
