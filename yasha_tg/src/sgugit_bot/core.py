# Shared infrastructure: database, schedule parsing, formatting and UI helpers.

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import base64
import hmac
import secrets
import html
from html.parser import HTMLParser
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements installs python-dotenv
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Union
from zoneinfo import ZoneInfo

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    LabeledPrice,
)
from telegram.constants import ParseMode
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

OWNER_ID = int(os.getenv("OWNER_ID", "1174432700"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
# Sponsor secret is managed in the owner panel / SQLite.
# Keep only a runtime fallback derived from BOT_TOKEN; no .env key is required.
SPONSOR_TRACKING_SECRET = (BOT_TOKEN or "change-me").encode()
WEB_PORT = int(os.getenv("PORT", "8080"))
BOT_APPLICATION = None
ADMIN_IDS = {OWNER_ID}


# Старосты хранятся в БД и назначаются владельцем через панель.


SCHEDULE_URL = os.getenv("SCHEDULE_URL", "https://sgugit.ru/raspisanie/").strip()

DB_PATH = Path(os.getenv("DB_PATH", "./data/sgugit.sqlite3"))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

TZ = ZoneInfo("Asia/Novosibirsk")
NOTIFY_HOUR = 20
NOTIFY_MINUTE = 0

# Проверяем источник каждые 5 минут.
SOURCE_CHECK_SECONDS = 300
# Небольшая проверка времени рассылки.
CLOCK_CHECK_SECONDS = 10

HTTP_TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/130 Safari/537.36 "
        "SGUGiTStudentService/2.0"
    )
}

WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
WEEKDAY_SET = set(WEEKDAYS)

MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

# Время пар, которое сейчас используется на странице.
# Parser не требует, чтобы все пары присутствовали.
TIME_PAIR_RE = re.compile(r"^(?P<a>\d{2}:\d{2})\s*$")
DATE_RE = re.compile(r"^(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{2})$")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("md221")


# ============================================================
# DATA
# ============================================================

@dataclass(frozen=True)
class Lesson:
    start: str
    end: str
    subject: str
    teacher: str = ""
    room: str = ""
    kind: str = ""

    def key(self) -> tuple:
        return (
            self.start,
            self.end,
            self.subject.strip(),
            self.teacher.strip(),
            self.room.strip(),
            self.kind.strip().lower(),
        )


@dataclass
class DaySchedule:
    day: date
    lessons: list[Lesson]


# ============================================================
# DB
# ============================================================

def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("""
        CREATE TABLE IF NOT EXISTS ui_state (
            chat_id INTEGER PRIMARY KEY,
            last_ui_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            daily_enabled INTEGER NOT NULL DEFAULT 1,
            change_enabled INTEGER NOT NULL DEFAULT 1,
            registered_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            key TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            day TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS leaders (
            chat_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            added_by INTEGER NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS manual_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            teacher TEXT NOT NULL DEFAULT '',
            room TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            group_code TEXT NOT NULL DEFAULT ''
        )
    """)
    mc_cols={r[1] for r in c.execute('PRAGMA table_info(manual_changes)').fetchall()}
    if 'group_code' not in mc_cols:
        c.execute("ALTER TABLE manual_changes ADD COLUMN group_code TEXT NOT NULL DEFAULT ''")

    c.commit()
    return c


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat()


def register_user(chat_id: int, username: str = "", first_name: str = ""):
    stamp = now_iso()
    with connect() as c:
        c.execute(
            """
            INSERT INTO users
              (chat_id, username, first_name, registered_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name,
              last_seen=excluded.last_seen
            """,
            (chat_id, username or "", first_name or "", stamp, stamp),
        )


def user(chat_id: int):
    with connect() as c:
        return c.execute(
            """
            SELECT chat_id, username, first_name,
                   daily_enabled, change_enabled
            FROM users WHERE chat_id=?
            """,
            (chat_id,),
        ).fetchone()


def set_setting(chat_id: int, field: str, value: bool):
    if field not in {"daily_enabled", "change_enabled"}:
        raise ValueError(field)

    with connect() as c:
        numeric = 1 if value else 0
        c.execute(
            f"UPDATE users SET {field}=?, last_seen=? WHERE chat_id=?",
            (numeric, now_iso(), chat_id),
        )
        # Keep legacy settings and the current notification center in sync.
        mirror = {"daily_enabled": "notify_daily", "change_enabled": "notify_changes"}.get(field)
        if mirror:
            c.execute(f"UPDATE users SET {mirror}=? WHERE chat_id=?", (numeric, chat_id))


def users_for(field: str) -> list[int]:
    if field not in {"daily_enabled", "change_enabled"}:
        raise ValueError(field)

    with connect() as c:
        rows = c.execute(
            f"SELECT chat_id FROM users WHERE {field}=1"
        ).fetchall()
    return [int(r[0]) for r in rows]


def count_users() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def delivered(key: str) -> bool:
    with connect() as c:
        return c.execute(
            "SELECT 1 FROM deliveries WHERE key=?",
            (key,),
        ).fetchone() is not None


def mark_delivered(key: str):
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO deliveries(key, created_at) VALUES (?, ?)",
            (key, now_iso()),
        )


def log_event(event: str, data: str = ""):
    with connect() as c:
        c.execute(
            "INSERT INTO events(event, data, created_at) VALUES (?, ?, ?)",
            (event, data, now_iso()),
        )


def snapshot_get(d: date):
    with connect() as c:
        return c.execute(
            "SELECT fingerprint, payload FROM snapshots WHERE day=?",
            (d.isoformat(),),
        ).fetchone()


def snapshot_put(d: date, fingerprint: str, payload: str):
    with connect() as c:
        c.execute(
            """
            INSERT INTO snapshots(day, fingerprint, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
              fingerprint=excluded.fingerprint,
              payload=excluded.payload,
              updated_at=excluded.updated_at
            """,
            (d.isoformat(), fingerprint, payload, now_iso()),
        )


# ============================================================
# LEADERS / MANUAL OVERRIDES
# ============================================================

def remove_leader(chat_id: int):
    with connect() as c:
        c.execute("DELETE FROM leaders WHERE chat_id=?", (chat_id,))


def is_leader(chat_id: int) -> bool:
    with connect() as c:
        row = c.execute("SELECT 1 FROM leaders WHERE chat_id=?", (chat_id,)).fetchone()
    return bool(row)


def leader_rows() -> list[tuple]:
    with connect() as c:
        return c.execute(
            "SELECT chat_id, username, first_name, added_at FROM leaders ORDER BY added_at"
        ).fetchall()


def manual_rows(day: date, group_code: str = '', active_only: bool = True) -> list[tuple]:
    q = "SELECT id, start, end, action, subject, teacher, room, kind, reason, author_id, author_name, created_at, active, group_code FROM manual_changes WHERE day=?"
    args = [day.isoformat()]
    if group_code:
        q += " AND (group_code=? OR group_code='')"
        args.append(group_code)
    if active_only:
        q += " AND active=1"
    q += " ORDER BY id"
    with connect() as c:
        return c.execute(q, args).fetchall()


def record_manual_change(day: date, start: str, end: str, action: str,
                         subject: str = '', teacher: str = '', room: str = '',
                         kind: str = '', reason: str = '', author_id: int = 0,
                         author_name: str = '', group_code: str = '') -> int:
    with connect() as c:
        cur = c.execute(
            """INSERT INTO manual_changes
               (day,start,end,action,subject,teacher,room,kind,reason,author_id,author_name,created_at,active,group_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
            (day.isoformat(), start, end, action, subject, teacher, room, kind, reason,
             author_id, author_name, now_iso(), group_code),
        )
        return int(cur.lastrowid)


def deactivate_change(change_id: int):
    with connect() as c:
        c.execute("UPDATE manual_changes SET active=0 WHERE id=?", (change_id,))


def clear_slot_overrides(day: date, start: str, group_code: str = ''):
    with connect() as c:
        if group_code:
            c.execute("UPDATE manual_changes SET active=0 WHERE day=? AND start=? AND group_code=? AND active=1",
                      (day.isoformat(), start, group_code))
        else:
            c.execute("UPDATE manual_changes SET active=0 WHERE day=? AND start=? AND active=1",
                      (day.isoformat(), start))

def apply_manual_overrides(day: date, official: list[Lesson], group_code: str = '') -> tuple[list[Lesson], list[dict]]:
    """Накладывает правки старосты поверх официального расписания.
    Возвращает итог и метаданные правок для красивой пометки в сообщении."""
    result = list(official)
    changes = manual_rows(day, group_code)
    marks = []

    for row in changes:
        _, start, end, action, subject, teacher, room, kind, reason, author_id, author_name, created_at, _, _group_code = row
        if action == 'delete':
            before = len(result)
            result = [x for x in result if x.start != start]
            if before != len(result):
                marks.append({'start': start, 'label': f'Удалено старостой {author_name or author_id}', 'reason': reason})
        elif action in {'add', 'replace'}:
            result = [x for x in result if x.start != start]
            result.append(Lesson(start, end, subject, teacher, room, kind))
            marks.append({'start': start, 'label': f'Изменено старостой {author_name or author_id}', 'reason': reason})

    result.sort(key=lambda x: x.start)
    return result, marks


# ============================================================
# SOURCE + PARSER
# ============================================================

class ScheduleError(Exception):
    pass


class ScheduleClient:
    _cache: dict[date, list[Lesson]] = {}
    _loaded_at: Optional[datetime] = None
    _last_html_hash: Optional[str] = None

    @classmethod
    def fetch(cls) -> str:
        try:
            r = requests.get(
                SCHEDULE_URL,
                headers=HEADERS,
                timeout=HTTP_TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise ScheduleError(f"Ошибка сайта: {e}") from e

        if not r.text or len(r.text) < 500:
            raise ScheduleError("Сайт вернул слишком короткий ответ.")

        r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    @classmethod
    def load(cls, force: bool = False) -> dict[date, list[Lesson]]:
        if (
            not force
            and cls._loaded_at
            and (now() - cls._loaded_at).total_seconds() < 120
            and cls._cache
        ):
            return cls._cache

        html_text = cls.fetch()
        parsed = parse_schedule(html_text)

        if not parsed:
            raise ScheduleError(
                "Не удалось найти ни одной даты на странице."
            )

        cls._cache = parsed
        cls._loaded_at = now()
        cls._last_html_hash = hashlib.sha256(
            html_text.encode("utf-8", "ignore")
        ).hexdigest()

        # Не записываем snapshot здесь до сравнения:
        # изменения определяются отдельной функцией.
        return parsed


class _ScheduleTextParser(HTMLParser):
    """Minimal stdlib HTML-to-text parser used for the schedule page.

    Uses only the Python standard library, so it runs without extra HTML
    parser dependencies on Bothost/Docker. Script/style/noscript contents are ignored.
    """

    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div",
        "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
        "main", "nav", "ol", "p", "pre", "section", "table", "tbody",
        "td", "tfoot", "th", "thead", "tr", "ul",
    }
    IGNORED_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if self._ignored_depth:
            return
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def clean_lines(html_text: str) -> list[str]:
    parser = _ScheduleTextParser()
    parser.feed(html_text or "")
    parser.close()

    lines: list[str] = []
    for raw in "".join(parser.parts).splitlines():
        value = re.sub(r"\s+", " ", raw).strip()
        if value:
            lines.append(value)
    return lines


def is_date_line(value: str) -> bool:
    return DATE_RE.fullmatch(value) is not None


def parse_date(value: str) -> date:
    m = DATE_RE.fullmatch(value)
    if not m:
        raise ValueError(value)
    year = 2000 + int(m.group("y"))
    return date(year, int(m.group("m")), int(m.group("d")))


def is_time(value: str) -> bool:
    return TIME_PAIR_RE.fullmatch(value) is not None


def is_metadata_kind(value: str) -> bool:
    v = value.lower().strip()
    return v in {
        "лекция",
        "практика",
        "лабораторная",
        "лабораторное занятие",
        "семинар",
        "экзамен",
        "зачет",
        "зачёт",
        "консультация",
        "курсовая работа",
        "курсовой проект",
    }


def looks_like_room(value: str) -> bool:
    v = value.strip().lower()
    if not v:
        return False
    if v in {"без аудитории", "спортзал"}:
        return True
    if re.fullmatch(r"[0-9А-ЯA-ZЁ./_-]{1,15}", value.strip()):
        return True
    return False


def parse_schedule(html_text: str) -> dict[date, list[Lesson]]:
    """
    Ключевая идея:
    после даты идут временные интервалы. Каждый интервал — отдельный слот.
    Если после интервала нет предмета до следующего интервала, слот пустой.
    Поэтому пустые пары не сдвигают следующие занятия.
    """

    lines = clean_lines(html_text)
    result: dict[date, list[Lesson]] = {}

    current_date: Optional[date] = None
    i = 0

    while i < len(lines):
        line = lines[i]

        if is_date_line(line):
            try:
                current_date = parse_date(line)
                result.setdefault(current_date, [])
            except ValueError:
                current_date = None
            i += 1
            continue

        if current_date is None or line in WEEKDAY_SET:
            i += 1
            continue

        # На странице время начала и время окончания идут двумя строками.
        if not is_time(line):
            i += 1
            continue

        if i + 1 >= len(lines) or not is_time(lines[i + 1]):
            i += 1
            continue

        start = line
        end = lines[i + 1]
        i += 2

        # После временного интервала:
        # - либо сразу следующий временной интервал => пустая пара;
        # - либо название предмета и его metadata.
        if i >= len(lines):
            continue

        if is_date_line(lines[i]) or lines[i] in WEEKDAY_SET or is_time(lines[i]):
            continue

        # Служебные строки.
        if lines[i].startswith("Расписание") or lines[i].startswith("Группа "):
            continue

        subject = lines[i]
        i += 1

        meta: list[str] = []

        # Читаем только до следующего временного интервала/даты.
        while i < len(lines):
            nxt = lines[i]

            if is_date_line(nxt) or nxt in WEEKDAY_SET or is_time(nxt):
                break

            # Иногда на сайте есть технические элементы.
            if nxt.startswith("Расписание"):
                break
            if nxt.startswith("Группа "):
                break

            meta.append(nxt)
            i += 1

            # Нормальный блок: преподаватель + аудитория + тип.
            # Если тип уже найден, дальше брать ничего не нужно.
            if is_metadata_kind(nxt):
                break

            if len(meta) >= 3:
                break

        kind = ""
        kind_idx = None
        for idx, value in enumerate(meta):
            if is_metadata_kind(value):
                kind = value
                kind_idx = idx
                break

        before = meta[:kind_idx] if kind_idx is not None else meta

        teacher = ""
        room = ""

        if len(before) >= 2:
            teacher = before[0]
            room = before[1]
        elif len(before) == 1:
            if looks_like_room(before[0]):
                room = before[0]
            else:
                teacher = before[0]

        result[current_date].append(
            Lesson(
                start=start,
                end=end,
                subject=subject,
                teacher=teacher,
                room=room,
                kind=kind,
            )
        )

    # Убираем дубли и сортируем.
    for d in result:
        unique: dict[tuple, Lesson] = {}
        for lesson in result[d]:
            unique[lesson.key()] = lesson

        result[d] = sorted(
            unique.values(),
            key=lambda x: x.start,
        )

    return result


# ============================================================
# SNAPSHOT / CHANGE DETECTION
# ============================================================

def serialize(lessons: list[Lesson]) -> str:
    return json.dumps(
        [asdict(x) for x in lessons],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def fingerprint(lessons: list[Lesson]) -> str:
    return hashlib.sha256(
        serialize(lessons).encode("utf-8")
    ).hexdigest()


async def check_for_changes(application: Application):
    try:
        fresh = await asyncio.to_thread(ScheduleClient.load, True)
    except Exception as e:
        log.exception("Source check failed")
        log_event("source_error", str(e))
        return

    today = now().date()
    until = today + timedelta(days=14)

    for d, official_lessons in fresh.items():
        if not (today <= d <= until):
            continue

        lessons, _marks = apply_manual_overrides(d, official_lessons)
        fp = fingerprint(lessons)
        old = snapshot_get(d)

        # Первый запуск: просто создаём базовую версию.
        if old is None:
            snapshot_put(d, fp, serialize(lessons))
            continue

        old_fp = old[0]

        if old_fp == fp:
            continue

        # Обновляем snapshot ДО рассылки.
        snapshot_put(d, fp, serialize(lessons))

        key = f"change:{d.isoformat()}:{fp}"
        if delivered(key):
            continue

        text = (
            "⚠️ <b>Расписание изменилось</b>\n\n"
            + format_day(d, lessons)
            + "\n\n"
            "Проверь актуальность перед занятием."
        )

        await send_to_users(
            application,
            users_for("change_enabled"),
            text,
        )

        mark_delivered(key)
        log_event(
            "schedule_change",
            f"date={d.isoformat()} users={len(users_for('change_enabled'))}",
        )


# ============================================================
# FORMAT
# ============================================================

def esc(value: str) -> str:
    return html.escape(str(value), quote=False)


def date_ru(d: date) -> str:
    return (
        f"{WEEKDAYS[d.weekday()]}, "
        f"{d.day} {MONTHS[d.month]}"
    )


def format_lesson_card(n: int, x: Lesson, mark: Optional[str] = None) -> str:
    # Один цельный «карточный» блок: сразу понятно время → предмет → формат → преподаватель → кабинет.
    title = f"<b>{n:02d}  ·  {esc(x.start)}–{esc(x.end)}</b>"
    lines = [title, f"📘 <b>{esc(x.subject)}</b>"]
    meta = []
    if x.kind:
        meta.append(f"🎓 {esc(x.kind)}")
    if x.teacher:
        meta.append(f"👨‍🏫 {esc(x.teacher)}")
    if x.room:
        meta.append(f"📍 {esc(x.room)}")
    if meta:
        lines.append("  ·  ".join(meta))
    if mark:
        lines.append(f"✏️ <i>{esc(mark)}</i>")
    return "\n".join(lines)


def format_day(d: date, lessons: list[Lesson]) -> str:
    title = f"📅 <b>{esc(date_ru(d))}</b>"
    if not lessons:
        return title + "\n\n🟢 <b>Занятий нет — свободный день.</b>"

    blocks = [format_lesson_card(n, x) for n, x in enumerate(lessons, 1)]
    # Если есть активные правки, добавляем аккуратный статус, но не загромождаем каждую строку.
    if manual_rows(d):
        blocks.insert(0, "✏️ <b>Есть правки старосты</b> <i>— они применены поверх официального расписания.</i>")
    return title + "\n\n" + "\n\n".join(blocks)


def format_day_with_marks(d: date, lessons: list[Lesson], marks: list[dict]) -> str:
    mark_by_start = {m['start']: m['label'] + (f" — {m['reason']}" if m.get('reason') else '') for m in marks}
    title = f"📅 <b>{esc(date_ru(d))}</b>"
    if not lessons:
        base = title + "\n\n🟢 <b>Занятий нет — свободный день.</b>"
    else:
        base = title + "\n\n" + "\n\n".join(
            format_lesson_card(n, x, mark_by_start.get(x.start)) for n, x in enumerate(lessons, 1)
        )
    if marks:
        base += "\n\n✏️ <b>Правки старосты применены</b>"
    return base


def format_compact_day(d: date, lessons: list[Lesson]) -> str:
    if not lessons:
        return f"📅 <b>{esc(date_ru(d))}</b> — свободно"
    return (
        f"📅 <b>{esc(date_ru(d))}</b>\n"
        + "\n".join(
            f"• <b>{esc(x.start)}–{esc(x.end)}</b> · {esc(x.subject)}"
            + (f" · 📍 {esc(x.room)}" if x.room else "")
            for x in lessons
        )
    )


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Завтра", callback_data="tomorrow"),
            InlineKeyboardButton("📖 Сегодня", callback_data="today"),
        ],
        [
            InlineKeyboardButton("🗓 Неделя", callback_data="week"),
            InlineKeyboardButton("⏭ Следующая пара", callback_data="next"),
        ],
        [
            InlineKeyboardButton("🔔 Настройки", callback_data="settings"),
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh"),
        ],
        [
            InlineKeyboardButton("📆 Дата", callback_data="date"),
            InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
        ],
        [
            InlineKeyboardButton("🌐 Официальное расписание", url=SCHEDULE_URL),
        ],
    ])


def settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    row = user(chat_id)
    daily = bool(row[3]) if row else True
    changes = bool(row[4]) if row else True

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔔 Ежедневные: ВКЛ"
                if daily else
                "🔕 Ежедневные: ВЫКЛ",
                callback_data="toggle_daily",
            )
        ],
        [
            InlineKeyboardButton(
                "⚠️ Изменения: ВКЛ"
                if changes else
                "⚪ Изменения: ВЫКЛ",
                callback_data="toggle_changes",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="menu",
            )
        ],
    ])


# ============================================================
# CLEAN UI: one active bot screen per private chat
# ============================================================
async def _get_last_ui_message_id(chat_id: int) -> int:
    with connect() as c:
        row=c.execute("SELECT last_ui_message_id FROM ui_state WHERE chat_id=?",(chat_id,)).fetchone()
    return int(row[0]) if row and row[0] else 0


async def _set_last_ui_message_id(chat_id: int, message_id: int):
    with connect() as c:
        c.execute("""INSERT INTO ui_state(chat_id,last_ui_message_id,updated_at)
                     VALUES(?,?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET
                     last_ui_message_id=excluded.last_ui_message_id,
                     updated_at=excluded.updated_at""",
                  (chat_id,int(message_id),now_iso()))


async def _delete_previous_ui(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Delete only the previous BOT UI message, never the user's message."""
    mid=await _get_last_ui_message_id(chat_id)
    if not mid:
        return
    try:
        await context.application.bot.delete_message(chat_id=chat_id,message_id=mid)
    except Exception:
        pass
    await _set_last_ui_message_id(chat_id,0)
    context.user_data.pop("last_ui_message_id",None)


async def reply_ui(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
    message=update.effective_message
    chat=update.effective_chat
    if not message or not chat:
        return None
    await _delete_previous_ui(context,chat.id)
    sent=await message.reply_text(*args,**kwargs)
    await _set_last_ui_message_id(chat.id,sent.message_id)
    context.user_data["last_ui_message_id"]=sent.message_id
    return sent


async def send_ui(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs):
    """Same clean-screen behavior for scheduler/system messages that replace the UI."""
    await _delete_previous_ui(context, chat_id)
    sent = await context.application.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    context.user_data["last_ui_message_id"] = sent.message_id
    return sent



async def ensure_user(update: Update):
    if not update.effective_chat:
        return

    u = update.effective_user
    register_user(
        update.effective_chat.id,
        u.username if u else "",
        u.first_name if u else "",
    )


async def send_to_users(
    application: Application,
    chat_ids: list[int],
    text: str,
    keyboard: Optional[Union[InlineKeyboardMarkup, Callable[[int], InlineKeyboardMarkup]]] = None,
    delivery_key: Optional[Union[str, Callable[[int], str]]] = None,
) -> tuple[int, int]:
    success = 0
    failed = 0

    for chat_id in chat_ids:
        key = delivery_key(chat_id) if callable(delivery_key) else delivery_key
        if key and delivered(key):
            continue
        try:
            # A callable keyboard is resolved per recipient. This is required
            # for menus whose contents depend on the recipient (e.g. sponsor
            # button or owner-only controls). Never pass a Python function to
            # Telegram as reply_markup: it is not JSON serializable.
            reply_markup = keyboard(chat_id) if callable(keyboard) else keyboard
            await application.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            success += 1
            if key:
                mark_delivered(key)
        except Exception as e:
            failed += 1
            log.warning("Telegram send %s failed: %s", chat_id, e)

        # Telegram flood-control friendly.
        await asyncio.sleep(0.06)

    return success, failed


