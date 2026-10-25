"""Доступ к данным. Все запросы совместимы и с SQLite, и с PostgreSQL."""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import time
import zlib
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Iterable

from app.db.core import Database
from app.db.schema import SERIAL_TABLES, TABLES
from app.models import LessonRec
from app.services.fio import FioContext, fio_key, surname_keys
from app.services.names import name_parts, same_person, surname_close  # noqa: F401
from app.timeutil import iso, now_ts, today as local_today

DEFAULT_SETTINGS = {
    "rating_enabled": "1",       # показывать раздел «Преподаватели»
    "hw_show_author": "1",       # показывать автора задания (Иванов И.)
    "maintenance": "0",          # режим техработ
    "fio_need_known_surname": "1",  # автоподтверждение ФИО только для фамилий из словарей/справочника/подтверждённых
    "fio_auto_delay_min": "90",  # через сколько минут автопроверка может подтвердить ФИО
    "rate_cooldown_days": "0",   # 0: студент может изменить свою оценку в любое время
    "rate_only_own": "1",        # оценивать можно только своих преподавателей
    "min_votes": "5",            # сколько оценок нужно, чтобы показать среднюю
    "parity_anchor": "",         # любая дата нечётной недели, YYYY-MM-DD
    "hw_daily_limit": "10",      # лимит заданий в сутки от одного пользователя
    "sync_enabled": "1",
    "group_require_start": "0",  # require every group-chat user to open the bot in private first
    "notify_changes": "1",       # глобальный выключатель рассылки «изменения в расписании» (личка и чаты)
}

USER_COLS = {"username", "tg_name", "group_id", "fio", "fio_status", "role", "admin_perms", "head_blocked", "banned",
             "bot_blocked", "subgroup", "n_enabled", "fio_submitted_at", "private_started", "n_evening", "n_evening_time", "n_before", "n_changes", "last_seen"}
CHAT_COLS = {"title", "group_id", "smart_mode", "autodelete_min", "evening_on", "evening_time", "added_by", "active",
             "wait_min", "changes_on", "pin_on"}

_LOOKALIKE = str.maketrans("abcehkmoptxyis", "авсенкмортхуис")


def canonical_group_name(name: str) -> str | None:
    """Нормализовать название группы, не завися от регистра и разделителей.

    Поддерживает одно- и многобуквенные коды (например, Э-22.1 и МД-22.1),
    латинские буквы-двойники и сокращённую запись подгруппы:
    «э221», «Э 22 1», «мд-221» -> каноническая форма.
    Не принимает произвольный текст, чтобы не привязывать пользователя к неверной группе.
    """
    s = (name or "").strip().lower().replace("ё", "е").translate(_LOOKALIKE).upper()
    # Между номером и подгруппой допустимы точка, дефис, пробел или отсутствие знака.
    match = re.fullmatch(r"\s*([А-Я]{1,4})\s*[-–—]?\s*(\d{2})(?:\s*[.\-–—]?\s*(\d))?\s*", s)
    if not match:
        return None
    letters, number, subgroup = match.groups()
    return f"{letters}-{number}" + (f".{subgroup}" if subgroup is not None else "")


def norm_group(name: str) -> str:
    canonical = canonical_group_name(name)
    if canonical:
        name = canonical
    s = (name or "").lower().replace("ё", "е").translate(_LOOKALIKE)
    return re.sub(r"[^0-9а-я]", "", s)


def teacher_key(name: str) -> str:
    s = (name or "").lower().replace("ё", "е").replace(".", " ")
    toks = s.split()
    i = len(toks)
    while i > 0 and len(toks[i - 1]) == 1:
        i -= 1
    if i < len(toks):
        toks = toks[:i] + ["".join(toks[i:])]
    return " ".join(toks)


def split_teachers(raw: str) -> list[str]:
    parts = re.split(r"[;,/\n]+", raw or "")
    return [" ".join(p.split()) for p in parts if p and p.strip()]


@dataclass
class ApplyResult:
    total: int = 0
    changes: dict[int, list[dict]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


class Repo:
    def __init__(self, db: Database):
        self.db = db
        self._settings: dict[str, str] = {}
        self._catalog: tuple[float, list[tuple[str, str]]] | None = None
        self._known: tuple[float, set[str]] | None = None

    # ================= настройки =================
    async def load_settings(self) -> None:
        rows = await self.db.fetchall("SELECT k, v FROM settings")
        self._settings = {r["k"]: r["v"] for r in rows}

    def setting(self, key: str) -> str:
        return self._settings.get(key, DEFAULT_SETTINGS.get(key, ""))

    def flag(self, key: str) -> bool:
        return self.setting(key) == "1"

    def int_setting(self, key: str) -> int:
        try:
            return int(self.setting(key))
        except ValueError:
            return int(DEFAULT_SETTINGS.get(key, "0") or 0)

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", key, value)
        self._settings[key] = value

    async def get_meta(self, key: str) -> str | None:
        return await self.db.scalar("SELECT v FROM meta WHERE k = ?", key)

    async def set_meta(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v", key, value)

    # ================= пользователи =================
    async def get_user(self, uid: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM users WHERE id = ?", uid)

    async def touch_user(self, uid: int, username: str | None, name: str | None) -> dict:
        now = now_ts()
        u = await self.get_user(uid)
        username = (username or "").lstrip("@") or None
        name = name or None
        if u is None:
            await self.db.execute(
                "INSERT INTO users (id, username, tg_name, created_at, last_seen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO NOTHING", uid, username, name, now, now)
            return await self.get_user(uid)  # type: ignore[return-value]
        if u["username"] != username or u["tg_name"] != name:
            await self.db.execute("UPDATE users SET username = ?, tg_name = ?, last_seen = ? WHERE id = ?",
                                  username, name, now, uid)
            u.update(username=username, tg_name=name, last_seen=now)
        elif now - int(u["last_seen"]) > 600:
            await self.db.execute("UPDATE users SET last_seen = ? WHERE id = ?", now, uid, volatile=True)
            u["last_seen"] = now
        return u

    async def ensure_user(self, uid: int) -> dict:
        u = await self.get_user(uid)
        if u:
            return u
        now = now_ts()
        await self.db.execute("INSERT INTO users (id, created_at, last_seen) VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING",
                              uid, now, now)
        return await self.get_user(uid)  # type: ignore[return-value]

    async def update_user(self, uid: int, **fields: Any) -> None:
        bad = set(fields) - USER_COLS
        if bad or not fields:
            raise ValueError(f"недопустимые поля: {bad}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(f"UPDATE users SET {sets} WHERE id = ?", *fields.values(), uid,
                              volatile=set(fields) <= {"last_seen"})

    async def find_user(self, query: str) -> dict | None:
        q = (query or "").strip()
        if not q:
            return None
        if re.fullmatch(r"\d{4,15}", q):
            return await self.get_user(int(q))
        if q.startswith("@") or re.fullmatch(r"[A-Za-z0-9_]{4,32}", q):
            return await self.db.fetchone("SELECT * FROM users WHERE LOWER(username) = ?", q.lstrip("@").lower())
        return None

    async def search_users_by_fio(self, query: str, limit: int = 8) -> list[dict]:
        q = query.lower().replace("ё", "е").strip()
        if len(q) < 2:
            return []
        rows = await self.db.fetchall("SELECT * FROM users WHERE fio IS NOT NULL")
        out = [r for r in rows if q in r["fio"].lower().replace("ё", "е")]
        return out[:limit]

    async def users_with_role(self, role: str) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM users WHERE role = ? ORDER BY id", role)

    async def group_users(self, gid: int) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM users WHERE group_id = ? AND banned = 0", gid)

    async def heads_of_group(self, gid: int) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM users WHERE group_id = ? AND role = 'head'", gid)

    async def pending_fio(self, limit: int = 10, offset: int = 0) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM users WHERE fio_status = 'pending' ORDER BY created_at LIMIT ? OFFSET ?", limit, offset)

    async def count(self, table: str, where: str = "1=1", *params: Any) -> int:
        if table not in TABLES:
            raise ValueError(table)
        return int(await self.db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {where}", *params) or 0)

    async def stats(self) -> dict:
        now = now_ts()
        return {
            "users": await self.count("users"),
            "verified": await self.count("users", "fio_status = 'verified'"),
            "pending": await self.count("users", "fio_status = 'pending'"),
            "banned": await self.count("users", "banned = 1"),
            "dau": await self.count("users", "last_seen >= ?", now - 86400),
            "wau": await self.count("users", "last_seen >= ?", now - 7 * 86400),
            "heads": await self.count("users", "role = 'head'"),
            "admins": await self.count("users", "role = 'admin'"),
            "groups": await self.count("groups"),
            "lessons": await self.count("lessons"),
            "hw": await self.count("homework", "status = 'approved'"),
            "hw_pending": await self.count("homework", "status = 'pending'"),
            "ratings": await self.count("ratings"),
            "teachers": await self.count("teachers"),
        }

    # ================= группы =================
    async def get_group(self, gid: int | None) -> dict | None:
        if gid is None:
            return None
        return await self.db.fetchone("SELECT * FROM groups WHERE id = ?", gid)

    async def get_or_create_group(self, name: str) -> dict:
        clean = canonical_group_name(name) or " ".join(name.split()).upper()
        key = norm_group(clean)
        if not key:
            raise ValueError("пустое название группы")
        g = await self.db.fetchone("SELECT * FROM groups WHERE norm = ?", key)
        if g:
            if canonical_group_name(name) and g["name"] != clean:
                await self.db.execute("UPDATE groups SET name = ? WHERE id = ?", clean, g["id"])
                g = await self.db.fetchone("SELECT * FROM groups WHERE id = ?", g["id"])
            return g
        await self.db.execute("INSERT INTO groups (name, norm, created_at) VALUES (?, ?, ?) ON CONFLICT (norm) DO NOTHING",
                              clean, key, now_ts())
        return await self.db.fetchone("SELECT * FROM groups WHERE norm = ?", key)  # type: ignore[return-value]

    async def all_groups(self) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM groups ORDER BY name")

    async def search_groups(self, query: str, limit: int = 6) -> list[dict]:
        q = norm_group(query)
        if not q:
            return []
        groups = await self.all_groups()
        exact = [g for g in groups if g["norm"] == q]
        if exact:
            return exact
        sub = [g for g in groups if q in g["norm"]]
        if sub:
            return sub[:limit]
        scored = sorted(((difflib.SequenceMatcher(None, q, g["norm"]).ratio(), g) for g in groups),
                        key=lambda x: -x[0])
        return [g for s, g in scored if s >= 0.72][:limit]

    # ================= расписание =================
    def _invalidate_catalog(self) -> None:
        self._catalog = None
        self._known = None

    async def apply_lessons(self, recs: Iterable[LessonRec], manual: bool, guard: bool = True) -> ApplyResult:
        """Заменяет занятия групп на диапазоне дат из recs. Возвращает изменения для уведомлений."""
        by_group: dict[str, list[LessonRec]] = {}
        for r in recs:
            by_group.setdefault(r.group, []).append(r)
        result = ApplyResult()
        if not by_group:
            return result
        mflag = 1 if manual else 0
        today_iso = iso(local_today())
        async with self.db.tx() as t:
            for gname, items in by_group.items():
                clean = canonical_group_name(gname) or " ".join(gname.split()).upper()
                key = norm_group(clean)
                if not key:
                    continue
                g = await t.fetchone("SELECT * FROM groups WHERE norm = ?", (key,))
                if not g:
                    gid = await t.insert("INSERT INTO groups (name, norm, created_at) VALUES (?, ?, ?)",
                                         (clean, key, now_ts()))
                else:
                    gid = g["id"]
                    if canonical_group_name(gname) and g["name"] != clean:
                        await t.execute("UPDATE groups SET name = ? WHERE id = ?", (clean, gid))
                d1 = min(r.day for r in items)
                d2 = max(r.day for r in items)
                old = await t.fetchall(
                    "SELECT * FROM lessons WHERE group_id = ? AND day >= ? AND day <= ? AND manual = ?",
                    (gid, d1, d2, mflag))
                if guard and len(old) >= 10 and len(items) < 0.3 * len(old):
                    result.skipped.append(clean)
                    continue
                old_keys = {(o["day"], o["num"], o["start_t"], o["end_t"], o["subject"], o["teacher"], o["room"],
                             o["kind"], o["subgroup"] or 0) for o in old}
                new_keys = {r.key() for r in items}
                await t.execute("DELETE FROM lessons WHERE group_id = ? AND day >= ? AND day <= ? AND manual = ?",
                                (gid, d1, d2, mflag))
                await t.executemany(
                    "INSERT INTO lessons (group_id, day, num, start_t, end_t, subject, teacher, room, kind, subgroup, manual) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(gid, r.day, r.num, r.start, r.end, r.subject, r.teacher, r.room, r.kind, r.subgroup, mflag)
                     for r in items])
                result.total += len(items)
                for r in items:
                    for tname in split_teachers(r.teacher):
                        k = teacher_key(tname)
                        if k:
                            await t.execute("INSERT INTO teachers (name, norm) VALUES (?, ?) ON CONFLICT (norm) DO NOTHING",
                                            (tname, k))
                if old:
                    changes: list[dict] = []
                    for day in sorted({k[0] for k in old_keys | new_keys}):
                        if day < today_iso:
                            continue
                        rem = sorted(k for k in old_keys - new_keys if k[0] == day)
                        add = sorted(k for k in new_keys - old_keys if k[0] == day)
                        if rem or add:
                            changes.append({"day": day, "removed": rem, "added": add})
                    if changes:
                        result.changes[gid] = changes
        self._invalidate_catalog()
        return result

    async def lessons_day(self, gid: int, day: str, subgroup: int | None = None) -> list[dict]:
        rows = await self.db.fetchall("SELECT * FROM lessons WHERE group_id = ? AND day = ? ORDER BY start_t, num, id",
                                      gid, day)
        return [r for r in rows if subgroup is None or r["subgroup"] is None or r["subgroup"] == subgroup]

    async def lessons_range(self, gid: int, d1: str, d2: str, subgroup: int | None = None) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM lessons WHERE group_id = ? AND day >= ? AND day <= ? ORDER BY day, start_t, num, id",
            gid, d1, d2)
        return [r for r in rows if subgroup is None or r["subgroup"] is None or r["subgroup"] == subgroup]

    async def days_with_lessons(self, gid: int, d1: str, d2: str) -> set[str]:
        rows = await self.db.fetchall(
            "SELECT DISTINCT day FROM lessons WHERE group_id = ? AND day >= ? AND day <= ?", gid, d1, d2)
        return {r["day"] for r in rows}

    async def get_lesson(self, lid: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM lessons WHERE id = ?", lid)

    async def add_manual_lesson(self, gid: int, rec: LessonRec) -> int:
        lid = await self.db.insert(
            "INSERT INTO lessons (group_id, day, num, start_t, end_t, subject, teacher, room, kind, subgroup, manual) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            gid, rec.day, rec.num, rec.start, rec.end, rec.subject, rec.teacher, rec.room, rec.kind, rec.subgroup)
        for tname in split_teachers(rec.teacher):
            k = teacher_key(tname)
            if k:
                await self.db.execute("INSERT INTO teachers (name, norm) VALUES (?, ?) ON CONFLICT (norm) DO NOTHING",
                                      tname, k)
        self._invalidate_catalog()
        return lid

    async def delete_manual_lesson(self, lid: int) -> bool:
        n = await self.db.execute("DELETE FROM lessons WHERE id = ? AND manual = 1", lid)
        self._invalidate_catalog()
        return n > 0

    async def manual_lessons(self, gid: int, from_day: str, limit: int = 10) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM lessons WHERE group_id = ? AND manual = 1 AND day >= ? ORDER BY day, start_t LIMIT ?",
            gid, from_day, limit)

    async def upcoming_subjects(self, gid: int, d1: str, d2: str) -> list[str]:
        rows = await self.db.fetchall(
            "SELECT DISTINCT subject FROM lessons WHERE group_id = ? AND day >= ? AND day <= ? ORDER BY subject",
            gid, d1, d2)
        return [r["subject"] for r in rows]

    async def subject_catalog(self) -> list[tuple[str, str]]:
        if self._catalog and time.time() - self._catalog[0] < 120:
            return self._catalog[1]
        subj = await self.db.fetchall("SELECT DISTINCT subject FROM lessons")
        al = await self.db.fetchall("SELECT alias, subject FROM aliases")
        cat: dict[str, str] = {s["subject"].lower(): s["subject"] for s in subj}
        acr: dict[str, str | None] = {}
        for s_ in subj:  # аббревиатуры: «Маркшейдерско-геодезические приборы» -> «мгп»
            words = [w for w in re.split(r"[\s\-–—,.()/]+", s_["subject"].lower().replace("ё", "е"))
                     if w and w not in ("и", "в", "на", "по", "для", "с", "к", "о", "об", "а", "от", "из")]
            short = "".join(w[0] for w in words)
            if len(words) >= 3 and len(short) >= 3:
                acr[short] = None if short in acr and acr[short] != s_["subject"] else s_["subject"]
        for short, subject in acr.items():
            if subject and short not in cat:
                cat[short] = subject
        for a in al:
            cat[a["alias"].lower()] = a["subject"]
        out = list(cat.items())
        self._catalog = (time.time(), out)
        return out

    async def add_alias(self, alias: str, subject: str) -> None:
        await self.db.execute(
            "INSERT INTO aliases (alias, subject) VALUES (?, ?) ON CONFLICT (alias) DO UPDATE SET subject = excluded.subject",
            alias.lower().strip(), subject.strip())
        self._invalidate_catalog()

    async def list_aliases(self) -> list[dict]:
        return await self.db.fetchall("SELECT alias, subject FROM aliases ORDER BY alias")

    async def del_alias(self, alias: str) -> None:
        await self.db.execute("DELETE FROM aliases WHERE alias = ?", alias.lower().strip())
        self._invalidate_catalog()

    async def upcoming_kind(self, gid: int, from_day: str, kinds: tuple[str, ...], limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM lessons WHERE group_id = ? AND day >= ? ORDER BY day, start_t", gid, from_day)
        out = [r for r in rows if any(k in r["kind"].lower().replace("ё", "е") for k in kinds)]
        return out[:limit]

    async def next_lessons(self, gid: int, from_day: str, days: int = 21, subgroup: int | None = None) -> list[dict]:
        d2 = iso(date.fromisoformat(from_day) + timedelta(days=days))
        return await self.lessons_range(gid, from_day, d2, subgroup)

    # ================= снимки =================
    async def save_snapshot(self, source: str, recs: list[LessonRec]) -> bool:
        data = sorted([[r.group, *r.key()] for r in recs])
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        h = hashlib.sha1(raw.encode()).hexdigest()
        last = await self.db.fetchone("SELECT hash FROM snapshots ORDER BY id DESC LIMIT 1")
        if last and last["hash"] == h:
            return False
        payload = base64.b64encode(zlib.compress(raw.encode(), 6)).decode()
        await self.db.insert("INSERT INTO snapshots (ts, source, hash, payload) VALUES (?, ?, ?, ?)",
                             now_ts(), source, h, payload)
        await self.db.execute(
            "DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 5)")
        return True

    async def list_snapshots(self) -> list[dict]:
        return await self.db.fetchall("SELECT id, ts, source, hash FROM snapshots ORDER BY id DESC")

    async def load_snapshot(self, sid: int) -> list[LessonRec] | None:
        row = await self.db.fetchone("SELECT payload FROM snapshots WHERE id = ?", sid)
        if not row:
            return None
        data = json.loads(zlib.decompress(base64.b64decode(row["payload"])).decode())
        out = []
        for g, day, num, start, end, subject, teacher, room, kind, sub in data:
            out.append(LessonRec(g, day, num, start, end, subject, teacher, room, kind, sub or None))
        return out

    # ================= преподаватели и оценки =================
    async def teacher_ids_for_group(self, gid: int) -> set[int]:
        rows = await self.db.fetchall("SELECT DISTINCT teacher FROM lessons WHERE group_id = ? AND teacher <> ''", gid)
        keys = {teacher_key(n) for r in rows for n in split_teachers(r["teacher"])}
        if not keys:
            return set()
        allt = await self.db.fetchall("SELECT id, norm FROM teachers")
        return {t["id"] for t in allt if t["norm"] in keys}

    async def list_teachers(self, offset: int, limit: int, ids: set[int] | None = None) -> tuple[list[dict], int]:
        where, params = "t.hidden = 0", []
        if ids is not None:
            if not ids:
                return [], 0
            where += " AND t.id IN (" + ",".join("?" * len(ids)) + ")"
            params = sorted(ids)
        total = int(await self.db.scalar(f"SELECT COUNT(*) FROM teachers t WHERE {where}", *params) or 0)
        rows = await self.db.fetchall(
            "SELECT t.id AS id, t.name AS name, COUNT(CASE WHEN r.stars > 0 THEN r.user_id END) AS cnt, AVG(NULLIF(r.stars, 0)) AS avg "
            f"FROM teachers t LEFT JOIN ratings r ON r.teacher_id = t.id WHERE {where} "
            "GROUP BY t.id, t.name ORDER BY t.name LIMIT ? OFFSET ?", *params, limit, offset)
        for r in rows:
            r["avg"] = float(r["avg"]) if r["avg"] is not None else None
        return rows, total

    async def get_teacher(self, tid: int) -> dict | None:
        r = await self.db.fetchone(
            "SELECT t.id AS id, t.name AS name, t.norm AS norm, t.hidden AS hidden, COUNT(CASE WHEN r.stars > 0 THEN r.user_id END) AS cnt, AVG(NULLIF(r.stars, 0)) AS avg "
            "FROM teachers t LEFT JOIN ratings r ON r.teacher_id = t.id WHERE t.id = ? "
            "GROUP BY t.id, t.name, t.norm, t.hidden", tid)
        if r and r["avg"] is not None:
            r["avg"] = float(r["avg"])
        return r

    async def teacher_subjects(self, tnorm: str, limit: int = 6) -> list[str]:
        rows = await self.db.fetchall("SELECT DISTINCT subject, teacher FROM lessons WHERE teacher <> ''")
        subs = sorted({r["subject"] for r in rows if tnorm in {teacher_key(n) for n in split_teachers(r["teacher"])}})
        return subs[:limit]

    async def teachers_by_subject(self, subject: str) -> list[dict]:
        rows = await self.db.fetchall("SELECT DISTINCT teacher FROM lessons WHERE subject = ? AND teacher <> ''", subject)
        keys = {teacher_key(n) for r in rows for n in split_teachers(r["teacher"])}
        if not keys:
            return []
        allt = await self.db.fetchall("SELECT id, name, norm FROM teachers WHERE hidden = 0 ORDER BY name")
        return [t for t in allt if t["norm"] in keys]

    async def search_teachers(self, query: str, limit: int = 8) -> list[dict]:
        q = teacher_key(query)
        if len(q) < 2:
            return []
        allt = await self.db.fetchall("SELECT id, name, norm FROM teachers WHERE hidden = 0 ORDER BY name")
        hits = [t for t in allt if q in t["norm"]]
        if not hits:
            first = q.split(" ")[0]
            scored = sorted(((difflib.SequenceMatcher(None, first, t["norm"].split(" ")[0]).ratio(), t) for t in allt),
                            key=lambda x: -x[0])
            hits = [t for s, t in scored if s >= 0.8]
        return hits[:limit]

    async def rate_teacher(self, uid: int, tid: int, stars: int, cooldown_days: int) -> tuple[str, int]:
        """('ok'|'same'|'cooldown', осталось_дней)."""
        if not 1 <= stars <= 5:
            raise ValueError("stars")
        now = now_ts()
        row = await self.db.fetchone("SELECT stars, updated_at FROM ratings WHERE user_id = ? AND teacher_id = ?", uid, tid)
        if row:
            if row["stars"] == stars:
                return "same", 0
            # Одна запись на пару пользователь/преподаватель (PRIMARY KEY) исключает
            # дополнительные голоса; повторная отправка обновляет его собственную оценку.
            # Ограничение по времени намеренно не применяется: студент может исправить ошибку.
        await self.db.execute(
            "INSERT INTO ratings (user_id, teacher_id, stars, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_id, teacher_id) DO UPDATE SET stars = excluded.stars, updated_at = excluded.updated_at",
            uid, tid, stars, now)
        return "ok", 0

    async def my_rating(self, uid: int, tid: int) -> int | None:
        v = await self.db.scalar("SELECT stars FROM ratings WHERE user_id = ? AND teacher_id = ?", uid, tid)
        return int(v) if v is not None else None

    async def user_ratings(self, uid: int) -> list[dict]:
        return await self.db.fetchall(
            "SELECT t.name AS name, r.stars AS stars, r.updated_at AS updated_at FROM ratings r "
            "JOIN teachers t ON t.id = r.teacher_id WHERE r.user_id = ? ORDER BY r.updated_at DESC", uid)

    async def set_teacher_hidden(self, tid: int, hidden: bool) -> None:
        await self.db.execute("UPDATE teachers SET hidden = ? WHERE id = ?", 1 if hidden else 0, tid)

    async def reset_ratings(self, tid: int) -> int:
        return await self.db.execute("DELETE FROM ratings WHERE teacher_id = ?", tid)

    # ================= задания =================
    async def add_hw(self, gid: int, subject: str, lesson_day: str | None, text: str, due_day: str | None,
                     author_id: int, status: str) -> int:
        return await self.db.insert(
            "INSERT INTO homework (group_id, subject, lesson_day, text, due_day, author_id, status, created_at, media_file_id, media_type, media_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)", gid, subject, lesson_day, text, due_day, author_id, status, now_ts())

    async def update_hw(self, hid: int, *, text: str | None = None, media_file_id: str | None = None,
                        media_type: str | None = None, media_name: str | None = None) -> None:
        await self.db.execute("UPDATE homework SET text = COALESCE(?, text), media_file_id = COALESCE(?, media_file_id), media_type = COALESCE(?, media_type), media_name = COALESCE(?, media_name) WHERE id = ?", text, media_file_id, media_type, media_name, hid)

    async def hw_today_count(self, uid: int) -> int:
        return await self.count("homework", "author_id = ? AND created_at >= ?", uid, now_ts() - 86400)

    async def get_hw(self, hid: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM homework WHERE id = ?", hid)

    async def list_hw(self, gid: int, today_iso: str, offset: int, limit: int) -> tuple[list[dict], int]:
        cond = "group_id = ? AND status = 'approved' AND (due_day IS NULL OR due_day >= ?)"
        total = int(await self.db.scalar(f"SELECT COUNT(*) FROM homework WHERE {cond}", gid, today_iso) or 0)
        rows = await self.db.fetchall(
            f"SELECT * FROM homework WHERE {cond} ORDER BY CASE WHEN due_day IS NULL THEN 1 ELSE 0 END, due_day, id "
            "LIMIT ? OFFSET ?", gid, today_iso, limit, offset)
        return rows, total

    async def hw_for_day(self, gid: int, day: str) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM homework WHERE group_id = ? AND status = 'approved' AND lesson_day = ? ORDER BY id", gid, day)

    async def hw_counts_for_day(self, gid: int, day: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for h in await self.hw_for_day(gid, day):
            out[h["subject"]] = out.get(h["subject"], 0) + 1
        return out

    async def hw_for_subject(self, gid: int, subject: str, today_iso: str, limit: int = 5) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM homework WHERE group_id = ? AND subject = ? AND status = 'approved' "
            "AND (due_day IS NULL OR due_day >= ?) ORDER BY id DESC LIMIT ?", gid, subject, today_iso, limit)

    async def pending_hw(self, gid: int | None, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        if gid is None:
            cond, params = "status = 'pending'", []
        else:
            cond, params = "status = 'pending' AND group_id = ?", [gid]
        total = int(await self.db.scalar(f"SELECT COUNT(*) FROM homework WHERE {cond}", *params) or 0)
        rows = await self.db.fetchall(f"SELECT * FROM homework WHERE {cond} ORDER BY id LIMIT ? OFFSET ?",
                                      *params, limit, offset)
        return rows, total

    async def set_hw_status(self, hid: int, status: str, by: int | None) -> None:
        await self.db.execute("UPDATE homework SET status = ?, decided_by = ? WHERE id = ?", status, by, hid)

    async def toggle_hw_done(self, uid: int, hid: int) -> bool:
        n = await self.db.execute("DELETE FROM hw_done WHERE user_id = ? AND hw_id = ?", uid, hid)
        if n:
            return False
        await self.db.execute("INSERT INTO hw_done (user_id, hw_id) VALUES (?, ?) ON CONFLICT DO NOTHING", uid, hid)
        return True

    async def hw_done_set(self, uid: int, hids: list[int]) -> set[int]:
        if not hids:
            return set()
        rows = await self.db.fetchall(
            "SELECT hw_id FROM hw_done WHERE user_id = ? AND hw_id IN (" + ",".join("?" * len(hids)) + ")", uid, *hids)
        return {r["hw_id"] for r in rows}

    # ================= заявки старост =================
    async def request_for_user(self, uid: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM head_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1", uid)

    async def create_request(self, uid: int, gid: int | None) -> int:
        return await self.db.insert(
            "INSERT INTO head_requests (user_id, group_id, status, created_at) VALUES (?, ?, 'pending', ?)",
            uid, gid, now_ts())

    async def get_request(self, rid: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM head_requests WHERE id = ?", rid)

    async def pending_requests(self, limit: int = 10) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM head_requests WHERE status = 'pending' ORDER BY id LIMIT ?", limit)

    async def decide_request(self, rid: int, status: str, by: int | None) -> bool:
        n = await self.db.execute(
            "UPDATE head_requests SET status = ?, decided_by = ? WHERE id = ? AND status = 'pending'", status, by, rid)
        return n > 0

    # ================= чаты =================
    async def get_chat(self, chat_id: int) -> dict | None:
        return await self.db.fetchone("SELECT * FROM chats WHERE chat_id = ?", chat_id)

    async def upsert_chat(self, chat_id: int, title: str | None, group_id: int | None, added_by: int | None) -> dict:
        existing = await self.get_chat(chat_id)
        if existing is None:
            await self.db.execute(
                "INSERT INTO chats (chat_id, title, group_id, added_by, active) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT (chat_id) DO NOTHING", chat_id, title, group_id, added_by)
        else:
            await self.db.execute("UPDATE chats SET title = ?, active = 1 WHERE chat_id = ?", title, chat_id)
            if group_id is not None and existing["group_id"] is None:
                await self.db.execute("UPDATE chats SET group_id = ?, added_by = ? WHERE chat_id = ?",
                                      group_id, added_by, chat_id)
        return await self.get_chat(chat_id)  # type: ignore[return-value]

    async def update_chat(self, chat_id: int, **fields: Any) -> None:
        bad = set(fields) - CHAT_COLS
        if bad or not fields:
            raise ValueError(f"недопустимые поля: {bad}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(f"UPDATE chats SET {sets} WHERE chat_id = ?", *fields.values(), chat_id)

    async def chats_for_group(self, gid: int) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM chats WHERE group_id = ? AND active = 1", gid)

    async def evening_chats(self) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM chats WHERE active = 1 AND evening_on = 1 AND group_id IS NOT NULL")

    # ================= закрепы в чатах =================
    async def add_pin(self, chat_id: int, message_id: int, unpin_at: int) -> None:
        await self.db.execute("INSERT INTO pinned_messages (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                              chat_id, message_id, unpin_at)

    async def due_pins(self, now: int) -> list[dict]:
        return await self.db.fetchall(
            "SELECT id, chat_id, message_id FROM pinned_messages WHERE unpin_at <= ? ORDER BY id LIMIT 50", now)

    async def delete_pin(self, pin_id: int) -> None:
        await self.db.execute("DELETE FROM pinned_messages WHERE id = ?", pin_id)

    # ================= журнал и служебное =================
    async def audit(self, actor: int | None, action: str, details: str = "") -> None:
        await self.db.execute("INSERT INTO audit (ts, actor, action, details) VALUES (?, ?, ?, ?)",
                              now_ts(), actor, action, details[:500], volatile=True)

    async def list_audit(self, limit: int = 15) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM audit ORDER BY id DESC LIMIT ?", limit)

    async def first_time(self, key: str) -> bool:
        n = await self.db.execute("INSERT INTO notif_log (k, ts) VALUES (?, ?) ON CONFLICT (k) DO NOTHING",
                                  key, now_ts(), volatile=True)
        return n > 0

    async def cleanup_notif_log(self) -> None:
        await self.db.execute("DELETE FROM notif_log WHERE ts < ?", now_ts() - 5 * 86400, volatile=True)

    # ================= справочник преподавателей вуза =================
    async def replace_directory(self, staff: list[dict], units: list[dict]) -> None:
        """Полностью заменяет справочник (staff: name, unit, url; units: name, room, url)."""
        now = now_ts()
        async with self.db.tx() as t:
            await t.execute("DELETE FROM staff")
            await t.execute("DELETE FROM units")
            seen: set[str] = set()
            for u in units:
                key = " ".join(u["name"].lower().replace("ё", "е").split())
                if not key or key in seen:
                    continue
                seen.add(key)
                await t.execute("INSERT INTO units (name, norm, room, url, updated_at) VALUES (?, ?, ?, ?, ?)",
                                (" ".join(u["name"].split()), key, u.get("room", ""), u.get("url", ""), now))
            rows = []
            for s_ in staff:
                surname, initials = name_parts(s_["name"])
                if surname:
                    rows.append((" ".join(s_["name"].split()), surname, initials, s_.get("unit", ""), s_.get("url", ""), now))
            if rows:
                await t.executemany("INSERT INTO staff (name, surname, initials, unit, url, updated_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
        self._known = None

    async def find_staff(self, surname: str, initials: str = "") -> list[dict]:
        rows = await self.db.fetchall("SELECT * FROM staff ORDER BY name")
        q = (surname.lower().replace("ё", "е"), initials)
        return [r for r in rows if surname_close(q[0], r["surname"]) and same_person((r["surname"], r["initials"]), (r["surname"], q[1]))]

    async def get_unit(self, name: str) -> dict | None:
        key = " ".join((name or "").lower().replace("ё", "е").split())
        return await self.db.fetchone("SELECT * FROM units WHERE norm = ?", key)

    async def directory_counts(self) -> tuple[int, int, int]:
        n_staff = await self.count("staff")
        n_units = await self.count("units")
        n_rooms = await self.count("units", "room <> ''")
        return n_staff, n_units, n_rooms

    async def known_surnames(self) -> set[str]:
        if getattr(self, "_known", None) and time.time() - self._known[0] < 300:
            return self._known[1]
        rows = await self.db.fetchall("SELECT DISTINCT surname FROM staff")
        names = {r["surname"] for r in rows}
        for r in await self.db.fetchall("SELECT norm FROM teachers"):
            names.add(r["norm"].split(" ")[0])
        self._known = (time.time(), names)
        return names

    async def fio_context(self) -> FioContext:
        """Данные для проверки ФИО: реальные фамилии (справочник, расписание, подтверждённые студенты) и преподаватели."""
        cached = getattr(self, "_fio_ctx", None)
        if cached and time.time() - cached[0] < 120:
            base = cached[1]
        else:
            known: set[str] = set()
            for sn in await self.known_surnames():
                known |= surname_keys(sn)
            for r in await self.db.fetchall("SELECT fio FROM users WHERE fio_status = 'verified' AND fio IS NOT NULL"):
                words = (r["fio"] or "").split()
                if words:
                    known |= surname_keys(words[0])
            pairs: set[tuple[str, str]] = set()
            for r in await self.db.fetchall("SELECT surname, initials FROM staff"):
                pairs.add(((r["surname"] or "").lower().replace("ё", "е"),
                           (r["initials"] or "").lower().replace("ё", "е").replace(".", "").replace(" ", "")))
            for r in await self.db.fetchall("SELECT norm FROM teachers"):
                toks = (r["norm"] or "").split(" ")
                if toks and toks[0]:
                    pairs.add((toks[0], "".join(toks[1:])))
            base = FioContext(frozenset(known), frozenset(pairs))
            self._fio_ctx = (time.time(), base)
        return replace(base, require_known_surname=self.flag("fio_need_known_surname"))

    async def fio_duplicate(self, group_id: int | None, fio: str, uid: int) -> bool:
        """В той же группе уже есть другой аккаунт с таким же ФИО (без учёта регистра, «ё» и рода фамилии)."""
        if not group_id or not fio:
            return False
        key = fio_key(fio)
        rows = await self.db.fetchall(
            "SELECT fio FROM users WHERE group_id = ? AND id <> ? AND fio IS NOT NULL", group_id, uid)
        return any(fio_key(r["fio"]) == key for r in rows)

    async def fio_changes_since(self, uid: int, since: int) -> int:
        return int(await self.db.scalar(
            "SELECT COUNT(*) FROM audit WHERE actor = ? AND action = 'fio_changed' AND ts >= ?", uid, since) or 0)

    async def teacher_lessons(self, surname: str, initials: str, d1: str, d2: str) -> list[dict]:
        """Занятия преподавателя у всех групп в диапазоне дат (с названием группы)."""
        rows = await self.db.fetchall(
            "SELECT l.*, g.name AS gname FROM lessons l JOIN groups g ON g.id = l.group_id "
            "WHERE l.day >= ? AND l.day <= ? AND l.teacher <> '' ORDER BY l.day, l.start_t", d1, d2)
        want = (surname, initials)
        return [r for r in rows if any(same_person(name_parts(n), want) for n in split_teachers(r["teacher"]))]

    # ================= вопросы, ожидающие ответа в чатах =================
    async def add_pending(self, chat_id: int, message_id: int, user_id: int, text: str, intent: str, due_at: int) -> int:
        return await self.db.insert(
            "INSERT INTO pending_questions (chat_id, message_id, user_id, text, intent, created_at, due_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'wait')", chat_id, message_id, user_id, text[:300], intent, now_ts(), due_at)

    async def pending_for_chat(self, chat_id: int) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM pending_questions WHERE chat_id = ? AND status = 'wait'", chat_id)

    async def pending_due(self, now: int) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM pending_questions WHERE status = 'wait' AND due_at <= ? ORDER BY due_at LIMIT 50", now)

    async def set_pending_status(self, pid: int, status: str) -> bool:
        n = await self.db.execute("UPDATE pending_questions SET status = ? WHERE id = ? AND status = 'wait'", status, pid,
                                  volatile=True)
        return n > 0

    async def purge_pending(self) -> None:
        await self.db.execute("DELETE FROM pending_questions WHERE created_at < ?", now_ts() - 2 * 86400, volatile=True)

    # ---- состояние диалога (переживает перезапуск) ----
    async def get_state(self, uid: int) -> tuple[str | None, dict]:
        row = await self.db.fetchone("SELECT state, data, ts FROM fsm WHERE user_id = ?", uid)
        if not row or now_ts() - int(row["ts"]) > 6 * 3600:
            return None, {}
        try:
            return row["state"], json.loads(row["data"])
        except ValueError:
            return row["state"], {}

    async def set_state(self, uid: int, state: str, data: dict | None = None) -> None:
        await self.db.execute(
            "INSERT INTO fsm (user_id, state, data, ts) VALUES (?, ?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET "
            "state = excluded.state, data = excluded.data, ts = excluded.ts",
            uid, state, json.dumps(data or {}, ensure_ascii=False), now_ts(), volatile=True)

    async def clear_state(self, uid: int) -> None:
        await self.db.execute("DELETE FROM fsm WHERE user_id = ?", uid, volatile=True)

    async def purge_old(self) -> None:
        await self.db.execute("DELETE FROM fsm WHERE ts < ?", now_ts() - 86400, volatile=True)
        await self.purge_pending()
        await self.db.execute("DELETE FROM lessons WHERE day < ?", iso(local_today() - timedelta(days=150)),
                              volatile=True)

    # ---- стоп-листы ФИО ----
    async def add_stopword(self, word: str, kind: str) -> None:
        w = word.lower().replace("ё", "е").strip()
        if w:
            await self.db.execute(
                "INSERT INTO stopwords (word, kind) VALUES (?, ?) ON CONFLICT (word) DO UPDATE SET kind = excluded.kind", w, kind)

    async def del_stopword(self, word: str) -> None:
        await self.db.execute("DELETE FROM stopwords WHERE word = ?", word.lower().replace("ё", "е").strip())

    async def stoplists(self) -> tuple[frozenset[str], frozenset[str]]:
        rows = await self.db.fetchall("SELECT word, kind FROM stopwords")
        stop = frozenset(r["word"] for r in rows if r["kind"] == "stub")
        bad = frozenset(r["word"] for r in rows if r["kind"] == "bad")
        return stop, bad

    async def list_stopwords(self) -> list[dict]:
        return await self.db.fetchall("SELECT word, kind FROM stopwords ORDER BY kind, word")

    # ================= бэкап =================
    async def dump(self) -> dict:
        tables: dict[str, list[dict]] = {}
        for name in TABLES:
            if name == "meta":
                continue
            tables[name] = await self.db.fetchall(f"SELECT * FROM {name}")
        return {"format": 1, "created": now_ts(), "tables": tables}

    async def restore(self, data: dict) -> dict[str, int]:
        if data.get("format") != 1 or "tables" not in data:
            raise ValueError("Неизвестный формат бэкапа")
        counts: dict[str, int] = {}
        tables = data["tables"]
        async with self.db.tx() as t:
            for name in TABLES:
                if name == "meta" or name not in tables:
                    continue
                await t.execute(f"DELETE FROM {name}")
                rows = tables[name]
                counts[name] = len(rows)
                for row in rows:
                    cols = list(row.keys())
                    if not all(re.fullmatch(r"[a-z_]+", c) for c in cols):
                        raise ValueError("Недопустимое имя колонки в бэкапе")
                    sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                    await t.execute(sql, [row[c] for c in cols])
            if self.db.kind == "pg":
                for name in SERIAL_TABLES:
                    await t.execute(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false)")
        await self.load_settings()
        self._invalidate_catalog()
        return counts

    async def is_empty(self) -> bool:
        return await self.count("users") == 0 and await self.count("lessons") == 0
