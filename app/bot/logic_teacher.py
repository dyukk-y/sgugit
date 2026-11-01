"""Личный режим преподавателя: расписание, свободные аудитории и поиск коллег."""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from app import timeutil as tu
from app.bot.core import Btn, Ctx, Kb, Out, Screen, home_btn, nav
from app.bot import logic_find
from app.db.repo import name_parts
from app.services import format as fm


def _teacher_name(account: dict) -> tuple[str, str]:
    return name_parts(account["name"])


async def menu(ctx: Ctx) -> Screen:
    account = await ctx.repo.teacher_account(ctx.uid)
    if not account:
        return Screen("Профиль преподавателя не найден. Пройдите регистрацию по фамилии.",
                      [[Btn("👨‍🏫 Найти себя в справочнике", "p:register")], [Btn("🏠 Студенческий режим", "p:student")]])
    rows: Kb = [
        [Btn("📅 Моё расписание", "p:day:today")],
        [Btn("⏭ Ближайшая пара", "p:next")],
        [Btn("🏫 Свободные аудитории", "p:rooms")],
        [Btn("🔎 Найти преподавателя", "p:find")],
        [Btn("💬 Поддержка", "me:fb"), Btn("❓ Помощь", "p:help")],
        [Btn("🔄 Сменить преподавателя", "p:change")],
        [Btn("🎓 Студенческий режим", "p:student")],
    ]
    today = await ctx.repo.teacher_lessons(*_teacher_name(account), tu.iso(ctx.today), tu.iso(ctx.today))
    active = [l for l in today if not l.get("cancelled")]
    status = "Сегодня пар нет." if not active else f"Сегодня запланировано пар: <b>{len(active)}</b>."
    return Screen(f"🧑‍🏫 <b>Кабинет преподавателя</b>\n{fm.esc(account['name'])}\n\n{status}\nВыберите нужный раздел.", rows)


def _day_token(token: str, today: date) -> date:
    if token == "today":
        return today
    if token == "tom":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(token)
    except ValueError:
        return today


async def day_screen(ctx: Ctx, token: str = "today") -> Screen:
    account = await ctx.repo.teacher_account(ctx.uid)
    if not account:
        return await menu(ctx)
    day = _day_token(token, ctx.today)
    surname, initials = _teacher_name(account)
    lessons = await ctx.repo.teacher_lessons(surname, initials, tu.iso(day), tu.iso(day))
    lessons.sort(key=lambda l: (l["start_t"], l["num"], l["group_id"]))
    active = [l for l in lessons if not l.get("cancelled")]
    title = f"<b>{tu.DAYS_FULL[day.weekday()]}, {tu.fmt_date(day)}</b>"
    lines = [title, f"🧑‍🏫 {fm.esc(account['name'])}", ""]
    if not lessons:
        lines.append("Сегодня пар нет 🎉" if day == ctx.today else "На эту дату пар нет 🎉")
    else:
        for lesson in lessons:
            lines.extend(fm._lesson_compact_lines(lesson))
            if lesson.get("gname"):
                lines.append(f"👥 Группа: {fm.esc(lesson['gname'])}")
            lines.append("")
        if not active:
            lines.append("Все найденные занятия на эту дату отмечены как отменённые.")
    prev_day, next_day = tu.iso(day - timedelta(days=1)), tu.iso(day + timedelta(days=1))
    kb: Kb = [
        [Btn("◀", f"p:day:{prev_day}"), Btn("📆 Календарь", f"p:cal:{day.year}-{day.month:02d}"),
         Btn("▶", f"p:day:{next_day}")],
        [Btn("Сегодня", "p:day:today"), Btn("Завтра", "p:day:tom"),
         Btn("Неделя", f"p:week:{tu.iso(tu.monday_of(day))}")],
        nav("p:menu"),
    ]
    return Screen("\n".join(lines)[:3900], kb)


async def week_screen(ctx: Ctx, token: str = "cur") -> Screen:
    account = await ctx.repo.teacher_account(ctx.uid)
    if not account:
        return await menu(ctx)
    if token == "cur":
        monday = tu.monday_of(ctx.today)
    elif token == "next":
        monday = tu.monday_of(ctx.today) + timedelta(days=7)
    else:
        try:
            monday = tu.monday_of(date.fromisoformat(token))
        except ValueError:
            monday = tu.monday_of(ctx.today)
    surname, initials = _teacher_name(account)
    sunday = monday + timedelta(days=6)
    lessons = await ctx.repo.teacher_lessons(surname, initials, tu.iso(monday), tu.iso(sunday))
    by_day: dict[str, list[dict]] = {}
    for lesson in lessons:
        by_day.setdefault(lesson["day"], []).append(lesson)
    lines = [f"<b>Расписание преподавателя · {tu.fmt_dm(monday)}–{tu.fmt_dm(sunday)}</b>",
             fm.esc(account["name"])]
    any_lessons = False
    for offset in range(7):
        day = monday + timedelta(days=offset)
        items = by_day.get(tu.iso(day), [])
        if not items and offset >= 5:
            continue
        lines.extend(["", f"📅 <b>{tu.DAYS_FULL[offset]}, {tu.fmt_dm(day)}</b>"])
        if not items:
            lines.append("Пар нет")
            continue
        for lesson in items:
            any_lessons = True
            lines.extend(fm._lesson_compact_lines(lesson))
            if lesson.get("gname"):
                lines.append(f"👥 Группа: {fm.esc(lesson['gname'])}")
    if not any_lessons:
        lines.append("\nНа этой неделе пар нет.")
    prev_week = tu.iso(monday - timedelta(days=7))
    next_week = tu.iso(monday + timedelta(days=7))
    kb: Kb = [
        [Btn("◀ Неделя", f"p:week:{prev_week}"), Btn("Неделя ▶", f"p:week:{next_week}")],
        [Btn("Пн", f"p:day:{tu.iso(monday)}"), Btn("Вт", f"p:day:{tu.iso(monday+timedelta(days=1))}"),
         Btn("Ср", f"p:day:{tu.iso(monday+timedelta(days=2))}"), Btn("Чт", f"p:day:{tu.iso(monday+timedelta(days=3))}"),
         Btn("Пт", f"p:day:{tu.iso(monday+timedelta(days=4))}")],
        [Btn("Сегодня", "p:day:today"), Btn("Календарь", f"p:cal:{monday.year}-{monday.month:02d}")],
        nav("p:menu"),
    ]
    return Screen("\n".join(lines)[:3900], kb)


async def calendar_screen(ctx: Ctx, ym: str) -> Screen:
    try:
        year, month = (int(x) for x in ym.split("-"))
        first = date(year, month, 1)
    except (ValueError, TypeError):
        first = ctx.today.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    account = await ctx.repo.teacher_account(ctx.uid)
    have: set[str] = set()
    if account:
        surname, initials = _teacher_name(account)
        rows = await ctx.repo.teacher_lessons(surname, initials, tu.iso(first), tu.iso(first.replace(day=last_day)))
        have = {l["day"] for l in rows if not l.get("cancelled")}
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=last_day)).replace(day=1)
    kb: Kb = [[Btn("◀", f"p:cal:{prev_m.year}-{prev_m.month:02d}"),
               Btn(f"{tu.MONTHS_NOM[first.month - 1]} {first.year}", "noop"),
               Btn("▶", f"p:cal:{next_m.year}-{next_m.month:02d}")],
              [Btn(x, "noop") for x in tu.DAYS_SHORT]]
    row: list[Btn] = [Btn(" ", "noop")] * first.weekday()
    for n in range(1, last_day + 1):
        day = first.replace(day=n)
        label = f"{n}•" if tu.iso(day) in have else str(n)
        if day == ctx.today:
            label = f"[{label}]"
        row.append(Btn(label, f"p:day:{tu.iso(day)}"))
        if len(row) == 7:
            kb.append(row)
            row = []
    if row:
        row += [Btn(" ", "noop")] * (7 - len(row))
        kb.append(row)
    kb.append([Btn("Сегодня", "p:day:today"), home_btn()])
    return Screen("<b>Календарь преподавателя</b>\n• — в этот день есть пары", kb)


def _room_identity(room: str) -> tuple[str, str]:
    low = room.lower().replace("ё", "е")
    corpus = re.search(r"корп(?:ус)?\.?\s*([0-9а-яa-z]+)", low)
    numbers = re.findall(r"(?<!\d)(\d{2,4}[а-яa-z]?)(?!\d)", low)
    return (corpus.group(1) if corpus else "", numbers[-1] if numbers else re.sub(r"[^а-яa-z0-9]", "", low))


def _same_room(left: str, right: str) -> bool:
    lc, ln = _room_identity(left)
    rc, rn = _room_identity(right)
    return bool(ln and ln == rn and (not lc or not rc or lc == rc))


def _room_floor(room: str) -> str:
    # Для типичных трёхзначных аудиторий первая цифра обозначает этаж.
    numbers = re.findall(r"(?<!\d)(\d{3})(?!\d)", room)
    if not numbers:
        return "этаж не указан"
    return f"{int(numbers[-1][0])} этаж (по номеру аудитории)"


async def free_rooms_screen(ctx: Ctx) -> Screen:
    rooms, occupied = await ctx.repo.teacher_free_room_data(tu.iso(ctx.today), ctx.now.hour * 60 + ctx.now.minute)
    ordered = sorted(rooms, key=lambda r: (int(re.search(r"\d+", r).group()) if re.search(r"\d+", r) else 10**9, r.casefold()))
    unique: list[str] = []
    for room in ordered:
        if not any(_same_room(room, seen) for seen in unique):
            unique.append(room)
    free = [room for room in unique if not any(_same_room(room, busy) for busy in occupied)]
    if not rooms:
        body = "В расписании пока нет списка аудиторий, поэтому определить свободные кабинеты не удалось."
    elif not free:
        body = "Сейчас все известные аудитории заняты по расписанию."
    else:
        body = "<b>Свободные аудитории сейчас</b>\n" + "\n".join(
            f"• <b>{fm.esc(room)}</b> — {_room_floor(room)}" for room in free[:70])
        if len(free) > 70:
            body += f"\n…и ещё {len(free)-70}."
    body += "\n\n<i>Расчёт по загруженному расписанию. Если занятие перенесли или аудиторию используют вне расписания, данные могут отличаться.</i>"
    return Screen(body, [[Btn("🔄 Обновить", "p:rooms")], nav("p:menu")])


async def next_screen(ctx: Ctx) -> Screen:
    account = await ctx.repo.teacher_account(ctx.uid)
    if not account:
        return await menu(ctx)
    surname, initials = _teacher_name(account)
    rows = await ctx.repo.teacher_lessons(surname, initials, tu.iso(ctx.today), tu.iso(ctx.today + timedelta(days=30)))
    rows = [l for l in rows if not l.get("cancelled")]
    now_min = ctx.now.hour * 60 + ctx.now.minute
    current = [l for l in rows if l["day"] == tu.iso(ctx.today)
               and (tu.hhmm_to_min(l["start_t"]) or 0) <= now_min < (tu.hhmm_to_min(l["end_t"]) or 0)]
    if current:
        lesson = current[0]
        title = f"▶️ <b>Сейчас идёт пара до {fm.esc(lesson['end_t'])}</b>"
    else:
        upcoming = [l for l in rows if l["day"] > tu.iso(ctx.today)
                    or (l["day"] == tu.iso(ctx.today) and (tu.hhmm_to_min(l["start_t"]) or 0) > now_min)]
        if not upcoming:
            return Screen("Сегодня пар нет, и ближайших занятий в следующие 30 дней не найдено.",
                          [[Btn("📅 Расписание", "p:day:today")], nav("p:menu")])
        lesson = upcoming[0]
        title = f"⏭ <b>Ближайшая пара · {fm.when_word(tu.parse_iso(lesson['day']), ctx.today)}</b>"
    lines = [title, f"📅 {tu.fmt_date(tu.parse_iso(lesson['day']))}", *fm._lesson_compact_lines(lesson)]
    if lesson.get("gname"):
        lines.append(f"👥 Группа: {fm.esc(lesson['gname'])}")
    return Screen("\n".join(lines), [[Btn("📅 Расписание", f"p:day:{lesson['day']}")], nav("p:menu")])


async def on_cb(ctx: Ctx, parts: list[str]) -> Out:
    act = parts[0] if parts else "menu"
    if act == "register":
        if ctx.is_admin:
            return Out(toast="Режим преподавателя пока доступен для обычных аккаунтов", alert=True)
        linked = await ctx.repo.teacher_account(ctx.uid)
        if linked:
            await ctx.repo.update_user(ctx.uid, role="teacher")
            ctx.user["role"] = "teacher"
            return Out(screen=await menu(ctx), clear_state=True)
        return Out(screen=Screen("Напишите фамилию преподавателя так, как она указана в расписании вуза.",
                                 [nav("m:home")]), state="p:surname", state_data={})
    if act == "change":
        if ctx.role != "teacher":
            return Out(toast="Сначала войдите в режим преподавателя", alert=True)
        return Out(screen=Screen("Напишите фамилию преподавателя, на которого хотите сменить профиль.",
                                 [nav("p:menu")]), state="p:surname", state_data={})
    if act == "choose" and len(parts) > 1 and parts[1].isdigit():
        state, data = await ctx.repo.get_state(ctx.uid)
        teacher_id = int(parts[1])
        allowed = state == "p:confirm" and (
            data.get("teacher_id") == teacher_id or teacher_id in data.get("candidate_ids", [])
        )
        if not allowed:
            return Out(toast="Этот вариант устарел. Начните поиск заново.", alert=True)
        teacher = await ctx.repo.get_teacher(teacher_id)
        if not teacher or teacher["hidden"]:
            return Out(toast="Преподаватель не найден в справочнике расписания", alert=True)
        if not await ctx.repo.set_teacher_account(ctx.uid, teacher["id"]):
            return Out(toast="Не удалось сохранить профиль. Попробуйте позже.", alert=True)
        await ctx.repo.audit(ctx.uid, "teacher_mode_register", f"{teacher['id']}:{teacher['name']}")
        ctx.user["role"] = "teacher"
        return Out(screen=await menu(ctx), clear_state=True, toast="Профиль преподавателя подключён")
    if act == "student":
        await ctx.repo.switch_teacher_to_student(ctx.uid)
        ctx.user["role"] = "student"
        if ctx.user.get("group_id"):
            from app.bot import logic_user
            return Out(screen=await logic_user.main_menu(ctx), clear_state=True)
        from app.bot import logic_user
        return await logic_user.start(ctx)
    if act == "menu":
        return Out(screen=await menu(ctx), clear_state=True)
    if act == "day":
        return Out(screen=await day_screen(ctx, parts[1] if len(parts) > 1 else "today"), clear_state=True)
    if act == "week":
        return Out(screen=await week_screen(ctx, parts[1] if len(parts) > 1 else "cur"), clear_state=True)
    if act == "cal":
        return Out(screen=await calendar_screen(ctx, parts[1] if len(parts) > 1 else ""), clear_state=True)
    if act == "next":
        return Out(screen=await next_screen(ctx), clear_state=True)
    if act == "rooms":
        return Out(screen=await free_rooms_screen(ctx), clear_state=True)
    if act == "find":
        return Out(screen=Screen("Напишите фамилию преподавателя (можно с инициалами). Покажу, какая пара идёт сейчас или когда будет ближайшая.",
                                 [nav("p:menu")]), state="p:find", state_data={})
    if act == "help":
        help_text = ("<b>Помощь · кабинет преподавателя</b>\n"
                     "• <b>Моё расписание</b> — пары на сегодня, завтра, неделю и выбранную дату. В карточке есть время, предмет, тип, аудитория и учебная группа.\n"
                     "• <b>Ближайшая пара</b> — показывает занятие, которое идёт сейчас, или следующее по расписанию.\n"
                     "• <b>Свободные аудитории</b> — аудитории, которые сейчас не заняты по расписанию. Этаж определяется по трёхзначному номеру, если он указан.\n"
                     "• <b>Найти преподавателя</b> — покажет текущую или ближайшую пару коллеги.\n"
                     "• <b>Поддержка</b> — личное обращение к администрации бота.\n\n"
                     "<i>Расписание и свободные аудитории рассчитываются по данным, загруженным ботом. Фактические изменения вне системы могут не отображаться.</i>")
        return Out(screen=Screen(help_text, [[Btn("🌐 Сайт СГУГиТ", url="https://sgugit.ru/")], nav("p:menu")]), clear_state=True)
    return Out(toast="Неизвестное действие")


async def on_text(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if state == "p:surname":
        query = " ".join(text.strip().lower().replace("ё", "е").split())
        if len(query) < 2 or not re.fullmatch(r"[а-яa-z-]+(?:\s+[а-яa-z.]+)*", query):
            return Out(screen=Screen("Введите фамилию русскими или латинскими буквами, без должности и кафедры.",
                                     [nav("m:home")]), state=state, state_data=data)
        found = await ctx.repo.search_teachers(query, limit=30)
        first = query.split()[0].rstrip(".")
        exact = [t for t in found if t["norm"].split()[0] == first]
        candidates = exact or found
        if not candidates:
            return Out(screen=Screen(f"В расписании не нашёл преподавателя с фамилией «{fm.esc(text.strip())}». Проверьте написание или попробуйте полное ФИО.",
                                     [nav("m:home")]), state=state, state_data=data)
        candidates = candidates[:8]
        if len(candidates) == 1:
            t = candidates[0]
            return Out(screen=Screen(f"Нашёл преподавателя: <b>{fm.esc(t['name'])}</b>\nЭто вы?\n\n<i>Это саморегистрация по справочнику, не официальная проверка личности.</i>",
                                     [[Btn("✅ Да, это я", f"p:choose:{t['id']}")], [Btn("↩ Ввести другую фамилию", "p:register")]]),
                       state="p:confirm", state_data={"teacher_id": t["id"]})
        kb: Kb = [[Btn(t["name"][:40], f"p:choose:{t['id']}")] for t in candidates]
        kb.append([Btn("↩ Ввести другую фамилию", "p:register")])
        return Out(screen=Screen("Нашёл несколько преподавателей. Выберите своё полное имя:", kb),
                   state="p:confirm", state_data={"candidate_ids": [t["id"] for t in candidates]})
    if state == "p:find":
        from app.services.nlu import extract_teacher
        known = await ctx.repo.known_surnames()
        query = extract_teacher(text, known) or text.strip()
        scr = await logic_find.teacher_answer(ctx, query)
        scr.kb = [[Btn("🔎 Найти другого преподавателя", "p:find")], nav("p:menu")]
        return Out(screen=scr, clear_state=True)
    return Out(screen=await menu(ctx), clear_state=True)
