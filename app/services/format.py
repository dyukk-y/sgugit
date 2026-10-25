"""Форматирование расписания и ответов для Telegram (HTML-разметка)."""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from app import timeutil as tu

NUM_EMOJI = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
MAX_LEN = 3900


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


def num_emoji(n: int) -> str:
    return NUM_EMOJI[n] if 0 <= n <= 9 else f"{n}."


def _kind_icon(kind: str) -> str:
    low = (kind or "").strip().lower()
    if "лекц" in low:
        return "🎓"
    if "лаб" in low:
        return "🧪"
    if "практ" in low or "семинар" in low:
        return "🛠"
    return "📚"


def _lesson_compact_lines(l: dict) -> list[str]:
    """Consistent compact lesson card used in day, week and next-lesson views."""
    number = int(l.get("num") or 0)
    head = f"<b>{number:02d}</b> ·  {esc(l.get('start_t', '??:??'))}–{esc(l.get('end_t', '??:??'))}"
    subject = f"📘 {esc(l.get('subject') or 'Название предмета не указано')}"
    kind = (l.get("kind") or "").strip()
    details = [f"{_kind_icon(kind)} {esc(kind.lower() if kind else 'тип занятия не указан')}"]
    if l.get("teacher"):
        details.append(f"👨‍🏫 {esc(l['teacher'])}")
    if l.get("room"):
        details.append(f"📍 {esc(l['room'])}")
    if l.get("subgroup"):
        details.append(f"👥 подгруппа {esc(str(l['subgroup']))}")
    lines = [head, subject, "  ·  ".join(details)]
    return lines


def lesson_block(l: dict, hw_count: int = 0, show_date: bool = False) -> str:
    """Compact, emoji-led lesson card with a consistent three-line layout."""
    lines = _lesson_compact_lines(l)
    if show_date:
        lines.insert(0, f"📅 <b>{tu.fmt_dm(tu.parse_iso(l['day']))}</b>")
    if l.get("manual"):
        lines.append("✏️ Добавлено вручную")
    if hw_count:
        lines.append(f"📎 Заданий: {hw_count}")
    return "\n".join(lines)


def _gap_minutes(prev_end: str, next_start: str) -> int:
    a, b = tu.hhmm_to_min(prev_end), tu.hhmm_to_min(next_start)
    if a is None or b is None:
        return 0
    return b - a


def day_text(d: date, lessons: list[dict], parity: str | None = None, hw_counts: dict[str, int] | None = None,
             group_name: str | None = None, fresh: str | None = None) -> str:
    hw_counts = hw_counts or {}
    title = f"<b>{tu.DAYS_FULL[d.weekday()]}, {d.day} {tu.MONTHS_GEN[d.month - 1]}</b>"
    if parity:
        title += f" · {parity} неделя"
    head = [title]
    if group_name:
        head.append(f"Группа {esc(group_name)}")
    if not lessons:
        body = ["", "Занятий нет 🎉" if d.weekday() < 6 else "Выходной 🎉"]
    else:
        body = [""]
        prev_end: str | None = None
        for l in lessons:
            if prev_end is not None:
                gap = _gap_minutes(prev_end, l["start_t"])
                if gap >= 60:
                    body.append(f"🕐 окно {tu.fmt_duration(gap)}")
            body.append(lesson_block(l, hw_counts.get(l["subject"], 0)))
            prev_end = l["end_t"]
    out = "\n".join(head + body)
    if fresh:
        out += f"\n\n<i>{esc(fresh)}</i>"
    return out[:MAX_LEN]


def week_text(monday: date, lessons: list[dict], parity: str | None = None, group_name: str | None = None) -> str:
    sunday = monday + timedelta(days=6)
    title = f"<b>Неделя {tu.fmt_dm(monday)}–{tu.fmt_dm(sunday)}</b>"
    if parity:
        title += f" · {parity}"
    parts = [title]
    if group_name:
        parts.append(f"Группа {esc(group_name)}")
    by_day: dict[str, list[dict]] = {}
    for l in lessons:
        by_day.setdefault(l["day"], []).append(l)
    any_lessons = False
    for i in range(7):
        d = monday + timedelta(days=i)
        ls = by_day.get(tu.iso(d), [])
        if not ls and i >= 5:
            continue
        parts.append("")
        parts.append(f"📅 <b>{tu.DAYS_FULL[i]}, {tu.fmt_dm(d)}</b>" + ("" if ls else " — занятий нет 🎉"))
        for l in ls:
            any_lessons = True
            # Same compact layout as the daily schedule: number/time, subject, type/teacher/room.
            parts.append("\n".join(_lesson_compact_lines(l)))
    if not any_lessons:
        parts.append("\nНа этой неделе занятий не найдено.")
    text = "\n".join(parts)
    return text if len(text) <= MAX_LEN else text[:MAX_LEN - 20] + "\n…"


def short_lesson(l: dict) -> str:
    """The same three-line visual style for next-lesson and compact views."""
    return "\n".join(_lesson_compact_lines(l))


def when_word(d: date, today: date) -> str:
    delta = (d - today).days
    names = {0: "сегодня", 1: "завтра", 2: "послезавтра", -1: "вчера"}
    return names.get(delta, f"{tu.DAYS_SHORT[d.weekday()].lower()} {tu.fmt_dm(d)}")


def now_status(lessons_today: list[dict], now: datetime) -> tuple[dict | None, dict | None]:
    """(идёт сейчас, следующая сегодня)."""
    cur = nxt = None
    m = now.hour * 60 + now.minute
    for l in lessons_today:
        s, e = tu.hhmm_to_min(l["start_t"]), tu.hhmm_to_min(l["end_t"])
        if s is None or e is None:
            continue
        if s <= m < e and cur is None:
            cur = l
        elif s > m and nxt is None:
            nxt = l
    return cur, nxt


def changes_text(group_name: str, changes: list[dict]) -> str:
    """changes: [{'day', 'removed': [keys], 'added': [keys]}], key = (day,num,start,end,subject,teacher,room,kind,sub)."""
    lines = [f"🔔 <b>Изменения в расписании</b> · {esc(group_name)}"]

    def fmt(k: tuple) -> str:
        room = f", {esc(k[6])}" if k[6] else ""
        return f"{num_emoji(k[1])} {k[2]}–{k[3]} {esc(k[4])}{room}"

    for ch in changes[:7]:
        d = tu.parse_iso(ch["day"])
        lines.append("")
        lines.append(f"<b>{tu.fmt_date(d)}</b>")
        for k in ch["removed"][:6]:
            lines.append(f"➖ {fmt(k)}")
        for k in ch["added"][:6]:
            lines.append(f"➕ {fmt(k)}")
    if len(changes) > 7:
        lines.append(f"\n…и ещё изменений: {len(changes) - 7}")
    return "\n".join(lines)[:MAX_LEN]


def _ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def make_ics(lessons: Iterable[dict], group_name: str) -> bytes:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SGUGiT Schedule Bot//RU", "CALSCALE:GREGORIAN",
           f"X-WR-CALNAME:{_ics_escape(group_name)}"]
    for l in lessons:
        d = tu.parse_iso(l["day"])
        s = tu.local_to_utc(d, l["start_t"]).strftime("%Y%m%dT%H%M%SZ")
        e = tu.local_to_utc(d, l["end_t"]).strftime("%Y%m%dT%H%M%SZ")
        desc = ", ".join(x for x in (l["teacher"], l["kind"]) if x)
        out += ["BEGIN:VEVENT", f"UID:lesson-{l['id']}@sgugit-bot", f"DTSTAMP:{stamp}", f"DTSTART:{s}", f"DTEND:{e}",
                f"SUMMARY:{_ics_escape(l['subject'])}"]
        if l["room"]:
            out.append(f"LOCATION:{_ics_escape(l['room'])}")
        if desc:
            out.append(f"DESCRIPTION:{_ics_escape(desc)}")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return ("\r\n".join(out) + "\r\n").encode("utf-8")
