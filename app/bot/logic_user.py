"""Регистрация, профиль, уведомления, заявка на старосту, прочие экраны меню «Ещё»."""
from __future__ import annotations

import time
from datetime import timedelta

from app import timeutil as tu
from app.bot import logic_schedule as ls
from app.bot.core import Btn, Ctx, Kb, Out, Screen, b, daily_quota, home_btn, nav
from app.db.repo import canonical_group_name, norm_group
from app.services import format as fm
from app.services.fio import validate_fio

_FIO_TRIES: dict[int, list] = {}   # uid -> [попытки, заблокирован_до]
_FB_LAST: dict[int, float] = {}

WELCOME = ("<b>Привет! Я бот расписания СГУГиТ</b> 👋\n"
           "Мне нужны ваша группа и ФИО: по ним я показываю расписание, задания группы и даю оценить "
           "преподавателей. Данные видят только администраторы бота.\n\n"
           "Напишите вашу группу, например: <code>ИС-11</code>")


async def main_menu(ctx: Ctx) -> Screen:
    group = await ctx.group()
    head = (ctx.repo.setting("interface_main_text") or "<b>Привет! Я бот СГУГиТ 👋</b>\n📅 Расписание на день и неделю\n🎓 Типы занятий и время пар\n📝 Задания группы · 👨‍🏫 Поиск преподавателей\n🔔 Напоминания — настройте под себя\n\n<b>Главное меню</b>") + (f"\n👥 Группа: {fm.esc(group['name'])}" if group else "")
    if ctx.repo.flag("maintenance"):
        head += "\n⚠️ Идут технические работы."

    rows: Kb = [
        [Btn("📅 Расписание", "s:d:today")],
        [Btn("📝 Задания", "h:l:0"), Btn("🔔 Уведомления", "me:ntf")],
        [Btn("👥 Другая группа", "me:other")],
        [Btn("🔎 Найти преподавателя", "me:findt")],
        [Btn("⚙️ Ещё", "me:menu")],
        [Btn("➕ В группу", url=f"https://t.me/{ctx.bot_username}?startgroup=true"),
         Btn(ctx.repo.setting("sponsor_button_title") or "💎 Спонсор",
             url=ctx.repo.setting("sponsor_button_url") or "https://t.me/theyasha_bot?start=ref_6702947726")],
    ]

    if ctx.repo.flag("rating_enabled"):
        rows[3].append(Btn("⭐Оценить преподавателя", "t:l:m:0"))

    return Screen(head, rows)


async def start(ctx: Ctx) -> Out:
    await ctx.repo.update_user(ctx.uid, private_started=1)
    ctx.user["private_started"] = 1
    if ctx.registered and ctx.user.get("fio"):
        return Out(screen=await main_menu(ctx), clear_state=True)
    if ctx.registered:
        return Out(screen=Screen("Напишите ваше ФИО полностью: <code>Фамилия Имя Отчество</code>"),
                   state="reg:fio", state_data={})
    welcome = Screen(ctx.repo.setting("welcome_text") or WELCOME, [[Btn(
        "➕ Добавить в группу", url=f"https://t.me/{ctx.bot_username}?startgroup=true")]])
    return Out(screen=welcome, state="reg:group", state_data={})


def _group_pick_screen(groups: list[dict], text_note: str = "") -> Screen:
    kb: Kb = [[Btn(g["name"], f"r:g:{g['id']}")] for g in groups[:6]]
    return Screen(text_note or "Выберите вашу группу:", kb)


async def _after_group(ctx: Ctx, gid: int) -> Out:
    had_fio = bool(ctx.user.get("fio"))
    await ctx.repo.update_user(ctx.uid, group_id=gid, subgroup=None)
    ctx.user["group_id"], ctx.user["subgroup"] = gid, None
    ctx._group_loaded = False
    if had_fio:
        return Out(screen=await main_menu(ctx), clear_state=True, toast="Группа изменена")
    return Out(screen=Screen("Отлично! Теперь напишите ваше ФИО полностью: <code>Фамилия Имя Отчество</code>"),
               state="reg:fio", state_data={})


async def on_cb_register(ctx: Ctx, parts: list[str]) -> Out:
    act = parts[0] if parts else ""
    if act == "g" and len(parts) > 1 and parts[1].isdigit():
        g = await ctx.repo.get_group(int(parts[1]))
        if not g:
            return Out(toast="Группа не найдена", alert=True)
        return await _after_group(ctx, g["id"])
    if act == "redo":
        return Out(screen=Screen("Напишите ФИО ещё раз: <code>Фамилия Имя Отчество</code>"), state="reg:fio", state_data={})
    if act == "ok":
        state, data = await ctx.repo.get_state(ctx.uid)
        fio, verdict = data.get("fio"), data.get("verdict")
        if state != "reg:fio_confirm" or not fio:
            return Out(screen=Screen("Давайте ещё раз. Напишите ФИО: <code>Фамилия Имя Отчество</code>"),
                       state="reg:fio", state_data={})
        status = "pending"  # подтверждает только автопроверка (после паузы и всех проверок) или администратор
        dup = await ctx.repo.fio_duplicate(ctx.user.get("group_id"), fio, ctx.uid)
        await ctx.repo.update_user(ctx.uid, fio=fio, fio_status=status, fio_submitted_at=tu.now_ts())
        ctx.user["fio"], ctx.user["fio_status"] = fio, status
        note = "дубликат в группе" if dup else (data.get("reasons") or "")
        await ctx.repo.audit(ctx.uid, "register", f"{status}:{verdict}" + (f":{note}" if note else ""))
        menu = await main_menu(ctx)
        if data.get("confident") and not dup:
            delay = ctx.repo.int_setting("fio_auto_delay_min")
            menu.text = (f"Готово! Расписание уже доступно. ФИО проходит автоматическую проверку — обычно до {delay} мин. "
                         "После подтверждения откроются задания и оценки преподавателей.\n\n") + menu.text
        else:
            menu.text = ("Готово! Расписание уже доступно. ФИО отправлено на проверку администратору — "
                         "после подтверждения откроются задания и оценки преподавателей.\n\n") + menu.text
        return Out(screen=menu, clear_state=True)
    return Out(toast="Неизвестное действие")


async def on_text_register(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if state == "reg:group":
        canonical = canonical_group_name(text)
        if canonical is None:
            return Out(screen=Screen(
                "Введите только название группы в формате <code>МД-22.1</code> или <code>ИС-11</code>.\n\n"
                "Варианты <code>мд22.1</code>, <code>мд221</code> и <code>мд-221</code> тоже распознаются."),
                state="reg:group", state_data=data)
        key = norm_group(canonical)
        all_groups = await ctx.repo.all_groups()
        # Сначала только точное совпадение нормализованного кода. Оно не зависит
        # от того, как группа записана в источнике (Э-22.1 / э221 / Э 22.1).
        groups = [g for g in all_groups if norm_group(g.get("name", "")) == key or g.get("norm") == key]
        # На английской раскладке буквой E часто пытаются набрать «Э». Сначала
        # ищем точную «Е»-группу, и только при её отсутствии проверяем вариант «Э».
        if not groups and canonical.startswith("Е-") and len(canonical.split("-", 1)[0]) == 1:
            alias_key = norm_group("Э-" + canonical.split("-", 1)[1])
            groups = [g for g in all_groups if norm_group(g.get("name", "")) == alias_key or g.get("norm") == alias_key]
        if not groups:
            total = await ctx.repo.count("groups")
            sync = ctx.services.get("sync")
            try:
                last_ok = int(ctx.repo.setting("sync_last_ok") or 0)
            except (TypeError, ValueError):
                last_ok = 0
            # Если нужной группы нет в кэше, обновляем каталог при пустой БД или
            # когда синхронизация устарела. Так не зацикливаем сетевые запросы на опечатках.
            refresh_after = max(300, int(getattr(ctx.cfg, "sync_interval_min", 30)) * 60)
            should_sync = total == 0 or (tu.now_ts() - last_ok >= refresh_after)
            if sync is not None and ctx.repo.flag("sync_enabled") and should_sync:
                try:
                    await sync.run_once()
                except Exception:
                    # Ошибка уже журналируется сервисом синхронизации.
                    pass
                all_groups = await ctx.repo.all_groups()
                groups = [g for g in all_groups if norm_group(g.get("name", "")) == key or g.get("norm") == key]
                if not groups and canonical.startswith("Е-") and len(canonical.split("-", 1)[0]) == 1:
                    alias_key = norm_group("Э-" + canonical.split("-", 1)[1])
                    groups = [g for g in all_groups if norm_group(g.get("name", "")) == alias_key or g.get("norm") == alias_key]
                total = await ctx.repo.count("groups")
                if len(groups) == 1:
                    kb = [[Btn(f"✅ Да, {groups[0]['name']}", f"r:g:{groups[0]['id']}")]]
                    return Out(screen=Screen("Ваша группа?", kb), state="reg:group", state_data=data)
                if len(groups) > 1:
                    return Out(screen=_group_pick_screen(groups), state="reg:group", state_data=data)
            if total == 0:
                error = ctx.repo.setting("sync_last_error") if hasattr(ctx.repo, "setting") else ""
                suffix = f"\nТехническая причина: <code>{fm.esc(error[:180])}</code>" if error else ""
                return Out(screen=Screen(
                    "Не удалось получить расписание с сайта автоматически. Попробуйте ещё раз через минуту." + suffix),
                    state="reg:group", state_data=data)
            # Если точного совпадения нет, предложим похожие реальные группы, но никогда
            # не привяжем пользователя автоматически к группе с похожим названием.
            candidates = await ctx.repo.search_groups(canonical, limit=5)
            candidates = [g for g in candidates if norm_group(g.get("name", "")) != key]
            if candidates:
                return Out(screen=_group_pick_screen(
                    candidates, f"Точную группу <code>{fm.esc(canonical)}</code> не нашёл.\n"
                    "Возможно, вы имели в виду одну из этих групп:"), state="reg:group", state_data=data)
            return Out(screen=Screen(f"Группа <code>{fm.esc(canonical)}</code> не найдена. Проверьте номер группы."),
                       state="reg:group", state_data=data)
        if len(groups) == 1:
            kb = [[Btn(f"✅ Да, {groups[0]['name']}", f"r:g:{groups[0]['id']}")]]
            return Out(screen=Screen("Ваша группа?", kb), state="reg:group", state_data=data)
        return Out(screen=_group_pick_screen(groups), state="reg:group", state_data=data)
    if state == "reg:fio":
        tries = _FIO_TRIES.setdefault(ctx.uid, [0, 0.0])
        if tries[1] and time.time() < tries[1]:
            wait = int((tries[1] - time.time()) // 60) + 1
            return Out(screen=Screen(f"Слишком много попыток. Подождите {wait} мин. и попробуйте снова."),
                       state="reg:fio", state_data=data)
        stop, bad = await ctx.repo.stoplists()
        res = validate_fio(text, stop, bad, ctx=await ctx.repo.fio_context())
        if res.verdict == "reject":
            tries[0] += 1
            if tries[0] >= 15:
                await ctx.repo.audit(ctx.uid, "fio_abuse", f"{tries[0]} попыток")
            if tries[0] % 5 == 0:
                tries[1] = time.time() + 600
                return Out(screen=Screen("Слишком много неудачных попыток. Подождите 10 минут."),
                           state="reg:fio", state_data=data)
            return Out(screen=Screen(f"{res.message}\n\nПопробуйте ещё раз: <code>Фамилия Имя Отчество</code>"),
                       state="reg:fio", state_data=data)
        _FIO_TRIES.pop(ctx.uid, None)
        kb = [[Btn("✅ Да, всё верно", "r:ok"), Btn("✏️ Изменить", "r:redo")]]
        return Out(screen=Screen(f"Ваше ФИО: <b>{fm.esc(res.fio)}</b>\nВсё верно?", kb),
                   state="reg:fio_confirm",
                   state_data={"fio": res.fio, "verdict": res.verdict, "confident": res.confident, "reasons": res.code})
    return Out(screen=await main_menu(ctx), clear_state=True)


# ---------------- меню «Ещё» ----------------
async def more_menu(ctx: Ctx) -> Screen:
    # Здесь только дополнительные действия: пункты главного меню не дублируем.
    kb: Kb = [
        [Btn("👤 Профиль", "me:prof")],
        [Btn("📤 В календарь", "me:ics"), Btn("❓ Помощь", "me:help")],
        [Btn("📨 Написать админу", "me:fb")],
    ]
    if ctx.is_admin:
        kb.append([Btn("🛠 Админ-панель", "ad:menu")])
    kb.append([home_btn()])
    return Screen("<b>Ещё ⚙️</b>\nДополнительные возможности: профиль, календарь, помощь и связь с администрацией. Выберите нужный пункт ниже.", kb)


def _status_text(ctx: Ctx) -> str:
    s = ctx.user.get("fio_status")
    return {"verified": "подтверждено ✅", "pending": "на проверке ⏳", "rejected": "отклонено ❌"}.get(s, "не указано")


async def profile_screen(ctx: Ctx) -> Screen:
    g = await ctx.group()
    sub = ctx.user.get("subgroup")
    role = {"super": "главный администратор", "admin": "администратор"}.get(ctx.role, "студент")
    lines = ["<b>Профиль</b>",
             f"Группа: {fm.esc(g['name']) if g else '—'}",
             f"ФИО: {fm.esc(ctx.user.get('fio') or '—')} ({_status_text(ctx)})",
             f"Подгруппа: {sub if sub else 'все'}",
             f"Роль: {role}"]
    kb: Kb = [[Btn("✏️ Изменить ФИО", "me:fio")], [Btn("🔄 Сменить группу", "me:grp")],
              [Btn("Подгруппа: все" + (" ✅" if not sub else ""), "me:sub:0"),
               Btn("1" + (" ✅" if sub == 1 else ""), "me:sub:1"), Btn("2" + (" ✅" if sub == 2 else ""), "me:sub:2")],
              nav("me:menu")]
    if not ctx.user.get("fio"):
        kb.insert(1, [Btn("✏️ Указать ФИО", "r:redo")])
    return Screen("\n".join(lines), kb)


def _tick(on: bool) -> str:
    return "✅" if on else "⬜"


def _onoff(on: bool) -> str:
    return "ВКЛ ✅" if on else "ВЫКЛ ⬜"


async def notif_screen(ctx: Ctx) -> Screen:
    """Экран уведомлений. Одна настройка = одна кнопка на всю ширину с состоянием в подписи;
    время и «за сколько минут» — по две кнопки в ряд (короткие подписи), чтобы на телефоне текст не обрезался."""
    u = ctx.user
    enabled = bool(u.get("n_enabled", 1))
    ev, ch = bool(u["n_evening"]), bool(u["n_changes"])
    before = int(u["n_before"] or 0)
    lines = ["<b>🔔 Уведомления</b>",
             "Нажмите на пункт, чтобы включить или выключить его. Состояние написано на кнопке.", ""]
    lines.append(f"Все уведомления: {'включены' if enabled else 'ВЫКЛЮЧЕНЫ'}")
    lines.append(f"🌙 Вечерняя сводка: {'в ' + u['n_evening_time'] if ev else 'выкл'}")
    lines.append(f"⏰ Перед парой: {'за ' + str(before) + ' мин' if before else 'выкл'}")
    lines.append(f"🔄 Изменения в расписании: {'присылать' if ch else 'не присылать'}")
    if not enabled:
        lines.append("\nСейчас ничего не приходит. Отдельные настройки сохранены и заработают после включения.")
    elif not ctx.repo.flag("notify_changes") and ch:
        lines.append("\nℹ️ Рассылку изменений временно отключила администрация.")
    kb: Kb = [
        [Btn(f"🔔 Все уведомления: {_onoff(enabled)}", "me:n:all:t")],
        [Btn(f"🌙 Вечерняя сводка: {_onoff(ev)}", "me:n:ev:t")],
        [Btn((f"✅ " if u["n_evening_time"] == t else "") + f"🕒 {t}", f"me:n:et:{t.replace(':', '')}") for t in ("19:00", "20:00")],
        [Btn((f"✅ " if u["n_evening_time"] == t else "") + f"🕒 {t}", f"me:n:et:{t.replace(':', '')}") for t in ("21:00", "22:00")],
        [Btn("⌨️ Свое время сводки", "me:n:custom_evening")],
        [Btn(f"🔄 Изменения в расписании: {_onoff(ch)}", "me:n:ch:t")],
        [Btn((("✅ " if before == m else "") + ("⏰ Перед парой: выкл" if m == 0 else f"⏰ За {m} мин")), f"me:n:bf:{m}") for m in (0, 15)],
        [Btn((("✅ " if before == m else "") + f"⏰ За {m} мин"), f"me:n:bf:{m}") for m in (30, 60)],
        [Btn("⌨️ Свой интервал (1–180 мин)", "me:n:custom_before")],
        nav("m:home"),
    ]
    return Screen("\n".join(lines), kb)


async def on_cb_me(ctx: Ctx, parts: list[str]) -> Out:
    act = parts[0] if parts else "menu"
    repo = ctx.repo
    if act == "menu":
        return Out(screen=await more_menu(ctx), clear_state=True)
    if act == "prof":
        return Out(screen=await profile_screen(ctx))
    if act == "help":
        return Out(screen=Screen(ls.HELP_TEXT + "\n\n<b>Полезные ссылки</b>", [[Btn("🌐 Сайт СГУГиТ", url="https://sgugit.ru/"), Btn("📅 Расписание вуза", url="https://sgugit.ru/raspisanie/")], [Btn("🏛 Структура и кафедры", url="https://sgugit.ru/university/struct/kafedry/")], nav("me:menu")]))
    if act == "ntf":
        return Out(screen=await notif_screen(ctx))
    if act == "n" and len(parts) >= 3:
        field, val = parts[1], parts[2]
        if field == "custom_evening":
            return Out(screen=Screen("Введите время вечерней сводки в формате ЧЧ:ММ, например 20:35.", [nav("me:ntf")]), state="me:n_evening_time", state_data={})
        if field == "custom_before":
            return Out(screen=Screen("За сколько минут до пары напоминать? Введите число от 1 до 180.", [nav("me:ntf")]), state="me:n_before", state_data={})
        if field == "all" and val == "t":
            await repo.update_user(ctx.uid, n_enabled=0 if ctx.user.get("n_enabled", 1) else 1)
        elif field == "ev" and val == "t":
            await repo.update_user(ctx.uid, n_evening=0 if ctx.user["n_evening"] else 1)
        elif field == "et" and val.isdigit() and len(val) == 4:
            hhmm = f"{val[:2]}:{val[2:]}"
            if hhmm in ("19:00", "20:00", "21:00", "22:00"):
                await repo.update_user(ctx.uid, n_evening_time=hhmm)
        elif field == "bf" and val in ("0", "15", "30", "60"):
            await repo.update_user(ctx.uid, n_before=int(val))
        elif field == "ch" and val == "t":
            await repo.update_user(ctx.uid, n_changes=0 if ctx.user["n_changes"] else 1)
        ctx.user.update(await repo.get_user(ctx.uid) or {})
        return Out(screen=await notif_screen(ctx))
    if act == "sub" and len(parts) > 1 and parts[1] in ("0", "1", "2"):
        await repo.update_user(ctx.uid, subgroup=int(parts[1]) or None)
        ctx.user["subgroup"] = int(parts[1]) or None
        return Out(screen=await profile_screen(ctx), toast="Сохранено")
    if act == "fio":
        return Out(screen=Screen("✏️ Напишите ФИО полностью в формате <code>Фамилия Имя Отчество</code>. После проверки оно обновится в профиле.", [nav("me:prof")]), state="me:fio", state_data={})
    if act == "grp":
        return Out(screen=Screen("Напишите новую группу, например <code>ИС-11</code>", [nav("me:prof")]),
                   state="reg:group", state_data={"change": 1})
    if act == "other":
        return Out(screen=Screen("👥 <b>Расписание другой группы</b>\nНапишите код группы, например <code>ИС-11</code>. Ваша основная группа не изменится. Если передумали — нажмите «Назад» или «Меню».",
                                 [nav("m:home")]), state="me:other", state_data={})
    if act == "findt":
        return Out(screen=Screen("Напишите фамилию преподавателя (можно с инициалами): покажу, где он сейчас или где его найти.",
                                 [nav("m:home")]), state="me:findt", state_data={})
    if act == "ics":
        gid = ctx.user.get("group_id")
        if not gid:
            return Out(toast="Сначала выберите группу", alert=True)
        rows = await repo.lessons_range(gid, tu.iso(ctx.today), tu.iso(ctx.today + timedelta(days=60)),
                                        ctx.user.get("subgroup"))
        if not rows:
            return Out(toast="В ближайшие 60 дней занятий нет", alert=True)
        g = await ctx.group()
        return Out(file=("schedule.ics", fm.make_ics(rows, g["name"] if g else "Группа"),
                         "Расписание на 60 дней. Откройте файл, чтобы добавить его в календарь."),
                   toast="Файл отправлен")
    if act == "fb":
        tickets = await repo.db.fetchall(
            "SELECT t.id, t.created_at, t.status, (SELECT text FROM support_messages m WHERE m.ticket_id = t.id ORDER BY m.id LIMIT 1) AS first_text, "
            "(SELECT COUNT(*) FROM support_messages m WHERE m.ticket_id = t.id) AS n "
            "FROM support_tickets t WHERE t.user_id = ? ORDER BY t.id DESC LIMIT 10", ctx.uid)
        if not tickets:
            tid = await repo.db.insert("INSERT INTO support_tickets (user_id, created_at, status) VALUES (?, ?, 'open')", ctx.uid, tu.now_ts())
            return Out(screen=Screen(f"<b>💬 Обращение №{tid}</b>\nНапишите вопрос администрации. Переписка сохранится здесь, а ответ придёт в этот чат.", [nav("me:menu")]),
                       state="me:fb", state_data={"ticket_id": tid})
        lines = ["<b>📨 Обращения в поддержку</b>", "Выберите обращение, чтобы прочитать переписку, или создайте новое."]
        kb = []
        for t in tickets:
            snippet = (t.get("first_text") or "Без текста").replace("\n", " ")[:24]
            kb.append([Btn(f"💬 Обращение №{t['id']} · {snippet}", f"me:ticket:{t['id']}")])
        kb.append([Btn("➕ Новое обращение", "me:fbnew")])
        kb.append(nav("me:menu"))
        if not tickets:
            lines.append("\nУ вас пока нет обращений.")
        return Out(screen=Screen("\n".join(lines), kb), clear_state=True)
    if act == "fbnew":
        tid = await repo.db.insert("INSERT INTO support_tickets (user_id, created_at, status) VALUES (?, ?, 'open')", ctx.uid, tu.now_ts())
        return Out(screen=Screen(f"<b>💬 Обращение №{tid}</b>\nОпишите вопрос одним или несколькими сообщениями. Ответ администратора появится в этом диалоге.", [nav("me:fb")]),
                   state="me:fb", state_data={"ticket_id": tid})
    if act == "ticket" and len(parts) > 1 and parts[1].isdigit():
        tid = int(parts[1])
        ticket = await repo.db.fetchone("SELECT * FROM support_tickets WHERE id = ? AND user_id = ?", tid, ctx.uid)
        if not ticket:
            return Out(toast="Обращение не найдено", alert=True)
        rows = await repo.db.fetchall("SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY id DESC LIMIT 20", tid)
        rows.reverse()
        lines = [f"<b>💬 Обращение №{tid}</b>"]
        for m in rows:
            stamp = time.strftime("%d.%m %H:%M", time.localtime(int(m["created_at"])))
            who = "👤 Вы" if m["sender_role"] == "user" else "🛠 Администратор"
            lines.append(f"\n{who} · {stamp}\n{fm.esc(m['text'][:700])}")
        if len(lines) == 1:
            lines.append("\nПока сообщений нет. Напишите свой вопрос ниже.")
        return Out(screen=Screen("\n".join(lines)[:3900], [[Btn("✍️ Написать сообщение", f"me:ticketreply:{tid}")], nav("me:fb")]))
    if act == "ticketreply" and len(parts) > 1 and parts[1].isdigit():
        tid = int(parts[1])
        ticket = await repo.db.fetchone("SELECT id FROM support_tickets WHERE id = ? AND user_id = ?", tid, ctx.uid)
        if not ticket:
            return Out(toast="Обращение не найдено", alert=True)
        return Out(screen=Screen(f"💬 Обращение №{tid}\nНапишите сообщение — оно добавится в эту переписку.", [nav(f"me:ticket:{tid}")]),
                   state="me:fb", state_data={"ticket_id": tid})
    if act == "mydata":
        g = await ctx.group()
        n_ratings = await repo.count("ratings", "user_id = ?", ctx.uid)
        n_hw = await repo.count("homework", "author_id = ?", ctx.uid)
        text = ("<b>Что бот хранит о вас</b>\n"
                f"• Telegram ID и @username\n• Группа: {fm.esc(g['name']) if g else '—'}\n"
                f"• ФИО: {fm.esc(ctx.user.get('fio') or '—')}\n• Настройки уведомлений\n"
                f"• Оценок преподавателям: {n_ratings}\n• Добавленных заданий: {n_hw}")
        kb = [[Btn("🗑 Удалить мои данные", "me:del")], nav("me:prof")]
        return Out(screen=Screen(text, kb))
    if act == "del":
        if len(parts) > 1 and parts[1] == "y":
            await repo.update_user(ctx.uid, fio=None, fio_status="none", group_id=None, username=None, tg_name=None,
                                   subgroup=None, n_evening=0, n_before=0, n_changes=0)
            await repo.audit(ctx.uid, "self_delete", "")
            return Out(screen=Screen("Ваши данные удалены. Оценки остаются без привязки к вам. "
                                     "Чтобы начать заново, нажмите /start."), clear_state=True)
        return Out(screen=Screen("Удалить ФИО, группу и настройки? Это нельзя отменить.",
                                 [[Btn("Да, удалить", "me:del:y"), Btn("Отмена", "me:mydata")]]))
    if act == "head":
        return Out(screen=await more_menu(ctx), toast="Функция старосты отключена")
    return Out(toast="Неизвестное действие")


async def _head_request(ctx: Ctx) -> Out:
    repo = ctx.repo
    if ctx.is_head or ctx.is_admin:
        return Out(toast="У вас уже есть расширенные права", alert=True)
    if ctx.user.get("head_blocked"):
        return Out(toast="Недоступно", alert=True)
    if not ctx.verified or not ctx.registered:
        return Out(toast="Сначала нужно подтверждённое ФИО", alert=True)
    last = await repo.request_for_user(ctx.uid)
    if last and last["status"] == "pending":
        return Out(screen=Screen("Ваша заявка уже на рассмотрении. Сообщим о решении.", [nav("me:menu")]))
    rid = await repo.create_request(ctx.uid, ctx.user["group_id"])
    g = await ctx.group()
    text = (f"👑 <b>Заявка на старосту</b>\n{fm.esc(ctx.user.get('fio') or '')} (ID {ctx.uid}"
            f"{', @' + fm.esc(ctx.user['username']) if ctx.user.get('username') else ''})\n"
            f"Группа: {fm.esc(g['name']) if g else '—'}")
    kb = [[Btn("✅ Одобрить", f"ad:rqd:{rid}:ok"), Btn("❌ Отказать", f"ad:rqd:{rid}:no")]]
    out = Out(screen=Screen("Заявка отправлена администраторам. Сообщим о решении.", [nav("me:menu")]))
    admins = [ctx.cfg.superadmin_id]
    for a in await repo.users_with_role("admin"):
        if "requests" in (a.get("admin_perms") or "").split(","):
            admins.append(a["id"])
    out.notify = [(aid, Screen(text, kb)) for aid in dict.fromkeys(admins)]
    return out


async def on_text_me(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if state == "me:n_evening_time":
        value = text.strip()
        if not tu.hhmm_to_min(value) and value != "00:00":
            return Out(screen=Screen("Неверный формат. Введите время ЧЧ:ММ, например 20:35."), state=state, state_data=data)
        try:
            h, m = map(int, value.split(":"))
            if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
        except ValueError:
            return Out(screen=Screen("Время должно быть от 00:00 до 23:59."), state=state, state_data=data)
        await ctx.repo.update_user(ctx.uid, n_evening_time=value)
        ctx.user.update(await ctx.repo.get_user(ctx.uid) or {})
        return Out(screen=await notif_screen(ctx), clear_state=True, toast="Время сохранено")
    if state == "me:n_before":
        try: minutes = int(text.strip())
        except ValueError: minutes = -1
        if not 1 <= minutes <= 180:
            return Out(screen=Screen("Введите целое число от 1 до 180."), state=state, state_data=data)
        await ctx.repo.update_user(ctx.uid, n_before=minutes)
        ctx.user.update(await ctx.repo.get_user(ctx.uid) or {})
        return Out(screen=await notif_screen(ctx), clear_state=True, toast="Интервал сохранён")
    if state == "me:fio":
        if await ctx.repo.fio_changes_since(ctx.uid, tu.now_ts() - 86400) >= 3:
            return Out(screen=Screen("За последние сутки ФИО уже менялось несколько раз. Попробуйте завтра "
                                     "или напишите администратору.", [nav("me:prof")]), clear_state=True)
        tries = _FIO_TRIES.setdefault(ctx.uid, [0, 0.0])
        if tries[1] and time.time() < tries[1]:
            wait = int((tries[1] - time.time()) // 60) + 1
            return Out(screen=Screen(f"Слишком много попыток. Подождите {wait} мин. и попробуйте снова.", [nav("me:prof")]),
                       state="me:fio", state_data=data)
        stop, bad = await ctx.repo.stoplists()
        res = validate_fio(text, stop, bad, ctx=await ctx.repo.fio_context())
        if res.verdict == "reject":
            tries[0] += 1
            if tries[0] % 5 == 0:
                tries[1] = time.time() + 600
            return Out(screen=Screen(f"{res.message}\n\nПопробуйте ещё раз: <code>Фамилия Имя Отчество</code>", [nav("me:prof")]), state="me:fio", state_data=data)
        _FIO_TRIES.pop(ctx.uid, None)
        status = "pending"
        await ctx.repo.update_user(ctx.uid, fio=res.fio, fio_status=status, fio_submitted_at=tu.now_ts())
        await ctx.repo.audit(ctx.uid, "fio_changed", status)
        ctx.user["fio"], ctx.user["fio_status"] = res.fio, status
        return Out(screen=Screen(f"ФИО обновлено: <b>{fm.esc(res.fio)}</b>\nСтатус: {_status_text(ctx)}", [nav("me:prof")]), clear_state=True)
    if state == "me:other":
        groups = await ctx.repo.search_groups(text)
        if not groups:
            return Out(screen=Screen("Не нашёл такую группу. Попробуйте ещё раз.", [nav("m:home")]),
                       state="me:other", state_data={})
        if len(groups) == 1:
            return Out(screen=await ls.day_screen(ctx, "today", groups[0]["id"]), clear_state=True)
        kb = [[Btn(g["name"], f"s:d:today:{g['id']}")] for g in groups[:6]] + [nav("m:home")]
        return Out(screen=Screen("Выберите группу:", kb), clear_state=True)
    if state == "me:findt":
        from app.bot import logic_find
        from app.services.nlu import extract_teacher

        known = await ctx.repo.known_surnames()
        query = extract_teacher(text, known)
        if not query:
            words = text.split()
            query = " ".join(words[:2]).lower() if words else ""
        scr = await logic_find.teacher_answer(ctx, query)
        scr.kb = [[Btn("🔎 Другой преподаватель", "me:findt")], nav("m:home")]
        return Out(screen=scr, clear_state=True)
    if state == "me:fb":
        ticket_id = int(data.get("ticket_id") or 0)
        if not ticket_id:
            return Out(screen=Screen("Сначала выберите или создайте обращение.", [[Btn("📨 Мои обращения", "me:fb")]]), clear_state=True)
        ticket = await ctx.repo.db.fetchone("SELECT id FROM support_tickets WHERE id = ? AND user_id = ?", ticket_id, ctx.uid)
        if not ticket:
            return Out(screen=Screen("Обращение не найдено. Откройте список обращений.", [[Btn("📨 Мои обращения", "me:fb")]]), clear_state=True)
        now = time.time()
        # В режиме диалога пользователь может отправлять несколько сообщений подряд.
        _FB_LAST[ctx.uid] = now
        await ctx.repo.db.execute(
            "INSERT INTO support_messages (user_id, sender_role, text, created_at, seen, ticket_id) VALUES (?, 'user', ?, ?, 0, ?)",
            ctx.uid, text[:3000], tu.now_ts(), ticket_id)
        return Out(screen=Screen(f"✅ Сообщение добавлено в обращение №{ticket_id}.\nМожете продолжить переписку или открыть историю.",
                                 [[Btn("💬 Открыть диалог", f"me:ticket:{ticket_id}")], [Btn("📨 Все обращения", "me:fb"), home_btn()]]),
                   state="me:fb", state_data={"ticket_id": ticket_id})
    return Out(screen=await more_menu(ctx), clear_state=True)
