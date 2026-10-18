"""Экраны расписания и ответы на вопросы обычным текстом."""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta

from app import timeutil as tu
from app.bot import logic_find
from app.bot.core import Btn, Ctx, Kb, Out, Screen, b, home_btn
from app.services import format as fm
from app.services.nlu import Intent

log = logging.getLogger(__name__)



async def _ensure_group_schedule(ctx: Ctx, gid: int) -> None:
    """При пустом кэше группы синхронно попробует загрузить данные с сайта один раз за 2 минуты."""
    try:
        # Старые записи за прошлый семестр не должны считаться актуальным кэшем.
        count = await ctx.repo.count("lessons", "group_id = ? AND day >= ?", gid, tu.iso(ctx.today))
    except Exception:
        return
    if count:
        return
    sync = ctx.services.get("sync")
    if sync is None or not ctx.repo.flag("sync_enabled"):
        return
    now = tu.now_ts()
    try:
        last_try = int(ctx.repo.setting("sync_demand_attempt") or 0)
    except (TypeError, ValueError):
        last_try = 0
    if now - last_try < 120:
        return
    # Отмечаем попытку до сетевого вызова, чтобы несколько кликов не запустили много загрузок.
    await ctx.repo.set_setting("sync_demand_attempt", str(now))
    try:
        report = await sync.run_once()
        if not report.ok:
            log.warning("Не удалось загрузить расписание группы id=%s: %s", gid, report.message)
    except Exception:
        # Сбой загрузки не должен ломать экран расписания; ниже покажем честное состояние.
        return

def _sfx(other: int | None) -> str:
    return f":{other}" if other else ""


def _freshness(ctx: Ctx) -> str | None:
    try:
        last = int(ctx.repo.setting("sync_last_ok") or 0)
    except ValueError:
        last = 0
    fails = ctx.repo.int_setting("sync_fail_count") if ctx.repo.setting("sync_fail_count") else 0
    if not last:
        return None
    age_h = (tu.now_ts() - last) / 3600
    if fails >= 1 or age_h > 6:
        when = datetime.fromtimestamp(last, tu.tz()).strftime("%d.%m %H:%M")
        return f"Обновлено {when}. Сайт вуза сейчас недоступен или не обновляется, показано сохранённое расписание."
    return None


def _resolve_day(token: str, today: date) -> date:
    if token == "today":
        return today
    if token == "tom":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(token)
    except ValueError:
        return today


async def day_screen(ctx: Ctx, token: str = "today", other: int | None = None) -> Screen:
    gid = other or ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    group = await ctx.repo.get_group(gid)
    if group is None:
        return Screen("Группа не найдена.", [[home_btn()]])
    d = _resolve_day(token, ctx.today)
    own = not other
    sub = ctx.user.get("subgroup") if own else None
    await _ensure_group_schedule(ctx, gid)
    lessons = await ctx.repo.lessons_day(gid, tu.iso(d), sub)
    hw = await ctx.repo.hw_counts_for_day(gid, tu.iso(d)) if own else {}
    text = fm.day_text(d, lessons, ctx.parity(d), hw, group["name"] if not own else None, _freshness(ctx))
    sfx = _sfx(other)
    prev_d, next_d = tu.iso(d - timedelta(days=1)), tu.iso(d + timedelta(days=1))
    kb: Kb = [
        [Btn("◀", f"s:d:{prev_d}{sfx}"), Btn("📆 Дата", f"s:c:{d.year}-{d.month:02d}{sfx}"),
         Btn("▶", f"s:d:{next_d}{sfx}")],
        [Btn("Сегодня", f"s:d:today{sfx}"), Btn("Завтра", f"s:d:tom{sfx}"), Btn("Неделя", f"s:w:{tu.iso(tu.monday_of(d))}{sfx}")],
    ]
    if own:
        row: list[Btn] = [Btn("⏭ Следующая", "s:n")]
        if ctx.verified:
            row.append(Btn("➕ Задание", f"h:add:{tu.iso(d)}"))
        kb.append(row)
        if hw:
            kb.append([Btn(f"📎 Задания дня ({sum(hw.values())})", f"h:d:{tu.iso(d)}")])
        kb.append([home_btn()])
    else:
        kb.append([Btn("↩ Моё расписание", "s:d:today"), home_btn()])
    return Screen(text, kb)


async def week_screen(ctx: Ctx, token: str = "cur", other: int | None = None) -> Screen:
    gid = other or ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    group = await ctx.repo.get_group(gid)
    if group is None:
        return Screen("Группа не найдена.", [[home_btn()]])
    if token == "cur":
        monday = tu.monday_of(ctx.today)
    elif token == "next":
        monday = tu.monday_of(ctx.today) + timedelta(days=7)
    else:
        try:
            monday = tu.monday_of(date.fromisoformat(token))
        except ValueError:
            monday = tu.monday_of(ctx.today)
    own = not other
    sub = ctx.user.get("subgroup") if own else None
    await _ensure_group_schedule(ctx, gid)
    lessons = await ctx.repo.lessons_range(gid, tu.iso(monday), tu.iso(monday + timedelta(days=6)), sub)
    text = fm.week_text(monday, lessons, ctx.parity(monday), group["name"] if not own else None)
    fresh = _freshness(ctx)
    if fresh:
        text += f"\n\n<i>{fm.esc(fresh)}</i>"
    sfx = _sfx(other)
    days_row = [Btn(tu.DAYS_SHORT[i], f"s:d:{tu.iso(monday + timedelta(days=i))}{sfx}") for i in range(6)]
    kb: Kb = [
        [Btn("◀ Неделя", f"s:w:{tu.iso(monday - timedelta(days=7))}{sfx}"),
         Btn("Неделя ▶", f"s:w:{tu.iso(monday + timedelta(days=7))}{sfx}")],
        days_row,
        [Btn("Сегодня", f"s:d:today{sfx}"), home_btn()],
    ]
    return Screen(text, kb)


async def calendar_screen(ctx: Ctx, ym: str, other: int | None = None) -> Screen:
    gid = other or ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    try:
        y, m = (int(x) for x in ym.split("-"))
        first = date(y, m, 1)
    except (ValueError, TypeError):
        first = ctx.today.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    have = await ctx.repo.days_with_lessons(gid, tu.iso(first), tu.iso(first.replace(day=last_day)))
    sfx = _sfx(other)
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=last_day)).replace(day=1)
    kb: Kb = [[Btn("◀", f"s:c:{prev_m.year}-{prev_m.month:02d}{sfx}"),
               Btn(f"{tu.MONTHS_NOM[first.month - 1]} {first.year}", "noop"),
               Btn("▶", f"s:c:{next_m.year}-{next_m.month:02d}{sfx}")],
              [Btn(x, "noop") for x in tu.DAYS_SHORT]]
    row: list[Btn] = [Btn(" ", "noop")] * first.weekday()
    for dnum in range(1, last_day + 1):
        d = first.replace(day=dnum)
        iso_d = tu.iso(d)
        label = f"{dnum}•" if iso_d in have else str(dnum)
        if d == ctx.today:
            label = f"[{label}]"
        row.append(Btn(label, f"s:d:{iso_d}{sfx}"))
        if len(row) == 7:
            kb.append(row)
            row = []
    if row:
        row += [Btn(" ", "noop")] * (7 - len(row))
        kb.append(row)
    kb.append([Btn("Сегодня", f"s:d:today{sfx}"), home_btn()])
    return Screen("<b>Выберите дату</b>\n• — в этот день есть занятия", kb)


async def next_lesson_screen(ctx: Ctx) -> Screen:
    gid = ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    text = await next_lesson_text(ctx, gid, ctx.user.get("subgroup"))
    return Screen(text, [[Btn("📅 Сегодня", "s:d:today"), home_btn()]])


async def next_lesson_text(ctx: Ctx, gid: int, subgroup: int | None) -> str:
    await _ensure_group_schedule(ctx, gid)
    today_lessons = await ctx.repo.lessons_day(gid, tu.iso(ctx.today), subgroup)
    cur, nxt = fm.now_status(today_lessons, ctx.now)
    lines: list[str] = []
    if cur:
        e = tu.hhmm_to_min(cur["end_t"]) or 0
        left = e - (ctx.now.hour * 60 + ctx.now.minute)
        lines.append(f"▶️ <b>Сейчас идёт</b> (ещё {tu.fmt_duration(max(left, 1))})\n{fm.short_lesson(cur)}")
    if nxt:
        s = tu.hhmm_to_min(nxt["start_t"]) or 0
        left = s - (ctx.now.hour * 60 + ctx.now.minute)
        lines.append(f"⏭ <b>Дальше</b> (через {tu.fmt_duration(max(left, 1))})\n{fm.short_lesson(nxt)}")
    if not nxt:
        future = await ctx.repo.next_lessons(gid, tu.iso(ctx.today + timedelta(days=1)), 21, subgroup)
        if future:
            l = future[0]
            d = tu.parse_iso(l["day"])
            lines.append(f"⏭ <b>Следующая пара — {fm.when_word(d, ctx.today)}</b> ({tu.fmt_date(d)})\n{fm.short_lesson(l)}")
    if not lines:
        return "Ближайших занятий в расписании не нашёл."
    return "\n\n".join(lines)


# ---------------- ответы на вопросы обычным текстом ----------------
HELP_TEXT = (
    "<b>❓ Помощь — что умеет бот</b>\n"
    "📅 <b>Расписание:</b> сегодня, завтра, неделя или выбранная дата. В недельном расписании в первую очередь показываю тип занятия — лекция, практика или лабораторная — и предмет.\n"
    "⏭ <b>Следующая пара:</b> можно нажать кнопку в расписании или спросить «когда следующая пара?».\n"
    "📝 <b>Задания:</b> список заданий группы; если функция доступна, можно добавить задание кнопкой из расписания.\n"
    "👨‍🏫 <b>Преподаватели:</b> поиск по фамилии и просмотр информации из справочника.\n"
    "🔔 <b>Уведомления:</b> вечерняя сводка на завтра, напоминание перед парой и сообщения об изменениях. Каждую категорию можно отключить отдельно или выключить всё сразу.\n"
    "👥 <b>Другая группа:</b> показывает расписание другой группы, не меняя вашу основную группу. Для возврата нажмите «Назад» или «Меню».\n"
    "👤 <b>Профиль:</b> можно изменить ФИО, группу и подгруппу. Если ФИО отправлено на проверку, часть функций может быть временно недоступна.\n"
    "💬 <b>Связь с администрацией:</b> откройте «Ещё → Написать админу»; переписка продолжится в одном диалоге.\n"
    "📆 <b>Календарь:</b> можно выгрузить расписание в файл календаря.\n\n"
    "<i>Если расписание пустое или отличается от сайта, проверьте выбранную группу и попробуйте позже: иногда сайт вуза обновляется с задержкой. Бот не может гарантировать наличие данных, которых нет на сайте.</i>"
)


async def _pick_day(ctx: Ctx, gid: int, intent: Intent, subgroup: int | None) -> tuple[date, list[dict], str]:
    """Если день не назван: сегодня, а когда занятия на сегодня закончились, то завтра."""
    if intent.day is not None:
        return intent.day, await ctx.repo.lessons_day(gid, tu.iso(intent.day), subgroup), ""
    today_lessons = await ctx.repo.lessons_day(gid, tu.iso(ctx.today), subgroup)
    m = ctx.now.hour * 60 + ctx.now.minute
    remaining = [l for l in today_lessons if (tu.hhmm_to_min(l["end_t"]) or 0) > m]
    if remaining:
        return ctx.today, today_lessons, ""
    tomorrow = ctx.today + timedelta(days=1)
    tl = await ctx.repo.lessons_day(gid, tu.iso(tomorrow), subgroup)
    prefix = "Сегодня занятий уже нет. " if today_lessons else "Сегодня занятий нет. "
    return tomorrow, tl, prefix


def _lesson_kb(d: date) -> Kb:
    return [[Btn("📅 Открыть день", f"s:d:{tu.iso(d)}")]]


async def answer_intent(ctx: Ctx, intent: Intent, gid: int, subgroup: int | None = None,
                        allow_kb: bool = True) -> Screen | None:
    """Ответ на распознанный вопрос. gid - группа, для которой отвечаем."""
    repo = ctx.repo
    if intent.name not in {"help", "thanks", "greet", "parity", "find_teacher"}:
        await _ensure_group_schedule(ctx, gid)
    name = intent.name
    if name == "help":
        return Screen(HELP_TEXT, [[home_btn()]] if allow_kb else None)
    if name == "thanks":
        return Screen("Пожалуйста! 😊")
    if name == "greet":
        return Screen("Привет! Спросите, например: «какие завтра пары?»")
    if name == "parity":
        p = ctx.parity(ctx.today)
        return Screen(f"Сейчас {p} неделя." if p else "Чётность недель пока не настроена администратором.")
    if name == "find_teacher" and intent.teacher:
        return await logic_find.teacher_answer(ctx, intent.teacher, intent.day if intent.explicit_day else None)
    group = await repo.get_group(gid)
    if group is None:
        return None
    kb_for = (lambda d: _lesson_kb(d)) if allow_kb else (lambda d: None)

    if name == "week":
        base = intent.day or ctx.today
        monday = tu.monday_of(base) + timedelta(days=7 if (intent.week_shift == 1 and intent.day is None) else 0)
        lessons = await repo.lessons_range(gid, tu.iso(monday), tu.iso(monday + timedelta(days=6)), subgroup)
        kb = [[Btn("📅 Открыть неделю", f"s:w:{tu.iso(monday)}")]] if allow_kb else None
        return Screen(fm.week_text(monday, lessons, ctx.parity(monday)), kb)

    if name == "hw":
        return await _answer_hw(ctx, intent, gid)

    if name == "subject_day":
        return await _answer_subject_day(ctx, intent, gid, subgroup, kb_for)

    if name == "exam":
        rows = await repo.upcoming_kind(gid, tu.iso(ctx.today), ("экзамен", "зачет", "консультац"), 8)
        if not rows:
            return Screen("Экзаменов и зачётов в расписании пока не вижу.")
        lines = ["<b>Ближайшие экзамены и зачёты</b>"]
        for l in rows:
            d = tu.parse_iso(l["day"])
            lines.append(f"{tu.fmt_date(d)}, {l['start_t']} · {fm.esc(l['subject'])} ({fm.esc(l['kind'])})"
                         + (f", ауд. {fm.esc(l['room'])}" if l["room"] else ""))
        return Screen("\n".join(lines))

    if name == "next":
        return Screen(await next_lesson_text(ctx, gid, subgroup),
                      [[Btn("📅 Сегодня", "s:d:today")]] if allow_kb else None)

    if name == "when_subject":
        subj = intent.subject
        rows = await repo.next_lessons(gid, tu.iso(ctx.today), 60, subgroup)
        rows = [l for l in rows if l["subject"] == subj and (l["day"] > tu.iso(ctx.today) or
                (tu.hhmm_to_min(l["end_t"]) or 0) > ctx.now.hour * 60 + ctx.now.minute)]
        if not rows:
            return Screen(f"«{fm.esc(subj)}» в ближайшие 2 месяца в расписании не нашёл.")
        l = rows[0]
        d = tu.parse_iso(l["day"])
        return Screen(f"<b>{fm.esc(subj)}</b>: ближайшая пара — {fm.when_word(d, ctx.today)} ({tu.fmt_date(d)})\n"
                      f"{fm.short_lesson(l)}", kb_for(d))

    # остальные интенты работают с конкретным днём
    d, lessons, prefix = await _pick_day(ctx, gid, intent, subgroup)
    when = fm.when_word(d, ctx.today)
    if name == "day":
        if intent.num:
            hit = [l for l in lessons if l["num"] == intent.num]
            if not hit:
                return Screen(f"{prefix}{when.capitalize()}: пары №{intent.num} нет.", kb_for(d))
            return Screen(f"{prefix}{when.capitalize()}:\n{fm.lesson_block(hit[0])}", kb_for(d))
        hw = await repo.hw_counts_for_day(gid, tu.iso(d))
        return Screen((prefix + "\n\n" if prefix else "") + fm.day_text(d, lessons, ctx.parity(d), hw), kb_for(d))
    if not lessons:
        return Screen(f"{prefix}{when.capitalize()} занятий нет 🎉", kb_for(d))
    if name == "count":
        first, last = lessons[0], lessons[-1]
        return Screen(f"{prefix}{when.capitalize()} пар: <b>{len(lessons)}</b>, с {first['start_t']} до {last['end_t']}.",
                      kb_for(d))
    if name == "first":
        l = lessons[0]
        return Screen(f"{prefix}Первая пара {when}:\n{fm.lesson_block(l)}", kb_for(d))
    if name == "last":
        l = lessons[-1]
        return Screen(f"{prefix}Последняя пара {when} заканчивается в <b>{l['end_t']}</b>:\n{fm.lesson_block(l)}",
                      kb_for(d))
    if name in ("room", "teacher"):
        hit: list[dict]
        if intent.num:
            hit = [l for l in lessons if l["num"] == intent.num]
        elif intent.subject:
            hit = [l for l in lessons if l["subject"] == intent.subject]
            if not hit:
                rows = await repo.next_lessons(gid, tu.iso(ctx.today), 60, subgroup)
                hit = [l for l in rows if l["subject"] == intent.subject][:1]
                if hit:
                    d = tu.parse_iso(hit[0]["day"])
                    when = fm.when_word(d, ctx.today)
        else:
            hit = lessons[:1]
        if not hit:
            return Screen(f"{prefix}Не нашёл такой пары {when}.", kb_for(d))
        l = hit[0]
        if name == "room":
            room = f"аудитория <b>{fm.esc(l['room'])}</b>" if l["room"] else "аудитория в расписании не указана"
            return Screen(f"{prefix}{fm.esc(l['subject'])} ({when}, {l['start_t']}): {room}.", kb_for(d))
        who = f"<b>{fm.esc(l['teacher'])}</b>" if l["teacher"] else "преподаватель в расписании не указан"
        return Screen(f"{prefix}{fm.esc(l['subject'])} ({when}, {l['start_t']}): {who}.", kb_for(d))
    return None


async def _answer_hw(ctx: Ctx, intent: Intent, gid: int) -> Screen:
    repo = ctx.repo
    today_iso = tu.iso(ctx.today)
    if intent.subject:
        rows = await repo.hw_for_subject(gid, intent.subject, today_iso, 5)
        title = f"Задания · {fm.esc(intent.subject)}"
    elif intent.day is not None:
        rows = await repo.hw_for_day(gid, tu.iso(intent.day))
        title = f"Задания на пары {fm.when_word(intent.day, ctx.today)}"
    else:
        rows, _ = await repo.list_hw(gid, today_iso, 0, 6)
        title = "Актуальные задания"
    if not rows:
        return Screen("Подтверждённых заданий не нашёл. Добавить: «дз математика №15 к пятнице».")
    lines = [f"<b>{title}</b>"]
    for h in rows[:6]:
        due = f" (до {tu.fmt_dm(date.fromisoformat(h['due_day']))})" if h["due_day"] else ""
        txt = h["text"] if len(h["text"]) <= 160 else h["text"][:157] + "…"
        lines.append(f"• <b>{fm.esc(h['subject'])}</b>{due}: {fm.esc(txt)}")
    return Screen("\n".join(lines), [[Btn("📝 Все задания", "h:l:0")]])


async def _answer_subject_day(ctx: Ctx, intent: Intent, gid: int, subgroup: int | None, kb_for) -> Screen:
    """«Завтра будет МГП?»: есть ли пара по предмету в этот день, когда, где и с кем."""
    repo = ctx.repo
    subj = intent.subject or ""
    d = intent.day or ctx.today
    lessons = [l for l in await repo.lessons_day(gid, tu.iso(d), subgroup) if l["subject"] == subj]
    if intent.day is None:
        m = ctx.now.hour * 60 + ctx.now.minute
        lessons = [l for l in lessons if (tu.hhmm_to_min(l["end_t"]) or 0) > m]
    when = fm.when_word(d, ctx.today)
    if lessons:
        out = []
        for l in lessons:
            room = f", ауд. <b>{fm.esc(l['room'])}</b>" if l["room"] else ""
            teacher = f", преподаватель <b>{fm.esc(l['teacher'])}</b>" if l["teacher"] else ""
            kind = f" ({fm.esc(l['kind'])})" if l["kind"] else ""
            out.append(f"<b>{fm.esc(subj)}</b>{kind}: пара состоится {when} в {l['start_t']}–{l['end_t']}{room}{teacher}.")
        return Screen("\n".join(out), kb_for(d))
    rows = await repo.next_lessons(gid, tu.iso(d + timedelta(days=1)), 60, subgroup)
    nxt = [l for l in rows if l["subject"] == subj][:1]
    text = f"{when.capitalize()} пары «{fm.esc(subj)}» в расписании нет."
    if nxt:
        nd = tu.parse_iso(nxt[0]["day"])
        text += f"\nБлижайшая — {fm.when_word(nd, ctx.today)} ({tu.fmt_date(nd)}):\n{fm.short_lesson(nxt[0])}"
    return Screen(text, kb_for(nxt and tu.parse_iso(nxt[0]["day"]) or d))
