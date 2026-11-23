from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from quizhub.db import Database
from quizhub.listing import collect
from quizhub.live import ScheduleUnavailable, quizzes_from_payload
from quizhub.polls import format_week, notice_from_question, parse_notice_start, parse_notices, poll_question
from quizhub.search import matches, parse_search
from quizhub.seed import build_demo, seed_if_empty
from quizhub.timeutil import today_msk, week_bounds
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
    def test_plain_question_means_the_whole_day(self) -> None:
        parsed = parse_search("какие квизы сегодня", TODAY)
        self.assertEqual(parsed.date_from, TODAY)
        self.assertEqual(parsed.tokens, [])

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

    def test_public_schedule_keeps_wall_clock(self) -> None:
        rows = quizzes_from_payload(
            {
                "success": True,
                "data": {
                    "table": {
                        "БелкинКвиз": {
                            "2026-10-21": {
                                "eveningQuizzes": [
                                    {
                                        "ID": "bjpnh",
                                        "Название": "№3.4 (33)",
                                        "Дата": "2026-10-21T19:30:00.000Z",
                                        "Место": "Фасоль",
                                        "Организатор": "БелкинКвиз",
                                        "Стоимость": 600,
                                        "Максимум в команде": 10,
                                        "Ссылка": "https://vk.com/belkinquizspb",
                                        "Теги": ["кино", "музыка"],
                                        "Внешний статус": "🟢",
                                    }
                                ]
                            }
                        }
                    }
                },
            },
            "spb",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "bjpnh")
        self.assertEqual(rows[0]["starts_at"], "2026-10-21 19:30")
        self.assertEqual(rows[0]["price"], "600 ₽")
        self.assertEqual(rows[0]["tags"], "кино, музыка")
        self.assertNotEqual(rows[0]["organizer"], "Мелодия")


SAMPLE = """Появились новые квизы по вашим подпискам:

👥 Квиз, плиз! (https://spb.quizplease.ru/game/01a1e361-6a9a-71a8-9a36-90319557081d)
🟢 [видеоигры] SPB #14
🗓 (https://www.google.com/calendar/render?action=TEMPLATE&text=%D0%9A%D0%B2%D0%B8%D0%B7%2C%20%D0%BF%D0%BB%D0%B8%D0%B7!&dates=20261128T163000Z/20261128T183000Z&location=%D0%A0%D0%B5%D1%81%D1%82%D0%BE%D0%BA%D0%BB%D1%83%D0%B1%20%D0%A1%D0%BE%D1%83%D1%81&details=%5B%D0%B2%D0%B8%D0%B4%D0%B5%D0%BE%D0%B8%D0%B3%D1%80%D1%8B%5D%20SPB%20%2314) Сб, 28 ноя. 19:30 💰700
🍻 Соус (https://yandex.ru/maps/org/restoklub_sous/237967929499/?ll=30.177145%2C59.876791&z=11)

👥 Шейкер квиз
🟢 #ОБО ВСЁМ
🗓 Вс, 29 ноя. 19:30 💰500
🍻 Puberty
"""


class PollTests(unittest.TestCase):
    def test_notice_becomes_readiness_question(self) -> None:
        notices = parse_notices(SAMPLE)
        self.assertEqual(len(notices), 2)
        first = notices[0]
        self.assertEqual(first.organizer, "Квиз, плиз!")
        self.assertEqual(first.title, "[видеоигры] SPB #14")
        self.assertEqual(first.when, "Сб, 28 ноя. 19:30")
        self.assertEqual(first.place, "Соус")
        self.assertEqual(first.price, "700")
        question = poll_question(first)
        self.assertIn("[видеоигры] SPB #14", question)
        self.assertIn("Квиз, плиз!", question)
        self.assertIn("Сб, 28 ноя. 19:30", question)
        self.assertIn("Соус", question)
        self.assertIn("700 ₽", question)
        self.assertTrue(question.endswith("Идём?"))
        self.assertNotIn("http", question)
        self.assertLessEqual(len(question), 300)
        self.assertEqual(notices[1].organizer, "Шейкер квиз")
        self.assertEqual(notices[1].place, "Puberty")

    def test_plain_lines_without_urls(self) -> None:
        notices = parse_notices("👥 Квиз, плиз!\n🟢 Классика\n🗓 Пт, 20 ноя. 19:30\n🍻 Фасоль")
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].price, "")
        self.assertIn("Фасоль", poll_question(notices[0]))

    def test_forward_without_emoji_marks(self) -> None:
        notices = parse_notices(
            "Квиз, плиз!\n[видеоигры] SPB #14\nСб, 28 ноя. 19:30 💰700\nСоус"
        )
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].organizer, "Квиз, плиз!")
        self.assertEqual(notices[0].title, "[видеоигры] SPB #14")
        self.assertEqual(notices[0].when, "Сб, 28 ноя. 19:30")
        self.assertEqual(notices[0].place, "Соус")
        self.assertEqual(notices[0].price, "700")

    def test_notice_date_lands_on_the_announced_saturday(self) -> None:
        moment = parse_notice_start("Сб, 28 ноя. 19:30", date(2026, 11, 23))
        self.assertIsNotNone(moment)
        assert moment is not None
        self.assertEqual(moment.year, 2026)
        self.assertEqual(moment.month, 11)
        self.assertEqual(moment.day, 28)
        self.assertEqual(moment.hour, 19)
        self.assertEqual(moment.minute, 30)

    def test_week_text_counts_only_people_who_are_going(self) -> None:
        start, end = week_bounds(date(2026, 11, 23))
        text = format_week(
            [
                {
                    "starts_at": "2026-11-28 19:30",
                    "when_text": "Сб, 28 ноя. 19:30",
                    "title": "[видеоигры] SPB #14",
                    "organizer": "Квиз, плиз!",
                    "place": "Соус",
                    "going": 5,
                    "options": [
                        {"text": "Иду", "count": 5},
                        {"text": "Возможно", "count": 2},
                        {"text": "Не иду", "count": 0},
                        {"text": "Опоздаю", "count": 1},
                    ],
                }
            ],
            start,
            end,
        )
        self.assertIn("28.11", text)
        self.assertIn("19:30", text)
        self.assertIn("Квиз, плиз!", text)
        self.assertIn("Соус", text)
        self.assertIn("Иду — 5", text)
        self.assertIn("Возможно — 2", text)
        self.assertIn("Не иду — 0", text)
        self.assertIn("Опоздаю — 1", text)

    def test_question_roundtrip_keeps_quiz_details(self) -> None:
        source = parse_notices(SAMPLE)[0]
        restored = notice_from_question(poll_question(source), date(2026, 11, 23))
        self.assertEqual(restored.title, source.title)
        self.assertEqual(restored.organizer, source.organizer)
        self.assertEqual(restored.when, source.when)
        self.assertEqual(restored.place, source.place)
        self.assertEqual(restored.price, source.price)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "quiz.db"))
        await self.db.init()
        added = await seed_if_empty(self.db)
        self.assertGreater(added, 0)
        self.schedule_patch = patch(
            "quizhub.web.fetch_schedule",
            new_callable=AsyncMock,
            side_effect=ScheduleUnavailable(),
        )
        self.schedule_patch.start()

    async def asyncTearDown(self) -> None:
        self.schedule_patch.stop()
        self.tmp.cleanup()

    async def test_today_search_in_spb(self) -> None:
        today = today_msk()
        parsed, city, found = await collect(
            self.db, "сегодня", "spb", today, source=self.db.quizzes_between
        )
        self.assertEqual(city, "spb")
        self.assertEqual(parsed.date_from, today)
        self.assertTrue(found)
        self.assertTrue(all(row["starts_at"].startswith(today.isoformat()) for row in found))

    async def test_unknown_topic_still_shows_the_day(self) -> None:
        parsed, _, found = await collect(
            self.db, "абракадабра сегодня", "spb", today_msk(), source=self.db.quizzes_between
        )
        self.assertTrue(parsed.relaxed)
        self.assertTrue(found)
        self.assertTrue(all("абракадабра" not in row["title"].lower() for row in found))

    async def test_week_polls_keep_only_going_votes(self) -> None:
        start, end = week_bounds(date(2026, 11, 23))
        await self.db.save_poll_quiz(
            poll_id="poll-1",
            chat_id=42,
            organizer="Квиз, плиз!",
            title="[видеоигры] SPB #14",
            place="Соус",
            starts_at="2026-11-28 19:30",
            when_text="Сб, 28 ноя. 19:30",
            going_option_id="going",
        )
        await self.db.save_poll_quiz(
            poll_id="poll-later",
            chat_id=42,
            organizer="Другой",
            title="После недели",
            place="Бар",
            starts_at=(end + timedelta(days=1)).strftime("%Y-%m-%d") + " 19:30",
            when_text="позже",
            going_option_id="going",
        )
        await self.db.save_poll_vote(
            poll_id="poll-1", telegram_id=1, going=True, name="Анна", username="anna"
        )
        await self.db.save_poll_vote(
            poll_id="poll-1", telegram_id=2, going=False, name="Борис", username=None
        )
        await self.db.save_poll_vote(
            poll_id="poll-1", telegram_id=1, going=False, name="Анна", username="anna"
        )
        await self.db.save_poll_vote(
            poll_id="poll-1", telegram_id=1, going=True, name="Анна", username="anna"
        )
        rows = await self.db.week_polls(42, start, end)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "[видеоигры] SPB #14")
        self.assertEqual(rows[0]["going"], 1)
        self.assertEqual(await self.db.poll_going_option("poll-1"), "going")
        self.assertIsNone(await self.db.poll_going_option("missing"))

    async def test_added_poll_uses_snapshot_until_new_votes(self) -> None:
        start, end = week_bounds(date(2026, 11, 23))
        await self.db.save_poll_quiz(
            poll_id="poll-snap",
            chat_id=42,
            organizer="Квиз, плиз!",
            title="Классика",
            place="Соус",
            starts_at="2026-11-28 19:30",
            when_text="Сб, 28 ноя. 19:30",
            going_option_id="going",
            going_snapshot=2,
        )
        rows = await self.db.week_polls(42, start, end)
        self.assertEqual(rows[0]["going"], 2)
        await self.db.save_poll_options(
            "poll-snap",
            [("going", "Иду", 2), ("maybe", "Возможно", 1), ("no", "Не иду", 0)],
            replace_counts=True,
        )
        await self.db.apply_option_vote("poll-snap", None, ["maybe"])
        rows = await self.db.week_polls(42, start, end)
        self.assertEqual(
            [(item["text"], item["count"]) for item in rows[0]["options"]],
            [("Иду", 2), ("Возможно", 2), ("Не иду", 0)],
        )
        await self.db.adjust_going_snapshot("poll-snap", None, True)
        rows = await self.db.week_polls(42, start, end)
        self.assertEqual(rows[0]["going"], 3)

    async def test_quiz_is_removed_the_day_after_it_ends(self) -> None:
        await self.db.save_poll_quiz(
            poll_id="yesterday",
            chat_id=42,
            organizer="Квиз, плиз!",
            title="Вчера",
            place="Соус",
            starts_at="2026-11-22 19:30",
            when_text="Вс, 22 ноя. 19:30",
            going_option_id="going",
            going_snapshot=4,
        )
        await self.db.save_poll_vote(
            poll_id="yesterday", telegram_id=1, going=True, name="Анна", username=None
        )
        await self.db.save_poll_quiz(
            poll_id="today",
            chat_id=42,
            organizer="Квиз, плиз!",
            title="Сегодня",
            place="Соус",
            starts_at="2026-11-23 19:30",
            when_text="Пн, 23 ноя. 19:30",
            going_option_id="going",
        )
        removed = await self.db.delete_expired_polls(date(2026, 11, 23))
        self.assertEqual(removed, 1)
        self.assertIsNone(await self.db.poll_quiz("yesterday"))
        self.assertIsNone(await self.db.poll_vote_going("yesterday", 1))
        kept = await self.db.poll_quiz("today")
        self.assertIsNotNone(kept)
        assert kept is not None
        self.assertEqual(kept["title"], "Сегодня")

    async def test_team_post_and_personal_filter(self) -> None:
        _, _, found = await collect(
            self.db, "сегодня", "spb", today_msk(), source=self.db.quizzes_between
        )
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

    async def test_today_uses_supplied_schedule_not_demo(self) -> None:
        today = today_msk()

        async def source(city: str, start: date, days: int) -> list[dict]:
            self.assertEqual(city, "spb")
            self.assertEqual(start, today)
            self.assertEqual(days, 1)
            return [
                {
                    "id": "bjpnh",
                    "city_code": city,
                    "organizer": "БелкинКвиз",
                    "title": "№3.4 (33)",
                    "starts_at": f"{today.isoformat()} 19:30",
                    "place": "Фасоль",
                    "price": "600 ₽",
                    "max_team": 10,
                    "description": "",
                    "url": "https://vk.com/belkinquizspb",
                    "status": "open",
                    "tags": "",
                }
            ]

        _, _, found = await collect(self.db, "сегодня", "spb", today, source=source)
        self.assertEqual([row["title"] for row in found], ["№3.4 (33)"])
        self.assertTrue(all(row["organizer"] != "Мелодия" for row in found))

    async def test_seed_is_not_duplicated(self) -> None:
        again = await seed_if_empty(self.db)
        self.assertEqual(again, 0)


if __name__ == "__main__":
    unittest.main()
