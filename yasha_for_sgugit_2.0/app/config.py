"""Настройки бота: переменные окружения и (необязательно) файл .env."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise SystemExit(f"Переменная {name} должна быть числом, получено: {raw!r}") from e


@dataclass(frozen=True)
class Settings:
    bot_token: str
    superadmin_id: int
    database_url: str
    timezone: str
    schedule_source_url: str
    sync_interval_min: int
    backup_dir: str
    log_level: str
    directory_url: str = "https://sgugit.ru/teachers/"
    webhook_url: str = ""
    webhook_path: str = "/telegram/webhook"
    webhook_secret: str = ""
    webhook_port: int = 8080


def load_settings() -> Settings:
    _load_dotenv()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задана переменная BOT_TOKEN (токен от @BotFather).")
    sid = _int("SUPERADMIN_ID", 0)
    if sid <= 0:
        raise SystemExit("Не задана переменная SUPERADMIN_ID (Telegram ID главного админа).")
    return Settings(
        bot_token=token,
        superadmin_id=sid,
        database_url=os.environ.get("DATABASE_URL", "sqlite:///data/bot.db").strip(),
        timezone=os.environ.get("TIMEZONE", "Asia/Novosibirsk").strip(),
        schedule_source_url=os.environ.get("SCHEDULE_SOURCE_URL", "https://sgugit.ru/raspisanie").strip(),
        sync_interval_min=max(5, _int("SYNC_INTERVAL_MIN", 30)),
        backup_dir=os.environ.get("BACKUP_DIR", "data/backups").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        directory_url=os.environ.get("DIRECTORY_URL", "https://sgugit.ru/teachers/").strip(),
        webhook_url=os.environ.get("WEBHOOK_URL", "").strip().rstrip("/"),
        webhook_path="/" + os.environ.get("WEBHOOK_PATH", "telegram/webhook").strip("/"),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", "").strip(),
        webhook_port=max(1, min(65535, _int("WEBHOOK_PORT", 8080))),
    )
