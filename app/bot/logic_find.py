"""Где найти преподавателя: идущая или ближайшая пара (все группы) + подразделение и кабинет из справочника вуза."""
from __future__ import annotations

from datetime import date, timedelta

from app import timeutil as tu
from app.bot.core import Ctx, Screen
from app.db.repo import name_parts, same_person, split_teachers
from app.services import format as fm

WINDOW_DAYS = 14


def _parse_query(query: str) -> tuple[str, str]:
    parts = (query or "").lower().replace("ё", "е").split()
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def _lesson_line(l: dict, with_day: bool = False) -> str:
    room = f", ауд. {fm.esc(l['room'])}" if l["room"] else ""
    day = f"{tu.fmt_date(tu.parse_iso(l['day']))}, " if with_day else ""
    return f"{day}{l['start_t']}–{l['end_t']} · {fm.esc(l['subject'])} · гр. {fm.esc(l['gname'])}{room}"


def _teacher_lessons(lessons: list[dict], key: tuple[str, str]) -> list[dict]:
    return [l for l in lessons if any(same_person(name_parts(n), key) for n in split_teachers(l["teacher"]))]


async def _directory_lines(ctx: Ctx, staff_row: dict | None) -> list[str]:
    if staff_row is None:
        return ["🏛 В справочнике вуза этого преподавателя не нашёл."]
    unit = staff_row.get("unit") or ""
    if not unit:
        return ["🏛 Структурное подразделение в справочнике не указано."]
    label = "Кафедра" if "кафедр" in unit.casefold() else "Подразделение"
    lines = [f"🏛 <b>{label}</b>\n{fm.esc(unit)}"]
    u = await ctx.repo.get_unit(unit)
    if u and u.get("room"):
        room = fm.esc(u["room"]).replace("кабинет №", "").strip()
        if not room.casefold().startswith("корпус "):
            room = room.replace("каб. ", "").strip()
        lines.append(f"🚪 <b>Кабинет кафедры</b>\n{room}")
    else:
        lines.append("🚪 <b>Кабинет кафедры</b>\nКабинет подразделения в справочнике не указан (нет подтверждённых данных).")
    return lines


def _teacher_lesson_card(l: dict) -> list[str]:
    """Карточка пары преподавателя в том же стиле, что и общее расписание."""
    # Общий формат: номер и время / предмет / тип, преподаватель и аудитория.
    lines = fm._lesson_compact_lines(l)
    if l.get("gname"):
        lines.append(f"👥 Группа: {fm.esc(l['gname'])}")
    return lines


def _schedule_lines(ctx: Ctx, lessons: list[dict], day: date | None) -> list[str]:
    m = ctx.now.hour * 60 + ctx.now.minute
    today_iso = tu.iso(ctx.today)
    if day is not None:
        ls = [l for l in lessons if l["day"] == tu.iso(day)]
        if not ls:
            return [f"📅 {fm.when_word(day, ctx.today).capitalize()} пар в расписании нет."]
        result = [f"📅 <b>{fm.when_word(day, ctx.today).capitalize()}</b>"]
        for l in ls[:5]:
            result.extend(_teacher_lesson_card(l))
            result.append("")
        return result[:-1]

    current = [l for l in lessons if l["day"] == today_iso and (tu.hhmm_to_min(l["start_t"]) or 0) <= m < (tu.hhmm_to_min(l["end_t"]) or 0)]
    if current:
        l = current[0]
        return [f"▶️ <b>Сейчас ведёт пару до {fm.esc(l['end_t'])}</b>", *_teacher_lesson_card(l)]

    upcoming = [l for l in lessons if l["day"] > today_iso or (l["day"] == today_iso and (tu.hhmm_to_min(l["start_t"]) or 0) > m)]
    if not upcoming:
        return [f"📅 В ближайшие {WINDOW_DAYS} дней пар в расписании нет."]
    first = upcoming[0]
    d = tu.parse_iso(first["day"])
    return [f"⏭️ <b>Ближайшая пара · {fm.when_word(d, ctx.today)}</b>",
            f"📅 {tu.fmt_date(d)}", *_teacher_lesson_card(first)]


async def teacher_answer(ctx: Ctx, query: str, day: date | None = None) -> Screen:
    surname, initials = _parse_query(query)
    if not surname:
        return Screen("Назовите фамилию преподавателя, например: «где найти Иванова?».")
    repo = ctx.repo
    staff = await repo.find_staff(surname, initials)
    d1 = tu.iso(ctx.today)
    d2 = tu.iso(ctx.today + timedelta(days=WINDOW_DAYS))
    lessons = await repo.teacher_lessons(surname, initials, d1, d2)
    if day is not None and tu.iso(day) > d2:
        lessons += await repo.teacher_lessons(surname, initials, tu.iso(day), tu.iso(day))

    # отдельные люди: по справочнику и по расписанию
    people: dict[tuple[str, str], dict] = {}
    for s in staff:
        people[(s["surname"], s["initials"])] = {"name": s["name"], "staff": s}
    for l in lessons:
        for n in split_teachers(l["teacher"]):
            key = name_parts(n)
            if same_person(key, (surname, initials)) and not any(same_person(key, k) for k in people):
                people[key] = {"name": n, "staff": None}
    if not people:
        return Screen(f"Преподавателя «{fm.esc(surname.capitalize())}» не нашёл ни в расписании, ни в справочнике вуза. "
                      "Проверьте фамилию или добавьте инициалы.")
    # у людей без записи в справочнике пытаемся найти себя по расписанию, и наоборот
    items = list(people.items())
    blocks: list[str] = []
    for key, info in items[:4]:
        mine = _teacher_lessons(lessons, key)
        lines = [f"🧑‍🏫 <b>{fm.esc(info['name'])}</b>"]
        lines += _schedule_lines(ctx, mine, day)
        staff_row = info["staff"]
        if staff_row is None:
            match = [s for s in staff if same_person((s["surname"], s["initials"]), key)]
            staff_row = match[0] if match else None
        lines += await _directory_lines(ctx, staff_row)
        blocks.append("\n".join(lines))
    head = ""
    if len(items) > 1 and not initials:
        head = "Нашёл нескольких с такой фамилией, уточните инициалы:\n\n"
    if len(items) > 4:
        blocks.append(f"…и ещё {len(items) - 4}. Уточните инициалы.")
    return Screen((head + "\n\n".join(blocks))[:3800])
