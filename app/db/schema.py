"""Схема БД и версионные миграции (без удаления данных: только создание и добавление)."""
from __future__ import annotations

import logging

from app.db.core import Database

log = logging.getLogger(__name__)

TABLES = [
    "meta", "settings", "groups", "users", "lessons", "teachers", "ratings", "homework",
    "hw_done", "head_requests", "chats", "audit", "notif_log", "stopwords", "aliases", "snapshots",
    "staff", "units", "pending_questions", "support_messages", "support_tickets", "scheduled_deletions",
    "pinned_messages",
]
# таблицы с автоинкрементным id (нужны для сброса последовательностей в PostgreSQL)
SERIAL_TABLES = ["groups", "lessons", "teachers", "homework", "head_requests", "audit", "snapshots", "staff", "units",
                 "pending_questions", "support_messages", "support_tickets", "scheduled_deletions", "pinned_messages"]

_V1 = [
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS groups (id {PK}, name TEXT NOT NULL, norm TEXT NOT NULL UNIQUE, created_at BIGINT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY, username TEXT, tg_name TEXT, group_id BIGINT, fio TEXT,
        fio_status TEXT NOT NULL DEFAULT 'none', role TEXT NOT NULL DEFAULT 'student',
        admin_perms TEXT NOT NULL DEFAULT '', head_blocked INTEGER NOT NULL DEFAULT 0,
        banned INTEGER NOT NULL DEFAULT 0, bot_blocked INTEGER NOT NULL DEFAULT 0, subgroup INTEGER,
        n_evening INTEGER NOT NULL DEFAULT 1, n_evening_time TEXT NOT NULL DEFAULT '20:00',
        n_before INTEGER NOT NULL DEFAULT 0, n_changes INTEGER NOT NULL DEFAULT 1,
        created_at BIGINT NOT NULL, last_seen BIGINT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_users_group ON users (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)",
    """CREATE TABLE IF NOT EXISTS lessons (
        id {PK}, group_id BIGINT NOT NULL, day TEXT NOT NULL, num INTEGER NOT NULL,
        start_t TEXT NOT NULL, end_t TEXT NOT NULL, subject TEXT NOT NULL,
        teacher TEXT NOT NULL DEFAULT '', room TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '',
        subgroup INTEGER, manual INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS ix_lessons_gd ON lessons (group_id, day)",
    "CREATE TABLE IF NOT EXISTS teachers (id {PK}, name TEXT NOT NULL, norm TEXT NOT NULL UNIQUE, hidden INTEGER NOT NULL DEFAULT 0)",
    """CREATE TABLE IF NOT EXISTS ratings (
        user_id BIGINT NOT NULL, teacher_id BIGINT NOT NULL, stars INTEGER NOT NULL, updated_at BIGINT NOT NULL,
        PRIMARY KEY (user_id, teacher_id))""",
    """CREATE TABLE IF NOT EXISTS homework (
        id {PK}, group_id BIGINT NOT NULL, subject TEXT NOT NULL, lesson_day TEXT, text TEXT NOT NULL,
        due_day TEXT, author_id BIGINT NOT NULL, status TEXT NOT NULL, created_at BIGINT NOT NULL, decided_by BIGINT)""",
    "CREATE INDEX IF NOT EXISTS ix_hw_group ON homework (group_id, status)",
    "CREATE TABLE IF NOT EXISTS hw_done (user_id BIGINT NOT NULL, hw_id BIGINT NOT NULL, PRIMARY KEY (user_id, hw_id))",
    """CREATE TABLE IF NOT EXISTS head_requests (
        id {PK}, user_id BIGINT NOT NULL, group_id BIGINT, status TEXT NOT NULL, created_at BIGINT NOT NULL, decided_by BIGINT)""",
    """CREATE TABLE IF NOT EXISTS chats (
        chat_id BIGINT PRIMARY KEY, title TEXT, group_id BIGINT, smart_mode TEXT NOT NULL DEFAULT 'mention',
        autodelete_min INTEGER NOT NULL DEFAULT 5, evening_on INTEGER NOT NULL DEFAULT 0,
        evening_time TEXT NOT NULL DEFAULT '20:00', added_by BIGINT, active INTEGER NOT NULL DEFAULT 1)""",
    "CREATE TABLE IF NOT EXISTS audit (id {PK}, ts BIGINT NOT NULL, actor BIGINT, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS notif_log (k TEXT PRIMARY KEY, ts BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS stopwords (word TEXT PRIMARY KEY, kind TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, subject TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS fsm (user_id BIGINT PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', ts BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS snapshots (id {PK}, ts BIGINT NOT NULL, source TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL)",
]

_V2 = [
    "CREATE TABLE IF NOT EXISTS staff (id {PK}, name TEXT NOT NULL, surname TEXT NOT NULL, initials TEXT NOT NULL DEFAULT '', "
    "unit TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', updated_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_staff_surname ON staff (surname)",
    "CREATE TABLE IF NOT EXISTS units (id {PK}, name TEXT NOT NULL, norm TEXT NOT NULL UNIQUE, room TEXT NOT NULL DEFAULT '', "
    "url TEXT NOT NULL DEFAULT '', updated_at BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS pending_questions (id {PK}, chat_id BIGINT NOT NULL, message_id BIGINT NOT NULL, "
    "user_id BIGINT NOT NULL, text TEXT NOT NULL, intent TEXT NOT NULL, created_at BIGINT NOT NULL, due_at BIGINT NOT NULL, "
    "status TEXT NOT NULL DEFAULT 'wait')",
    "CREATE INDEX IF NOT EXISTS ix_pq_status ON pending_questions (status, due_at)",
    "ALTER TABLE chats ADD COLUMN wait_min INTEGER NOT NULL DEFAULT 60",
]

_V3 = ["ALTER TABLE homework ADD COLUMN media_file_id TEXT", "ALTER TABLE homework ADD COLUMN media_type TEXT", "ALTER TABLE homework ADD COLUMN media_name TEXT"]
_V4 = [
    """CREATE TABLE IF NOT EXISTS support_messages (
        id {PK}, user_id BIGINT NOT NULL, sender_role TEXT NOT NULL,
        text TEXT NOT NULL, created_at BIGINT NOT NULL, seen INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS ix_support_user ON support_messages (user_id, id)",
]
_V5 = ["ALTER TABLE users ADD COLUMN n_enabled INTEGER NOT NULL DEFAULT 1"]
_V6 = ["ALTER TABLE users ADD COLUMN fio_submitted_at BIGINT"]
_V7 = ["ALTER TABLE users ADD COLUMN private_started INTEGER NOT NULL DEFAULT 0", "UPDATE users SET private_started = 1"]
_V8 = [
    "ALTER TABLE support_messages ADD COLUMN ticket_id BIGINT",
    "CREATE TABLE IF NOT EXISTS support_tickets (id {PK}, user_id BIGINT NOT NULL, created_at BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'open')",
    "CREATE INDEX IF NOT EXISTS ix_support_ticket_user ON support_tickets (user_id, id)",
    "INSERT INTO support_tickets (user_id, created_at, status) SELECT user_id, MIN(created_at), 'open' FROM support_messages GROUP BY user_id",
    "UPDATE support_messages SET ticket_id = (SELECT MIN(id) FROM support_tickets WHERE support_tickets.user_id = support_messages.user_id) WHERE ticket_id IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_support_messages_ticket ON support_messages (ticket_id, id)",
    "CREATE TABLE IF NOT EXISTS scheduled_deletions (id {PK}, chat_id BIGINT NOT NULL, message_id BIGINT NOT NULL, delete_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_scheduled_deletions_due ON scheduled_deletions (delete_at)",
]
_V9 = [
    "ALTER TABLE chats ADD COLUMN changes_on INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE chats ADD COLUMN pin_on INTEGER NOT NULL DEFAULT 1",
    "CREATE TABLE IF NOT EXISTS pinned_messages (id {PK}, chat_id BIGINT NOT NULL, message_id BIGINT NOT NULL, unpin_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_pinned_due ON pinned_messages (unpin_at)",
]
_V10 = [
    "ALTER TABLE ratings ADD COLUMN lectures INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ratings ADD COLUMN strictness INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ratings ADD COLUMN assessment INTEGER NOT NULL DEFAULT 0",
    "CREATE TABLE IF NOT EXISTS analytics_events (id {PK}, user_id BIGINT, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_analytics_event_ts ON analytics_events (event, created_at)",
    "CREATE TABLE IF NOT EXISTS calendar_exceptions (day TEXT PRIMARY KEY, kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS interface_texts (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "ALTER TABLE users ADD COLUMN n_before_custom INTEGER NOT NULL DEFAULT 0",
]
_V11 = [
    "UPDATE users SET role = 'student' WHERE role = 'head'",
    "UPDATE head_requests SET status = 'disabled' WHERE status IN ('pending', 'approved')",
]
MIGRATIONS: list[tuple[int, list[str]]] = [(1, _V1), (2, _V2), (3, _V3), (4, _V4), (5, _V5), (6, _V6), (7, _V7), (8, _V8), (9, _V9), (10, _V10), (11, _V11)]


async def migrate(db: Database) -> int:
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if db.kind == "sqlite" else "BIGSERIAL PRIMARY KEY"
    await db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    cur = await db.scalar("SELECT v FROM meta WHERE k = ?", "schema_version")
    current = int(cur) if cur is not None else 0
    for version, stmts in MIGRATIONS:
        if version <= current:
            continue
        async with db.tx() as t:
            for s in stmts:
                await t.execute(s.replace("{PK}", pk))
            await t.execute(
                "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v",
                ("schema_version", str(version)),
            )
        current = version
        log.info("Применена миграция схемы до версии %s", version)
    return current
