from __future__ import annotations

import html
from datetime import datetime

from aiohttp import web

from quizhub.db import Database
from quizhub.format import MONTHS, WEEKDAY_SHORT, status_icon
from quizhub.timeutil import EVENING_HOUR, parse_stored, today_msk

TABLE_DAYS = 21


DB_KEY: web.AppKey[Database] = web.AppKey("db", Database)


def create_web_app(db: Database) -> web.Application:
    app = web.Application()
    app[DB_KEY] = db
    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/dashboard/{city}", dashboard)
    app.router.add_get("/t/{token}", personal)
    app.router.add_post("/t/{token}/filter", save_filter)
    app.router.add_get("/quiz/{quiz_id}", quiz_page)
    return app


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def home(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    cities = await db.cities()
    cards = "\n".join(
        f'<a class="card" href="/dashboard/{html.escape(city["code"])}">{html.escape(city["name"])}</a>'
        for city in cities
    )
    body = f"""
      <h1>QuizHub</h1>
      <p class="lead">Расписание барных квизов. Выберите город — откроется таблица на три недели.</p>
      <div class="cards">{cards}</div>
    """
    return _page("QuizHub", body)


async def dashboard(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    city = request.match_info["city"]
    name = await db.city_name(city)
    if name is None:
        raise web.HTTPNotFound(text="Такого города нет")
    start = today_msk()
    quizzes = await db.quizzes_between(city, start, TABLE_DAYS)
    body = _table_block(name, quizzes, filter_form=None)
    return _page(f"Расписание — {name}", body)


async def personal(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    link = await db.table_link(request.match_info["token"])
    if link is None:
        raise web.HTTPNotFound(text="Ссылка на таблицу не найдена")
    name = await db.city_name(link["city_code"]) or link["city_code"]
    start = today_msk()
    quizzes = await db.quizzes_between(link["city_code"], start, TABLE_DAYS)
    quizzes = _apply_filter(quizzes, link["filter_mode"], link["organizers"])
    organizers = await db.organizers(link["city_code"], start, TABLE_DAYS)
    form = _filter_form(request.match_info["token"], organizers, link["filter_mode"], set(link["organizers"]))
    body = _table_block(name, quizzes, filter_form=form)
    return _page(f"Моя таблица — {name}", body)


async def save_filter(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    token = request.match_info["token"]
    link = await db.table_link(token)
    if link is None:
        raise web.HTTPNotFound(text="Ссылка на таблицу не найдена")
    form = await request.post()
    mode = str(form.get("mode") or "blacklist")
    organizers = [str(item) for item in form.getall("organizer")] if "organizer" in form else []
    await db.save_table_filter(token, mode, organizers)
    raise web.HTTPFound(f"/t/{token}")


async def quiz_page(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    try:
        quiz_id = int(request.match_info["quiz_id"])
    except ValueError as error:
        raise web.HTTPNotFound(text="Квиз не найден") from error
    quiz = await db.get_quiz(quiz_id)
    if quiz is None:
        raise web.HTTPNotFound(text="Квиз не найден")
    city = await db.city_name(quiz["city_code"]) or quiz["city_code"]
    posts = await db.team_posts(quiz_id)
    moment = parse_stored(quiz["starts_at"])
    teams = [post for post in posts if post["kind"] == "team"]
    players = [post for post in posts if post["kind"] == "player"]
    link = ""
    if quiz.get("url"):
        url = html.escape(quiz["url"], quote=True)
        link = f'<p><a href="{url}">Регистрация у организатора</a></p>'
    body = f"""
      <p><a href="/dashboard/{html.escape(quiz["city_code"])}">← {html.escape(city)}</a></p>
      <h1>{status_icon(quiz["status"])} {html.escape(quiz["title"])}</h1>
      <ul class="facts">
        <li>{html.escape(_long_when(moment))}</li>
        <li>{html.escape(quiz["organizer"])}</li>
        <li>{html.escape(quiz["place"])}</li>
        {f'<li>{html.escape(quiz["price"])}</li>' if quiz.get("price") else ""}
        {f'<li>До {int(quiz["max_team"])} человек в команде</li>' if quiz.get("max_team") else ""}
      </ul>
      <p>{html.escape(quiz.get("description") or "")}</p>
      {link}
      <h2>Ищут игрока</h2>
      {_posts_html(players)}
      <h2>Ищут команду</h2>
      {_posts_html(teams)}
    """
    return _page(quiz["title"], body)


def _apply_filter(quizzes: list[dict], mode: str, organizers: list[str]) -> list[dict]:
    chosen = set(organizers)
    if mode == "whitelist":
        return [quiz for quiz in quizzes if quiz["organizer"] in chosen]
    if not chosen:
        return quizzes
    return [quiz for quiz in quizzes if quiz["organizer"] not in chosen]


def _filter_form(token: str, organizers: list[str], mode: str, chosen: set[str]) -> str:
    checks = "\n".join(
        f"""<label><input type="checkbox" name="organizer" value="{html.escape(name, quote=True)}" {"checked" if name in chosen else ""}> {html.escape(name)}</label>"""
        for name in organizers
    )
    whitelist = "checked" if mode == "whitelist" else ""
    blacklist = "checked" if mode != "whitelist" else ""
    return f"""
      <form class="filter" method="post" action="/t/{html.escape(token)}/filter">
        <h2>Фильтр организаторов</h2>
        <label><input type="radio" name="mode" value="blacklist" {blacklist}> Скрывать отмеченных</label>
        <label><input type="radio" name="mode" value="whitelist" {whitelist}> Показывать только отмеченных</label>
        <div class="orgs">{checks}</div>
        <button type="submit">Сохранить фильтр</button>
      </form>
    """


def _table_block(city_name: str, quizzes: list[dict], filter_form: str | None) -> str:
    start = today_msk()
    days = [start.fromordinal(start.toordinal() + offset) for offset in range(TABLE_DAYS)]
    by_org: dict[str, dict] = {}
    for quiz in quizzes:
        moment = parse_stored(quiz["starts_at"])
        bucket = by_org.setdefault(quiz["organizer"], {})
        bucket.setdefault(moment.date().isoformat(), []).append(quiz)
    organizers = sorted(by_org, key=str.casefold)
    head = "".join(
        f'<th class="{"weekend" if day.weekday() >= 5 else ""}">{WEEKDAY_SHORT[day.weekday()]}, {day.strftime("%d.%m")}</th>'
        for day in days
    )
    body_rows = []
    for organizer in organizers:
        cells = []
        for day in days:
            cell_quizzes = by_org[organizer].get(day.isoformat(), [])
            cell_quizzes.sort(key=lambda item: item["starts_at"])
            day_part = [item for item in cell_quizzes if parse_stored(item["starts_at"]).hour < EVENING_HOUR]
            evening = [item for item in cell_quizzes if parse_stored(item["starts_at"]).hour >= EVENING_HOUR]
            inner = _cell(day_part)
            if day_part and evening:
                inner += '<div class="split"></div>'
            inner += _cell(evening)
            weekend = " weekend" if day.weekday() >= 5 else ""
            cells.append(f'<td class="cell{weekend}">{inner}</td>')
        body_rows.append(
            "<tr><th>" + html.escape(organizer) + "</th>" + "".join(cells) + "</tr>"
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="22">На эти недели квизов нет.</td></tr>')
    form = filter_form or ""
    return f"""
      <p><a href="/">Все города</a></p>
      <h1>{html.escape(city_name)}</h1>
      <p class="lead">До 18:00 игра стоит выше разделителя, вечерние — ниже. Зелёный кружок — есть места, жёлтый — мало, оранжевый — мест нет.</p>
      <input id="q" placeholder="Название, организатор, место" oninput="filterRows()">
      {form}
      <div class="scroll">
        <table>
          <thead><tr><th>Организатор</th>{head}</tr></thead>
          <tbody>{"".join(body_rows)}</tbody>
        </table>
      </div>
      <script>
        function filterRows() {{
          const q = document.getElementById('q').value.toLowerCase();
          document.querySelectorAll('tbody tr').forEach((row) => {{
            row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
          }});
        }}
      </script>
    """


def _cell(quizzes: list[dict]) -> str:
    chunks = []
    for quiz in quizzes:
        moment = parse_stored(quiz["starts_at"])
        chunks.append(
            f'<a class="quiz" href="/quiz/{quiz["id"]}">'
            f'{status_icon(quiz["status"])} {html.escape(quiz["title"])}'
            f'<small>{moment.strftime("%H:%M")} · {html.escape(quiz["place"])}</small></a>'
        )
    return "".join(chunks)


def _posts_html(posts: list[dict]) -> str:
    if not posts:
        return "<p class='muted'>Пока никто не написал.</p>"
    items = []
    for post in posts:
        who = html.escape(post["name"])
        if post.get("username"):
            who += f" (@{html.escape(post['username'])})"
        note = f" — {html.escape(post['note'])}" if post.get("note") else ""
        items.append(f"<li>{who}{note}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _long_when(moment: datetime) -> str:
    return (
        f"{WEEKDAY_SHORT[moment.weekday()]}, {moment.day} {MONTHS[moment.month - 1]} "
        f"в {moment.strftime('%H:%M')}"
    )


def _page(title: str, body: str) -> web.Response:
    html_doc = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#1d2430; --muted:#5d6b7c; --line:#e4d7c5; --paper:#f6f1e8; --card:#fffdf8; --accent:#0f6e6e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font:16px/1.45 Georgia, "Iowan Old Style", serif; color:var(--ink); background:var(--paper); }}
    main {{ max-width:1100px; margin:0 auto; padding:28px 18px 60px; }}
    h1 {{ font-weight:600; margin:0 0 8px; }}
    h2 {{ font-size:1.05rem; margin:22px 0 8px; }}
    a {{ color:var(--accent); }}
    .lead, .muted {{ color:var(--muted); }}
    .cards {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; text-decoration:none; color:var(--ink); }}
    input, button {{ font:inherit; }}
    #q, .filter {{ width:min(100%, 520px); }}
    #q {{ display:block; margin:14px 0; padding:10px 12px; border:1px solid var(--line); border-radius:10px; background:white; }}
    .filter {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px 16px; margin-bottom:14px; }}
    .filter label {{ display:block; margin:4px 0; }}
    .orgs {{ max-height:180px; overflow:auto; margin:8px 0 12px; }}
    button {{ background:var(--accent); color:white; border:0; border-radius:10px; padding:8px 14px; cursor:pointer; }}
    .scroll {{ overflow:auto; border:1px solid var(--line); border-radius:12px; background:white; }}
    table {{ border-collapse:collapse; min-width:900px; }}
    th, td {{ border-bottom:1px solid var(--line); border-right:1px solid #f0e7da; vertical-align:top; padding:6px; font-size:13px; }}
    thead th {{ position:sticky; top:0; background:#fff8ee; z-index:1; }}
    tbody th {{ position:sticky; left:0; background:#fffdf8; text-align:left; min-width:140px; }}
    .weekend {{ background:#f3f7f4; }}
    .cell {{ min-width:150px; }}
    .quiz {{ display:block; text-decoration:none; color:var(--ink); margin:0 0 6px; }}
    .quiz small {{ display:block; color:var(--muted); }}
    .split {{ height:1px; background:#d9c7a8; margin:4px 0; }}
    .facts {{ padding-left:18px; }}
  </style>
</head>
<body><main>{body}</main></body>
</html>"""
    return web.Response(text=html_doc, content_type="text/html")
