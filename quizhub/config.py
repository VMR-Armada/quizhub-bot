from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_env_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SystemExit(
            f"Файл {path} сохранён в кодировке, которую бот не читает.\n"
            "Откройте его в редакторе и сохраните как UTF-8."
        ) from error


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in _read_env_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    web_host: str
    web_port: int
    public_base_url: str
    db_path: str

    def is_admin(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id in self.admin_ids


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.exists() and not os.environ.get("BOT_TOKEN", "").strip():
        raise SystemExit(
            f"Не найден файл {env_path}.\n"
            "Скопируйте .env.example в .env и вставьте токен, который выдаёт @BotFather командой /newbot."
        )
    _load_dotenv(env_path)

    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token or token.startswith("123456:replace"):
        raise SystemExit(
            f"В {env_path} всё ещё шаблонный BOT_TOKEN.\n"
            "Вставьте настоящий токен от @BotFather. Кавычки и пробелы вокруг него не нужны."
        )

    admin_ids: set[int] = set()
    for part in os.environ.get("ADMIN_IDS", "").split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.add(int(part))

    base = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    db_path = os.environ.get("DB_PATH", "data/quizhub.db")
    if not Path(db_path).is_absolute():
        db_path = str(root / db_path)

    return Settings(
        bot_token=token,
        admin_ids=frozenset(admin_ids),
        web_host=os.environ.get("WEB_HOST", "127.0.0.1"),
        web_port=int(os.environ.get("WEB_PORT", "8080")),
        public_base_url=base,
        db_path=db_path,
    )
