"""Админ-панель: управление всей экосистемой бота через кнопки."""
from __future__ import annotations

from datetime import datetime

from app import timeutil as tu
from app.bot.core import ALL_PERMS, PERM_LABELS, Btn, Ctx, Kb, Out, Screen, home_btn, nav, pager
from app.providers import importer
from app.services import backup as bk
from app.services import export as ex
from app.services import format as fm
from app.services.fio import describe_reasons, short_name, validate_fio

PAGE = 6
DEFAULT_ADMIN_PERMS = ("users", "requests", "homework", "teachers", "stats")
BOOL_SETTINGS = {
    "rating_enabled": "Раздел «Преподаватели»",
    "hw_show_author": "Показывать автора задания",
    "maintenance": "Режим техработ",
    "fio_need_known_surname": "Автоподтверждение ФИО только для известных фамилий",
    "rate_only_own": "Оценивать только своих преподавателей",
    "sync_enabled": "Автосинхронизация расписания",
    "notify_changes": "Рассылать «изменения в расписании»",
    "group_require_start": "В группе требовать запуск бота в личке",
}
INT_SETTINGS = {
    "rate_cooldown_days": "Менять оценку не чаще (дней)",
    "min_votes": "Оценок для показа средней",
    "hw_daily_limit": "Заданий в сутки от одного студента",
    "fio_auto_delay_min": "Автопроверка ФИО через (мин)",
}
_RESTORE: dict[int, dict] = {}


def _deny() -> Out:
    return Out(toast="Недоступно", alert=True)


def _need(ctx: Ctx, perm: str | None = None, sup: bool = False) -> bool:
    if not ctx.is_admin:
        return False
    if sup:
        return ctx.is_super
    return perm is None or ctx.can(perm)


def _user_label(u: dict) -> str:
    name = u.get("fio") or u.get("tg_name") or "без имени"
    return f"{name[:22]} · {u['id']}"


async def menu_screen(ctx: Ctx) -> Screen:
    rows: Kb = []

    def add(pair: list[Btn]) -> None:
        if pair:
            rows.append(pair)

    pend_fio = await ctx.repo.count("users", "fio_status = 'pending'") if ctx.can("users") else 0
    pend_rq = await ctx.repo.count("head_requests", "status = 'pending'") if ctx.can("requests") else 0
    pend_hw = await ctx.repo.count("homework", "status = 'pending'") if ctx.can("homework") else 0
    add([Btn("📊 Статистика", "ad:stats")] if ctx.can("stats") else [])
    add([Btn("👥 Пользователи", "ad:u")] if ctx.can("users") else [])
    if ctx.is_admin:
        unread = int(await ctx.repo.db.scalar(
            "SELECT COUNT(*) FROM support_messages WHERE sender_role = 'user' AND seen = 0") or 0)
        add([Btn(f"💬 Диалоги с пользователями ({unread})", "ad:msg:0")])
    r2 = []
    if ctx.can("users"):
        r2.append(Btn(f"🛡 ФИО ({pend_fio})", "ad:fq:0"))
    add(r2)
    r3 = []
    if ctx.can("schedule"):
        r3.append(Btn("🗓 Расписание", "ad:sch"))
    if ctx.can("homework"):
        r3.append(Btn(f"📝 Задания ({pend_hw})", "ad:hw:0"))
    add(r3)
    r4 = []
    if ctx.can("teachers"):
        r4.append(Btn("⭐ Рейтинг", "ad:rt"))
    if ctx.can("broadcast"):
        r4.append(Btn("📣 Рассылка", "ad:bc"))
    add(r4)
    if ctx.can("users"):
        add([Btn("✍️ Словари", "ad:dict")])
    if ctx.is_super:
        add([Btn("📝 Тексты интерфейса", "ad:uitext")])
        add([Btn("⚙️ Настройки", "ad:set"), Btn("🧾 Аудит", "ad:aud")])
        add([Btn("💾 Бэкап", "ad:bk"), Btn("📤 Экспорт", "ad:ex")])
        add([Btn("🔐 Админы", "ad:adm")])
    rows.append([home_btn()])
    return Screen("<b>Админ-панель</b>", rows)


# ---------------- карточка пользователя ----------------
async def user_card(ctx: Ctx, uid: int) -> Out:
    u = await ctx.repo.get_user(uid)
    if not u:
        return Out(toast="Пользователь не найден", alert=True)
    g = await ctx.repo.get_group(u.get("group_id"))
    seen = datetime.fromtimestamp(int(u["last_seen"]), tu.tz()).strftime("%d.%m.%Y %H:%M")
    reg = datetime.fromtimestamp(int(u["created_at"]), tu.tz()).strftime("%d.%m.%Y")
    is_target_super = uid == ctx.cfg.superadmin_id
    role = {"admin": "админ"}.get(u["role"], "студент")
    if is_target_super and not ctx.is_super:
        role = "студент"  # главный админ скрыт от остальных
    lines = [f"<b>{fm.esc(u.get('fio') or 'ФИО не указано')}</b>",
             f"ID: <code>{uid}</code>" + (f" · @{fm.esc(u['username'])}" if u.get("username") else ""),
             f"Группа: {fm.esc(g['name']) if g else '—'}",
             f"ФИО: {u['fio_status']}", f"Роль: {role}",
             f"Бан: {'да 🚫' if u['banned'] else 'нет'}",
             f"Блок заявки на старосту: {'да' if u['head_blocked'] else 'нет'}" if ctx.is_super else "",
             f"Регистрация: {reg} · активность: {seen}"]
    kb: Kb = []
    if u["fio_status"] == "pending" and u.get("fio") and not (is_target_super and not ctx.is_super):
        chk = validate_fio(u["fio"], *await ctx.repo.stoplists(), ctx=await ctx.repo.fio_context())
        if chk.verdict == "reject":
            lines.append(f"Автопроверка: отклонила бы ({fm.esc(chk.message)})")
        elif chk.confident:
            lines.append("Автопроверка: все проверки пройдены, подтвердится после паузы")
        else:
            lines.append(f"Нужна ручная проверка: {fm.esc(describe_reasons(chk.code) or 'не хватает данных')}")
    if is_target_super and not ctx.is_super:
        kb.append(nav("ad:u"))
        return Out(screen=Screen("\n".join(x for x in lines if x), kb))
    protected = is_target_super or (u["role"] == "admin" and not ctx.is_super) or uid == ctx.uid
    if ctx.can("users") and not protected:
        kb.append([Btn("✅ Разбанить" if u["banned"] else "🚫 Забанить", f"ad:ub:{uid}")])
    if ctx.can("users"):
        if u["fio_status"] == "pending":
            kb.append([Btn("✅ Подтвердить ФИО", f"ad:ufo:{uid}:ok"), Btn("🔄 Сбросить ФИО", f"ad:ufo:{uid}:reset")])
        elif u.get("fio"):
            kb.append([Btn("🔄 Сбросить ФИО", f"ad:ufo:{uid}:reset")])
    if ctx.is_super:
        kb.append([Btn("⭐ Оценки пользователя", f"ad:ur:{uid}")])
    kb.append(nav("ad:menu"))
    return Out(screen=Screen("\n".join(x for x in lines if x), kb))


async def _resolve_user(ctx: Ctx, text: str) -> dict | None:
    u = await ctx.repo.find_user(text)
    if u:
        return u
    found = await ctx.repo.search_users_by_fio(text, 1)
    return found[0] if found else None


# ---------------- обработка нажатий ----------------
async def on_cb(ctx: Ctx, parts: list[str]) -> Out:
    if not ctx.is_admin:
        return _deny()
    act = parts[0] if parts else "menu"
    repo = ctx.repo
    arg = parts[1] if len(parts) > 1 else ""
    arg2 = parts[2] if len(parts) > 2 else ""

    if act == "menu":
        return Out(screen=await menu_screen(ctx), clear_state=True)
    if act in {"rq", "rqd", "hm"}:
        return Out(toast="Функции старост отключены", alert=True)
    if act == "uitext":
        if not ctx.is_super:
            return _deny()
        items = [("interface_main_text", "Текст главного экрана"), ("sponsor_button_title", "Название кнопки спонсора"), ("sponsor_button_url", "Ссылка кнопки спонсора"), ("unknown_text", "Текст при неизвестном вопросе"), ("welcome_text", "Приветствие при регистрации")]
        kb = [[Btn(label, f"ad:uitextedit:{key}")] for key, label in items]
        kb.append(nav("ad:menu"))
        return Out(screen=Screen("<b>Редактор текстов интерфейса</b>\nВыберите элемент. Для ссылки спонсора укажите полный https:// или t.me URL.", kb))
    if act == "uitextedit" and arg in {"interface_main_text", "sponsor_button_title", "sponsor_button_url", "unknown_text", "welcome_text"}:
        if not ctx.is_super:
            return _deny()
        current = repo.setting(arg) or "(не задано)"
        return Out(screen=Screen(f"Текущее значение:\n<code>{fm.esc(current[:1200])}</code>\n\nОтправьте новое значение одним сообщением. Чтобы очистить, отправьте дефис — будет использоваться значение по умолчанию.", [nav("ad:uitext")]), state="ad:uitext", state_data={"key": arg})

    # ---- обращения пользователей: единый диалог на каждого пользователя ----
    if act == "msg":
        page = int(arg) if arg.isdigit() else 0
        rows = await repo.db.fetchall(
            "SELECT user_id, MAX(id) AS last_id, SUM(CASE WHEN sender_role = 'user' AND seen = 0 THEN 1 ELSE 0 END) AS unread "
            "FROM support_messages GROUP BY user_id ORDER BY last_id DESC LIMIT 8 OFFSET ?", page * 8)
        total = int(await repo.db.scalar("SELECT COUNT(DISTINCT user_id) FROM support_messages") or 0)
        kb: Kb = []
        lines = ["<b>💬 Диалоги с пользователями</b>", "Выберите пользователя, чтобы прочитать историю и ответить."]
        for row in rows:
            u = await repo.get_user(int(row["user_id"]))
            label = (u.get("fio") or u.get("tg_name") or str(row["user_id"])) if u else str(row["user_id"])
            unread_n = int(row.get("unread") or 0)
            kb.append([Btn(("🟢 " if unread_n else "⚪ ") + f"{label[:24]} · {unread_n} новых", f"ad:msgread:{row['user_id']}")])
        if not rows:
            lines.append("\nПока обращений нет.")
        if total > 8:
            kb.append(pager("ad:msg", page, total, 8))
        kb.append(nav("ad:menu"))
        return Out(screen=Screen("\n".join(lines), kb))
    if act == "msgread" and arg.isdigit():
        uid = int(arg)
        u = await repo.get_user(uid)
        if not u:
            return Out(toast="Пользователь не найден", alert=True)
        await repo.db.execute("UPDATE support_messages SET seen = 1 WHERE user_id = ? AND sender_role = 'user'", uid)
        tickets = await repo.db.fetchall("SELECT id, created_at, status FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 10", uid)
        lines = [f"<b>💬 Обращения: {fm.esc(u.get('fio') or u.get('tg_name') or str(uid))}</b>",
                 f"ID: <code>{uid}</code>" + (f" · @{fm.esc(u['username'])}" if u.get("username") else ""),
                 "Выберите номер обращения, чтобы открыть историю и ответить."]
        kb = []
        for t in tickets:
            count = int(await repo.db.scalar("SELECT COUNT(*) FROM support_messages WHERE ticket_id = ?", t["id"]) or 0)
            kb.append([Btn(f"💬 Обращение №{t['id']} · {count} сообщ.", f"ad:msgticket:{uid}:{t['id']}")])
        if not tickets:
            lines.append("\nУ пользователя пока нет обращений.")
        else:
            latest = await repo.db.fetchall("SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY id DESC LIMIT 3", tickets[0]["id"])
            latest.reverse()
            for m in latest:
                who = "👤 Пользователь" if m["sender_role"] == "user" else "🛠 Админ"
                lines.append(f"\n{who}: {fm.esc(m['text'][:250])}")
        kb.append(nav("ad:msg:0"))
        return Out(screen=Screen("\n".join(lines), kb))
    if act == "msgticket" and arg.isdigit() and arg2.isdigit():
        uid, tid = int(arg), int(arg2)
        u = await repo.get_user(uid)
        ticket = await repo.db.fetchone("SELECT id FROM support_tickets WHERE id = ? AND user_id = ?", tid, uid)
        if not u or not ticket:
            return Out(toast="Обращение не найдено", alert=True)
        await repo.db.execute("UPDATE support_messages SET seen = 1 WHERE ticket_id = ? AND sender_role = 'user'", tid)
        history = await repo.db.fetchall("SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY id DESC LIMIT 20", tid)
        history.reverse()
        lines = [f"<b>💬 Обращение №{tid}: {fm.esc(u.get('fio') or u.get('tg_name') or str(uid))}</b>", f"ID: <code>{uid}</code>"]
        for m in history:
            stamp = datetime.fromtimestamp(int(m["created_at"]), tu.tz()).strftime("%d.%m %H:%M")
            who = "👤 Пользователь" if m["sender_role"] == "user" else "🛠 Админ"
            lines.append(f"\n{who} · {stamp}\n{fm.esc(m['text'][:700])}")
        kb = [[Btn("↩️ Ответить", f"ad:msgreply:{uid}:{tid}")], [Btn("🔄 Обновить", f"ad:msgticket:{uid}:{tid}")], [Btn("◀ К обращениям", f"ad:msgread:{uid}")]]
        return Out(screen=Screen("\n".join(lines)[:3900], kb))
    if act == "msgreply" and arg.isdigit():
        uid = int(arg)
        if not await repo.get_user(uid):
            return Out(toast="Пользователь не найден", alert=True)
        ticket = await repo.db.fetchone("SELECT id FROM support_tickets WHERE id = ? AND user_id = ?", int(arg2), uid) if arg2.isdigit() else await repo.db.fetchone("SELECT id FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 1", uid)
        if not ticket:
            tid = await repo.db.insert("INSERT INTO support_tickets (user_id, created_at, status) VALUES (?, ?, 'open')", uid, tu.now_ts())
        else:
            tid = int(ticket["id"])
        return Out(screen=Screen(f"Напишите ответ в обращение №{tid}. Сообщение придёт пользователю и будет удалено из чата через час; история останется в обращениях.",
                                 [nav(f"ad:msgread:{uid}")]), state="ad:msg_reply", state_data={"uid": uid, "ticket_id": tid})
    # ---- статистика ----
    if act == "stats":
        if not _need(ctx, "stats"):
            return _deny()
        s = await repo.stats()
        last = int(repo.setting("sync_last_ok") or 0)
        last_s = datetime.fromtimestamp(last, tu.tz()).strftime("%d.%m %H:%M") if last else "ещё не было"
        analytics = await repo.db.fetchall("SELECT event, COUNT(*) AS n FROM analytics_events WHERE created_at >= ? GROUP BY event ORDER BY n DESC", tu.now_ts() - 7 * 86400)
        popular = "\n".join(f"• {fm.esc(str(x['event']))}: {x['n']}" for x in analytics[:8]) or "нет данных"
        unanswered = int(await repo.db.scalar("SELECT COUNT(*) FROM analytics_events WHERE event = 'unanswered' AND created_at >= ?", tu.now_ts() - 7 * 86400) or 0)
        messages = int(await repo.db.scalar("SELECT COUNT(*) FROM analytics_events WHERE event = 'message' AND created_at >= ?", tu.now_ts() - 7 * 86400) or 0)
        ratio = (100 * unanswered / max(1, messages))
        text = (f"<b>Статистика</b>\nПользователей: {s['users']} (подтверждено ФИО: {s['verified']}, на проверке: {s['pending']})\n"
                f"Активных за сутки: {s['dau']} · за неделю: {s['wau']}\nАдмины: {s['admins']}\n"
                f"Группы: {s['groups']} · занятий в базе: {s['lessons']}\nПреподавателей: {s['teachers']} · оценок: {s['ratings']}\n"
                f"Заданий: {s['hw']} (на проверке: {s['hw_pending']})\nЗаблокировано: {s['banned']}\n\n<b>Аналитика за 7 дней</b>\nПопулярные события: {fm.esc(popular)}\nВопросы без ответа: {unanswered} · ориентировочная доля: {ratio:.1f}%\n"
                f"Синхронизация расписания: {last_s}")
        return Out(screen=Screen(text, [nav("ad:menu")]))

    # ---- пользователи ----
    if act == "u":
        if not _need(ctx, "users"):
            return _deny()
        if arg.isdigit():
            return await user_card(ctx, int(arg))
        return Out(screen=Screen("Введите @username, Telegram ID или часть ФИО.", [nav("ad:menu")]),
                   state="ad:user_search", state_data={})
    if act == "ub" and arg.isdigit():
        if not _need(ctx, "users"):
            return _deny()
        uid = int(arg)
        u = await repo.get_user(uid)
        if not u or uid == ctx.cfg.superadmin_id or uid == ctx.uid or (u["role"] == "admin" and not ctx.is_super):
            return _deny()
        await repo.update_user(uid, banned=0 if u["banned"] else 1)
        await repo.audit(ctx.uid, "ban" if not u["banned"] else "unban", str(uid))
        return await user_card(ctx, uid)
    if act == "ufo" and arg.isdigit() and arg2 in ("ok", "reset"):
        if not _need(ctx, "users"):
            return _deny()
        uid = int(arg)
        u = await repo.get_user(uid)
        if not u:
            return Out(toast="Пользователь не найден", alert=True)
        out: Out
        if arg2 == "ok" and u.get("fio"):
            await repo.update_user(uid, fio_status="verified")
            out = await user_card(ctx, uid)
            out.notify = [(uid, Screen("✅ Ваше ФИО подтверждено. Теперь доступны задания и оценки преподавателей."))]
        else:
            await repo.update_user(uid, fio=None, fio_status="none")
            out = await user_card(ctx, uid)
            out.notify = [(uid, Screen("Администратор попросил указать ФИО заново. Нажмите /start."))]
        await repo.audit(ctx.uid, f"fio_{arg2}", str(uid))
        return out
    if act == "uh" and arg.isdigit():
        if not _need(ctx, "requests"):
            return _deny()
        uid = int(arg)
        u = await repo.get_user(uid)
        if not u or u["role"] == "admin" or uid == ctx.cfg.superadmin_id:
            return _deny()
        if u["role"] == "head":
            await repo.update_user(uid, role="student")
            await repo.audit(ctx.uid, "head_remove", str(uid))
            out = await user_card(ctx, uid)
            out.notify = [(uid, Screen("Роль старосты снята администратором."))]
            return out
        if not u.get("group_id"):
            return Out(toast="У пользователя нет группы", alert=True)
        await repo.update_user(uid, role="head")
        await repo.audit(ctx.uid, "head_assign", str(uid))
        out = await user_card(ctx, uid)
        out.notify = [(uid, Screen("🎉 Вы назначены старостой группы. Откройте «Ещё → Панель старосты»."))]
        return out
    if act == "uc" and arg.isdigit():
        if not _need(ctx, sup=True):
            return _deny()
        await repo.update_user(int(arg), head_blocked=0)
        await repo.audit(ctx.uid, "head_unblock", arg)
        return await user_card(ctx, int(arg))
    if act == "ur" and arg.isdigit():
        if not _need(ctx, sup=True):
            return _deny()
        rows = await repo.user_ratings(int(arg))
        lines = [f"<b>Оценки пользователя {arg}</b>"]
        if rows:
            lines += [f"{'⭐' * r['stars']} · {fm.esc(r['name'])}" for r in rows[:30]]
        else:
            lines.append("Оценок нет.")
        return Out(screen=Screen("\n".join(lines), [nav(f"ad:u:{arg}")]))
    if act == "fq":
        if not _need(ctx, "users"):
            return _deny()
        page = int(arg) if arg.isdigit() else 0
        total = await repo.count("users", "fio_status = 'pending'")
        rows = await repo.pending_fio(PAGE, page * PAGE)
        kb: Kb = []
        for u in rows:
            g = await repo.get_group(u.get("group_id"))
            kb.append([Btn(f"{(u.get('fio') or '')[:24]} · {g['name'] if g else '—'}", f"ad:u:{u['id']}")])
        if total > PAGE:
            kb.append(pager("ad:fq", page, total, PAGE))
        kb.append(nav("ad:menu"))
        return Out(screen=Screen(f"<b>ФИО на проверке: {total}</b>" + ("" if rows else "\nОчередь пуста."), kb))

    # ---- заявки старост ----
    if act == "rq":
        if not _need(ctx, "requests"):
            return _deny()
        reqs = await repo.pending_requests(6)
        lines = [f"<b>Заявки на старосту: {len(reqs)}</b>"]
        kb = []
        for r in reqs:
            u = await repo.get_user(r["user_id"])
            g = await repo.get_group(r["group_id"])
            who = (u.get("fio") if u else None) or str(r["user_id"])
            lines.append(f"• {fm.esc(who)} · {fm.esc(g['name']) if g else '—'}")
            kb.append([Btn(f"✅ {who[:16]}", f"ad:rqd:{r['id']}:ok"), Btn("❌", f"ad:rqd:{r['id']}:no"),
                       Btn("👤", f"ad:u:{r['user_id']}")])
        if not reqs:
            lines.append("Заявок нет.")
        kb.append([Btn("➕ Назначить по @username/ID", "ad:hm")])
        kb.append(nav("ad:menu"))
        return Out(screen=Screen("\n".join(lines), kb))
    if act == "rqd" and arg.isdigit() and arg2 in ("ok", "no"):
        if not _need(ctx, "requests"):
            return _deny()
        req = await repo.get_request(int(arg))
        if not req:
            return Out(toast="Заявка не найдена", alert=True)
        if req["status"] != "pending":
            return Out(screen=Screen("Эта заявка уже обработана.", [nav("ad:rq")]), toast="Уже обработана")
        u = await repo.get_user(req["user_id"])
        if not u:
            return Out(toast="Пользователь не найден", alert=True)
        if not await repo.decide_request(req["id"], "approved" if arg2 == "ok" else "rejected", ctx.uid):
            return Out(toast="Уже обработана", alert=True)
        if arg2 == "ok":
            if u["role"] == "student" and u.get("group_id"):
                await repo.update_user(u["id"], role="head")
            await repo.audit(ctx.uid, "head_approve", str(u["id"]))
            note = "🎉 Заявка одобрена: вы теперь староста. Откройте «Ещё → Панель старосты»."
        else:
            await repo.update_user(u["id"], head_blocked=1)
            await repo.audit(ctx.uid, "head_reject", str(u["id"]))
            note = "К сожалению, заявка на старосту отклонена."
        out = Out(screen=Screen("Решение сохранено ✅", [nav("ad:rq")]), toast="Готово")
        out.notify = [(u["id"], Screen(note))]
        return out
    if act == "hm":
        if not _need(ctx, "requests"):
            return _deny()
        return Out(screen=Screen("Введите @username или Telegram ID пользователя, которого нужно назначить старостой.",
                                 [nav("ad:rq")]), state="ad:head_assign", state_data={})

    # ---- расписание ----
    if act == "sch":
        if not _need(ctx, "schedule"):
            return _deny()
        last = int(repo.setting("sync_last_ok") or 0)
        last_s = datetime.fromtimestamp(last, tu.tz()).strftime("%d.%m.%Y %H:%M") if last else "ещё не было"
        err = repo.setting("sync_last_error")
        text = (f"<b>Расписание</b>\nИсточник: {fm.esc(ctx.cfg.schedule_source_url)}\nПоследняя успешная синхронизация: {last_s}\n"
                f"Последнее число занятий: {repo.setting('sync_last_count') or '—'}\n"
                f"Неудач подряд: {repo.setting('sync_fail_count') or 0}" + (f"\nОшибка: {fm.esc(err)}" if err else "") +
                f"\nЧётность недель: {'настроена' if repo.setting('parity_anchor') else 'не настроена'}")
        kb = [[Btn("🔄 Синхронизировать сейчас", "ad:sync")], [Btn("📥 Загрузить файл", "ad:imp"), Btn("➕ Группы", "ad:grp")],
              [Btn("🕘 Снимки", "ad:snap"), Btn("📅 Чётность", "ad:par")],
              [Btn("👥 Справочник преподавателей", "ad:dir")], nav("ad:menu")]
        return Out(screen=Screen(text, kb))
    if act == "sync":
        if not _need(ctx, "schedule"):
            return _deny()
        sync = ctx.services.get("sync")
        if sync is None:
            return Out(toast="Синхронизация недоступна", alert=True)
        spawn, alert = ctx.services.get("spawn"), ctx.services.get("alert")
        if spawn and alert:  # в боте: запускаем в фоне, иначе долгая синхронизация держит очередь админа
            async def _job() -> None:
                r = await sync.run_once()
                await repo.audit(ctx.uid, "sync_now", r.message[:200])
                await alert(("✅ " if r.ok else "⚠️ ") + "Синхронизация: " + r.message)
            spawn(_job())
            return Out(screen=Screen("🔄 Синхронизация запущена в фоне. Результат пришлю сообщением — бот пока работает как обычно.",
                                     [nav("ad:sch")]))
        rep = await sync.run_once()
        await repo.audit(ctx.uid, "sync_now", rep.message[:200])
        text = ("✅ " if rep.ok else "⚠️ ") + fm.esc(rep.message)
        if not rep.ok:
            text += "\n\nБот продолжает показывать сохранённое расписание. Можно загрузить файл вручную."
        return Out(screen=Screen(text, [nav("ad:sch")]))
    if act == "dir":
        if not _need(ctx, "schedule"):
            return _deny()
        n_staff, n_units, n_rooms = await repo.directory_counts()
        last = int(repo.setting("dir_last_ok") or 0)
        last_s = datetime.fromtimestamp(last, tu.tz()).strftime("%d.%m.%Y %H:%M") if last else "ещё не было"
        err = repo.setting("dir_error")
        text = (f"<b>Справочник преподавателей</b>\nИсточник: {fm.esc(ctx.cfg.directory_url)} "
                f"(режим: {'файл' if repo.setting('dir_source') == 'file' else 'сайт'})\n"
                f"Преподавателей: {n_staff} · подразделений: {n_units} · с кабинетом: {n_rooms}\n"
                f"Обновлено: {last_s}" + (f"\nОшибка: {fm.esc(err)}" if err else "") +
                "\n\nСправочник нужен, чтобы отвечать «где найти преподавателя»: подразделение и кабинет.")
        kb = [[Btn("🔄 Обновить с сайта", "ad:dirsync")], [Btn("📥 Загрузить файлом", "ad:dirimp")], nav("ad:sch")]
        return Out(screen=Screen(text, kb))
    if act == "dirsync":
        if not _need(ctx, "schedule"):
            return _deny()
        svc = ctx.services.get("directory")
        if svc is None:
            return Out(toast="Недоступно", alert=True)
        spawn, alert = ctx.services.get("spawn"), ctx.services.get("alert")
        if spawn and alert:
            async def _djob() -> None:
                ok2, msg2 = await svc.run_once()
                await repo.audit(ctx.uid, "dir_sync", msg2[:200])
                await alert(("✅ " if ok2 else "⚠️ ") + "Справочник: " + msg2)
            spawn(_djob())
            return Out(screen=Screen("🔄 Обновление справочника запущено в фоне. Результат пришлю сообщением.", [nav("ad:dir")]))
        ok, msg = await svc.run_once()
        await repo.audit(ctx.uid, "dir_sync", msg[:200])
        text = ("✅ " if ok else "⚠️ ") + fm.esc(msg)
        if not ok:
            text += "\n\nБот продолжает использовать сохранённый справочник. Можно загрузить его файлом."
        return Out(screen=Screen(text, [nav("ad:dir")]))
    if act == "dirimp":
        if not _need(ctx, "schedule"):
            return _deny()
        return Out(screen=Screen("Пришлите файл .xlsx или .csv с колонками: <code>ФИО;Подразделение;Кабинет</code> "
                                 "(подробнее в docs/IMPORT_FORMAT.md). Автообновление с сайта после этого отключится, "
                                 "пока вы не нажмёте «Обновить с сайта».", [nav("ad:dir")]),
                   state="ad:dir_import", state_data={})
    if act == "imp":
        if not _need(ctx, "schedule"):
            return _deny()
        return Out(screen=Screen("Пришлите файл .xlsx или .csv с расписанием. Колонки: группа, дата, пара, начало, конец, "
                                 "предмет, преподаватель, аудитория, тип, подгруппа (подробнее в docs/IMPORT_FORMAT.md).",
                                 [nav("ad:sch")]), state="ad:import", state_data={})
    if act == "grp":
        if not _need(ctx, "schedule"):
            return _deny()
        return Out(screen=Screen("Введите названия групп через запятую или с новой строки, например: ИС-11, ИС-12.",
                                 [nav("ad:sch")]), state="ad:group_add", state_data={})
    if act == "snap":
        if not _need(ctx, "schedule"):
            return _deny()
        snaps = await repo.list_snapshots()
        kb = [[Btn(f"↩ {datetime.fromtimestamp(int(s['ts']), tu.tz()).strftime('%d.%m %H:%M')} · {s['source']}",
                   f"ad:snr:{s['id']}")] for s in snaps[:5]]
        kb.append(nav("ad:sch"))
        return Out(screen=Screen("<b>Снимки расписания</b>\nОткат заменяет данные сайта выбранным снимком "
                                 "(ручные пары не затрагиваются)." + ("" if snaps else "\nСнимков пока нет."), kb))
    if act == "snr" and arg.isdigit():
        if not _need(ctx, "schedule"):
            return _deny()
        if arg2 != "y":
            return Out(screen=Screen("Откатить расписание к этому снимку?",
                                     [[Btn("Да, откатить", f"ad:snr:{arg}:y"), Btn("Отмена", "ad:snap")]]))
        sync = ctx.services.get("sync")
        ok = bool(sync) and await sync.rollback(int(arg))
        await repo.audit(ctx.uid, "snapshot_rollback", arg)
        return Out(screen=Screen("Откат выполнен ✅" if ok else "Снимок не найден.", [nav("ad:sch")]))
    if act == "par":
        if not _need(ctx, "schedule"):
            return _deny()
        return Out(screen=Screen("Введите дату любого дня <b>нечётной</b> недели (ДД.ММ.ГГГГ). «-» отключает показ чётности.",
                                 [nav("ad:sch")]), state="ad:parity", state_data={})

    # ---- задания ----
    if act == "hw":
        if not _need(ctx, "homework"):
            return _deny()
        page = int(arg) if arg.isdigit() else 0
        rows, total = await repo.pending_hw(None, PAGE, page * PAGE)
        kb = []
        for r in rows:
            g = await repo.get_group(r["group_id"])
            kb.append([Btn(f"{g['name'] if g else ''} · {r['subject'][:14]}: {r['text'][:14]}", f"h:v:{r['id']}")])
        if total > PAGE:
            kb.append(pager("ad:hw", page, total, PAGE))
        kb.append(nav("ad:menu"))
        return Out(screen=Screen(f"<b>Задания на проверке: {total}</b>" + ("" if rows else "\nОчередь пуста."), kb))

    # ---- рейтинг ----
    if act == "rt":
        if not _need(ctx, "teachers"):
            return _deny()
        on = repo.flag("rating_enabled")
        kb = [[Btn("🙈 Скрыть раздел у всех" if on else "👁 Показать раздел", "ad:rte")],
              [Btn("🔎 Найти преподавателя", "ad:rts")], nav("ad:menu")]
        return Out(screen=Screen(f"<b>Рейтинг преподавателей</b>\nРаздел сейчас: {'включён ✅' if on else 'скрыт 🙈'}", kb))
    if act == "rte":
        if not _need(ctx, "teachers"):
            return _deny()
        new = "0" if repo.flag("rating_enabled") else "1"
        await repo.set_setting("rating_enabled", new)
        await repo.audit(ctx.uid, "rating_toggle", new)
        return await on_cb(ctx, ["rt"])
    if act == "rts":
        if not _need(ctx, "teachers"):
            return _deny()
        return Out(screen=Screen("Введите фамилию преподавателя.", [nav("ad:rt")]), state="ad:teacher_search", state_data={})
    if act == "rtc" and arg.isdigit():
        if not _need(ctx, "teachers"):
            return _deny()
        t = await repo.get_teacher(int(arg))
        if not t:
            return Out(toast="Не найден", alert=True)
        avg = f"{t['avg']:.2f}" if t["avg"] is not None else "—"
        text = (f"<b>{fm.esc(t['name'])}</b>\nОценок: {t['cnt']} · средняя: {avg}\n"
                f"Статус: {'скрыт 🙈' if t['hidden'] else 'виден'}")
        kb = [[Btn("👁 Показать" if t["hidden"] else "🙈 Скрыть", f"ad:rth:{t['id']}")],
              [Btn("🧹 Сбросить оценки", f"ad:rtr:{t['id']}")], nav("ad:rt")]
        return Out(screen=Screen(text, kb))
    if act == "rth" and arg.isdigit():
        if not _need(ctx, "teachers"):
            return _deny()
        t = await repo.get_teacher(int(arg))
        if not t:
            return Out(toast="Не найден", alert=True)
        await repo.set_teacher_hidden(t["id"], not t["hidden"])
        await repo.audit(ctx.uid, "teacher_hide", f"{t['id']}:{not t['hidden']}")
        return await on_cb(ctx, ["rtc", arg])
    if act == "rtr" and arg.isdigit():
        if not _need(ctx, "teachers"):
            return _deny()
        if arg2 != "y":
            return Out(screen=Screen("Удалить все оценки этого преподавателя? Это нельзя отменить.",
                                     [[Btn("Да, сбросить", f"ad:rtr:{arg}:y"), Btn("Отмена", f"ad:rtc:{arg}")]]))
        n = await repo.reset_ratings(int(arg))
        await repo.audit(ctx.uid, "ratings_reset", f"{arg}:{n}")
        return Out(screen=Screen(f"Удалено оценок: {n}", [nav(f"ad:rtc:{arg}")]))

    # ---- рассылка ----
    if act == "bc":
        if not _need(ctx, "broadcast"):
            return _deny()
        kb = [[Btn("👥 Всем пользователям", "ad:bca:all")], [Btn("🏫 Конкретной группе", "ad:bca:grp")], nav("ad:menu")]
        return Out(screen=Screen("<b>📣 Рассылка</b>\nВыберите аудиторию. Можно отправить текст или фото с подписью. После предпросмотра бот попросит подтвердить отправку.", kb), clear_state=True)
    if act == "bca":
        if not _need(ctx, "broadcast"):
            return _deny()
        if arg == "grp":
            return Out(screen=Screen("Введите название группы.", [nav("ad:bc")]), state="ad:bc_group", state_data={})
        if arg in ("all", "heads"):
            return Out(screen=Screen("Напишите текст рассылки одним сообщением.", [nav("ad:bc")]),
                       state="ad:bc_text", state_data={"aud": arg})
    if act == "bcp":
        if not _need(ctx, "broadcast"):
            return _deny()
        state, data = await repo.get_state(ctx.uid)
        if state != "ad:bc_text" or not data.get("media_file_id"):
            return Out(toast="Фото-черновик не найден", alert=True)
        n = len(await _recipients(ctx, data))
        data["text"] = ""
        return Out(screen=Screen(f"<b>Предпросмотр рассылки</b>\n\n📷 Фото без подписи\nПолучателей: {n}",
                                 [[Btn(f"✅ Отправить ({n})", "ad:bcy"), Btn("❌ Отмена", "ad:bc")]]),
                   state="ad:bc_confirm", state_data=data)

    if act == "bcy":
        if not _need(ctx, "broadcast"):
            return _deny()
        state, data = await repo.get_state(ctx.uid)
        if state != "ad:bc_confirm" or (not data.get("text") and not data.get("media_file_id")):
            return Out(toast="Черновик устарел", alert=True)
        recipients = await _recipients(ctx, data)
        text = "📣 " + fm.esc(data.get("text", ""))
        await repo.audit(ctx.uid, "broadcast", f"{data.get('aud')}:{len(recipients)}")
        out = Out(screen=Screen(f"Рассылка поставлена в очередь: получателей {len(recipients)}.", [nav("ad:menu")]),
                  clear_state=True)
        if data.get("media_file_id"):
            caption = text[:900] if text.strip() else "📣 Сообщение от администрации"
            out.notify_media = [(uid, data["media_file_id"], data.get("media_type", "photo"), caption) for uid in recipients]
        else:
            out.notify = [(uid, Screen(text)) for uid in recipients]
        return out

    # ---- редактор текстов интерфейса ----
    if act == "uitext":
        if not _need(ctx, sup=True): return _deny()
        keys = {"welcome_text": "Приветствие", "unknown_text": "Подсказка при непонимании", "hw_intro_text": "Подсказка заданий"}
        kb = [[Btn(label, f"ad:utkey:{key}")] for key, label in keys.items()]
        kb.append(nav("ad:set"))
        return Out(screen=Screen("<b>Редактор текстов интерфейса</b>\nВыберите текст. Пустое значение сбрасывает его к стандартному.", kb))
    if act == "utkey" and arg in ("welcome_text", "unknown_text", "hw_intro_text"):
        if not _need(ctx, sup=True): return _deny()
        return Out(screen=Screen("Отправьте новый текст (до 1000 символов). Для сброса отправьте дефис -.", [nav("ad:uitext")]), state="ad:uitext_val", state_data={"key": arg})

    # ---- настройки ----
    if act == "set":
        if not _need(ctx, sup=True):
            return _deny()
        return Out(screen=_settings_screen(ctx))
    if act == "st" and arg in BOOL_SETTINGS:
        if not _need(ctx, sup=True):
            return _deny()
        new = "0" if repo.flag(arg) else "1"
        await repo.set_setting(arg, new)
        await repo.audit(ctx.uid, "setting", f"{arg}={new}")
        return Out(screen=_settings_screen(ctx))
    if act == "sv" and arg in INT_SETTINGS:
        if not _need(ctx, sup=True):
            return _deny()
        return Out(screen=Screen(f"{INT_SETTINGS[arg]}.\nСейчас: {repo.setting(arg)}. Введите число от 1 до 365.",
                                 [nav("ad:set")]), state="ad:set_val", state_data={"key": arg})
    if act == "aud":
        if not _need(ctx, sup=True):
            return _deny()
        rows = await repo.list_audit(15)
        lines = ["<b>Журнал действий</b>"]
        for r in rows:
            when = datetime.fromtimestamp(int(r["ts"]), tu.tz()).strftime("%d.%m %H:%M")
            lines.append(f"{when} · {r['actor']} · {fm.esc(r['action'])} {fm.esc(r['details'])}")
        return Out(screen=Screen("\n".join(lines)[:3900], [nav("ad:menu")]))

    # ---- бэкап и экспорт ----
    if act == "bk":
        if not _need(ctx, sup=True):
            return _deny()
        kb = [[Btn("💾 Сделать бэкап сейчас", "ad:bkn")], [Btn("♻️ Восстановить из файла", "ad:bkr")], nav("ad:menu")]
        return Out(screen=Screen("<b>Резервные копии</b>\nБот присылает файл один раз при первом запуске и дальше сам заменяет его в этом же сообщении (раз в сутки и примерно раз в час после изменений) — чат не засоряется. Предыдущие версии хранятся на сервере в папке бэкапов.", kb))
    if act == "bkn":
        if not _need(ctx, sup=True):
            return _deny()
        name, blob = await bk.make_backup(repo)
        await repo.audit(ctx.uid, "backup_manual", name)
        return Out(file=(name, blob, "Резервная копия базы бота"), toast="Бэкап отправлен")
    if act == "bkr":
        if not _need(ctx, sup=True):
            return _deny()
        return Out(screen=Screen("Пришлите файл бэкапа (.json.gz). ⚠️ Восстановление заменит ВСЕ текущие данные.",
                                 [nav("ad:bk")]), state="ad:restore", state_data={})
    if act == "bky":
        if not _need(ctx, sup=True):
            return _deny()
        dump = _RESTORE.pop(ctx.uid, None)
        if not dump:
            return Out(toast="Файл устарел, загрузите заново", alert=True)
        try:
            counts = await repo.restore(dump)
        except Exception as e:  # откат транзакции уже произошёл, данные не тронуты
            return Out(screen=Screen(f"Не удалось восстановить: {fm.esc(str(e)[:200])}\nТекущие данные не изменены.",
                                     [nav("ad:bk")]), clear_state=True)
        await repo.audit(ctx.uid, "restore", str(sum(counts.values())))
        return Out(screen=Screen(f"Восстановлено записей: {sum(counts.values())} ✅", [nav("ad:bk")]), clear_state=True)
    if act == "ex":
        if not _need(ctx, sup=True):
            return _deny()
        if arg in ("users", "ratings", "homework"):
            name, blob = await ex.export_xlsx(repo, arg)
            await repo.audit(ctx.uid, "export", arg)
            return Out(file=(name, blob, "Выгрузка данных"), toast="Файл отправлен")
        kb = [[Btn("👥 Пользователи", "ad:ex:users"), Btn("⭐ Оценки", "ad:ex:ratings")],
              [Btn("📝 Задания", "ad:ex:homework")], nav("ad:menu")]
        return Out(screen=Screen("<b>Экспорт в Excel</b>\nФайл придёт сообщением и не хранится на сервере.", kb))

    # ---- админы ----
    if act == "adm":
        if not _need(ctx, sup=True):
            return _deny()
        if arg.isdigit():
            return await _admin_card(ctx, int(arg))
        admins = await repo.users_with_role("admin")
        kb = [[Btn(_user_label(a), f"ad:adm:{a['id']}")] for a in admins[:10]]
        kb.append([Btn("➕ Добавить админа", "ad:adma")])
        kb.append(nav("ad:menu"))
        return Out(screen=Screen(f"<b>Администраторы: {len(admins)}</b>", kb))
    if act == "adma":
        if not _need(ctx, sup=True):
            return _deny()
        return Out(screen=Screen("Введите @username или Telegram ID (человек должен уже запускать бота).", [nav("ad:adm")]),
                   state="ad:admin_add", state_data={})
    if act == "admp" and arg.isdigit() and arg2 in ALL_PERMS:
        if not _need(ctx, sup=True):
            return _deny()
        u = await repo.get_user(int(arg))
        if not u or u["role"] != "admin":
            return _deny()
        perms = {p for p in (u["admin_perms"] or "").split(",") if p}
        perms ^= {arg2}
        await repo.update_user(u["id"], admin_perms=",".join(p for p in ALL_PERMS if p in perms))
        await repo.audit(ctx.uid, "admin_perm", f"{arg}:{arg2}")
        return await _admin_card(ctx, int(arg))
    if act == "admd" and arg.isdigit():
        if not _need(ctx, sup=True):
            return _deny()
        u = await repo.get_user(int(arg))
        if not u or u["role"] != "admin":
            return _deny()
        await repo.update_user(u["id"], role="student", admin_perms="")
        await repo.audit(ctx.uid, "admin_remove", arg)
        out = Out(screen=Screen("Админ снят ✅", [nav("ad:adm")]))
        out.notify = [(u["id"], Screen("Права администратора сняты."))]
        return out

    # ---- словари ----
    if act == "dict":
        if not _need(ctx, "users"):
            return _deny()
        kb = [[Btn("🚫 Заглушка ФИО", "ad:sw:stub"), Btn("🤬 Запрещённая основа", "ad:sw:bad")],
              [Btn("📋 Стоп-лист", "ad:swl")], [Btn("🔤 Синонимы предметов", "ad:al")], nav("ad:menu")]
        return Out(screen=Screen("<b>Словари</b>\nСтоп-листы проверки ФИО и синонимы предметов для вопросов текстом.", kb))
    if act == "sw" and arg in ("stub", "bad"):
        if not _need(ctx, "users"):
            return _deny()
        what = "слово-заглушку (его нельзя использовать в ФИО)" if arg == "stub" else "запрещённую основу слова"
        return Out(screen=Screen(f"Введите {what}.", [nav("ad:dict")]), state="ad:sw_add", state_data={"kind": arg})
    if act == "swl":
        if not _need(ctx, "users"):
            return _deny()
        rows = await repo.list_stopwords()
        kb = [[Btn(f"🗑 {r['word'][:20]} ({r['kind']})", f"ad:swd:{i}")] for i, r in enumerate(rows[:15])]
        kb.append(nav("ad:dict"))
        return Out(screen=Screen("<b>Ваш стоп-лист</b> (встроенные списки не показаны)" + ("" if rows else "\nПусто."), kb))
    if act == "swd" and arg.isdigit():
        if not _need(ctx, "users"):
            return _deny()
        rows = await repo.list_stopwords()
        if int(arg) < len(rows):
            await repo.del_stopword(rows[int(arg)]["word"])
        return await on_cb(ctx, ["swl"])
    if act == "al":
        if not _need(ctx, "users"):
            return _deny()
        rows = await repo.list_aliases()
        kb = [[Btn(f"🗑 {r['alias'][:16]} → {r['subject'][:16]}", f"ad:ald:{i}")] for i, r in enumerate(rows[:15])]
        kb.append([Btn("➕ Добавить синоним", "ad:ala")])
        kb.append(nav("ad:dict"))
        return Out(screen=Screen("<b>Синонимы предметов</b>" + ("" if rows else "\nПока нет."), kb))
    if act == "ala":
        if not _need(ctx, "users"):
            return _deny()
        return Out(screen=Screen("Введите синоним и предмет через «=», например: <code>матеша = Математика</code>",
                                 [nav("ad:al")]), state="ad:alias_add", state_data={})
    if act == "ald" and arg.isdigit():
        if not _need(ctx, "users"):
            return _deny()
        rows = await repo.list_aliases()
        if int(arg) < len(rows):
            await repo.del_alias(rows[int(arg)]["alias"])
        return await on_cb(ctx, ["al"])
    return Out(toast="Неизвестное действие")


def _settings_screen(ctx: Ctx) -> Screen:
    kb: Kb = []
    for key, label in BOOL_SETTINGS.items():
        kb.append([Btn(f"{'✅' if ctx.repo.flag(key) else '⬜'} {label}", f"ad:st:{key}")])
    for key, label in INT_SETTINGS.items():
        kb.append([Btn(f"{label}: {ctx.repo.setting(key)}", f"ad:sv:{key}")])
    kb.append([Btn("📝 Редактор текстов интерфейса", "ad:uitext")])
    kb.append(nav("ad:menu"))
    return Screen("<b>Настройки</b>\nИзменения применяются сразу, перезапуск не нужен.", kb)


async def _admin_card(ctx: Ctx, uid: int) -> Out:
    u = await ctx.repo.get_user(uid)
    if not u or u["role"] != "admin":
        return Out(toast="Не найден", alert=True)
    perms = {p for p in (u["admin_perms"] or "").split(",") if p}
    kb: Kb = [[Btn(f"{'✅' if p in perms else '⬜'} {PERM_LABELS[p]}", f"ad:admp:{uid}:{p}")] for p in ALL_PERMS]
    kb.append([Btn("🗑 Снять с должности", f"ad:admd:{uid}")])
    kb.append(nav("ad:adm"))
    return Out(screen=Screen(f"<b>{fm.esc(u.get('fio') or u.get('tg_name') or str(uid))}</b> · {uid}\n"
                             "Отметьте, что разрешено этому админу. Экспорт, бэкапы, настройки и управление "
                             "админами всегда только у вас.", kb))


async def _recipients(ctx: Ctx, data: dict) -> list[int]:
    repo = ctx.repo
    aud = data.get("aud")
    if aud == "all":
        rows = await repo.db.fetchall("SELECT id FROM users WHERE banned = 0 AND bot_blocked = 0")
    elif aud == "heads":
        rows = await repo.db.fetchall("SELECT id FROM users WHERE role = 'head' AND banned = 0 AND bot_blocked = 0")
    else:
        rows = await repo.db.fetchall(
            "SELECT id FROM users WHERE group_id = ? AND banned = 0 AND bot_blocked = 0", data.get("gid"))
    return [r["id"] for r in rows]


# ---------------- ввод текста ----------------
async def on_text(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if not ctx.is_admin:
        return _deny()
    repo = ctx.repo
    if state == "ad:uitext" and ctx.is_super:
        key = str(data.get("key") or "")
        allowed = {"interface_main_text", "sponsor_button_title", "sponsor_button_url", "unknown_text", "welcome_text"}
        if key not in allowed:
            return Out(screen=Screen("Элемент не найден.", [nav("ad:uitext")]), clear_state=True)
        value = "" if text.strip() == "-" else text.strip()
        if key == "sponsor_button_url" and value and not (value.startswith("https://") or value.startswith("http://") or value.startswith("tg://")):
            return Out(screen=Screen("Ссылка должна начинаться с https://, http:// или tg://", [nav("ad:uitext")]), state=state, state_data=data)
        if len(value) > 3500:
            return Out(screen=Screen("Слишком длинный текст (максимум 3500 символов)."), state=state, state_data=data)
        await repo.set_setting(key, value)
        await repo.audit(ctx.uid, "interface_text_edit", key)
        return Out(screen=Screen("✅ Текст сохранён.", [nav("ad:uitext")]), clear_state=True)
    if state == "ad:msg_reply":
        try:
            uid = int(data.get("uid"))
        except (TypeError, ValueError):
            return Out(screen=Screen("Диалог устарел. Откройте его снова.", [nav("ad:msg:0")]), clear_state=True)
        if not await repo.get_user(uid):
            return Out(screen=Screen("Пользователь не найден.", [nav("ad:msg:0")]), clear_state=True)
        ticket_id = int(data.get("ticket_id") or 0)
        if not ticket_id:
            ticket = await repo.db.fetchone("SELECT id FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 1", uid)
            if not ticket:
                ticket_id = await repo.db.insert("INSERT INTO support_tickets (user_id, created_at, status) VALUES (?, ?, 'open')", uid, tu.now_ts())
            else:
                ticket_id = int(ticket["id"])
        await repo.db.execute(
            "INSERT INTO support_messages (user_id, sender_role, text, created_at, seen, ticket_id) VALUES (?, 'admin', ?, ?, 1, ?)",
            uid, text[:3000], tu.now_ts(), ticket_id)
        out = Out(screen=Screen("✅ Ответ сохранён и отправлен пользователю. Сообщение в личном чате удалится через час, история останется в обращении.", [nav(f"ad:msgread:{uid}")]), clear_state=True)
        out.notify_timed = [(uid, Screen(f"💬 <b>Ответ администратора · обращение №{ticket_id}</b>\n\n{fm.esc(text[:3000])}\n\nИстория переписки доступна в кнопке «📨 Написать админу»."), 3600)]
        return out
    if state == "ad:user_search" and ctx.can("users"):
        u = await _resolve_user(ctx, text)
        if not u:
            return Out(screen=Screen("Не нашёл. Введите @username, ID или часть ФИО.", [nav("ad:menu")]),
                       state="ad:user_search", state_data={})
        out = await user_card(ctx, u["id"])
        out.clear_state = True
        return out
    if state == "ad:head_assign" and ctx.can("requests"):
        u = await repo.find_user(text)
        if not u or not u.get("group_id") or u["role"] == "admin" or u["id"] == ctx.cfg.superadmin_id:
            return Out(screen=Screen("Пользователь не найден или ещё не выбрал группу в боте. Попробуйте ещё раз.",
                                     [nav("ad:rq")]), state="ad:head_assign", state_data={})
        await repo.update_user(u["id"], role="head")
        await repo.audit(ctx.uid, "head_assign", str(u["id"]))
        out = await user_card(ctx, u["id"])
        out.clear_state = True
        out.notify = [(u["id"], Screen("🎉 Вы назначены старостой группы. Откройте «Ещё → Панель старосты»."))]
        return out
    if state == "ad:group_add" and ctx.can("schedule"):
        names = [n.strip() for n in text.replace("\n", ",").split(",") if n.strip()][:50]
        done = []
        for n in names:
            try:
                g = await repo.get_or_create_group(n)
                done.append(g["name"])
            except ValueError:
                continue
        await repo.audit(ctx.uid, "groups_add", ",".join(done)[:200])
        return Out(screen=Screen("Группы добавлены: " + (fm.esc(", ".join(done)) or "ничего"), [nav("ad:sch")]), clear_state=True)
    if state == "ad:parity" and ctx.can("schedule"):
        if text.strip() == "-":
            await repo.set_setting("parity_anchor", "")
            return Out(screen=Screen("Чётность недель отключена.", [nav("ad:sch")]), clear_state=True)
        d = importer.parse_day(text.strip())
        if not d:
            return Out(screen=Screen("Не понял дату. Формат: ДД.ММ.ГГГГ", [nav("ad:sch")]), state="ad:parity", state_data={})
        await repo.set_setting("parity_anchor", d)
        await repo.audit(ctx.uid, "parity_anchor", d)
        return Out(screen=Screen(f"Готово: неделя с {d} нечётная.", [nav("ad:sch")]), clear_state=True)
    if state == "ad:teacher_search" and ctx.can("teachers"):
        found = await repo.search_teachers(text)
        if not found:
            return Out(screen=Screen("Не нашёл. Попробуйте ещё раз.", [nav("ad:rt")]), state="ad:teacher_search", state_data={})
        kb = [[Btn(t["name"][:32], f"ad:rtc:{t['id']}")] for t in found] + [nav("ad:rt")]
        return Out(screen=Screen("Нашёл:", kb), clear_state=True)
    if state == "ad:bc_group" and ctx.can("broadcast"):
        groups = await repo.search_groups(text, 1)
        if not groups:
            return Out(screen=Screen("Группа не найдена.", [nav("ad:bc")]), state="ad:bc_group", state_data={})
        return Out(screen=Screen(f"Группа {fm.esc(groups[0]['name'])}. Напишите текст рассылки."),
                   state="ad:bc_text", state_data={"aud": "grp", "gid": groups[0]["id"]})
    if state == "ad:bc_text" and ctx.can("broadcast"):
        if len(text) > 3000:
            return Out(screen=Screen("Слишком длинно (максимум 3000 символов)."), state="ad:bc_text", state_data=data)
        new = dict(data, text=text)
        n = len(await _recipients(ctx, new))
        kb = [[Btn(f"✅ Отправить ({n})", "ad:bcy"), Btn("❌ Отмена", "ad:bc")]]
        preview = ("📷 Фото будет приложено.\n" if new.get("media_file_id") else "")
        return Out(screen=Screen(f"<b>Предпросмотр</b>\n\n{preview}📣 {fm.esc(text)}\n\nПолучателей: {n}", kb),
                   state="ad:bc_confirm", state_data=new)
    if state == "ad:uitext_val" and ctx.is_super:
        key = data.get("key")
        if key not in ("welcome_text", "unknown_text", "hw_intro_text"):
            return Out(screen=Screen("Ключ текста устарел.", [nav("ad:uitext")]), clear_state=True)
        value = "" if text.strip() == "-" else text.strip()
        if len(value) > 1000:
            return Out(screen=Screen("Максимум 1000 символов."), state=state, state_data=data)
        await repo.set_setting(key, value)
        await repo.audit(ctx.uid, "ui_text", key)
        return Out(screen=Screen("Текст сохранён.", [nav("ad:uitext")]), clear_state=True)
    if state == "ad:set_val" and ctx.is_super:
        key = data.get("key")
        if key not in INT_SETTINGS or not text.strip().isdigit() or not 1 <= int(text.strip()) <= 365:
            return Out(screen=Screen("Нужно число от 1 до 365.", [nav("ad:set")]), state="ad:set_val", state_data=data)
        await repo.set_setting(key, str(int(text.strip())))
        await repo.audit(ctx.uid, "setting", f"{key}={text.strip()}")
        return Out(screen=_settings_screen(ctx), clear_state=True)
    if state == "ad:admin_add" and ctx.is_super:
        u = await repo.find_user(text)
        if u is None and text.strip().isdigit():
            u = await repo.ensure_user(int(text.strip()))
        if not u or u["id"] == ctx.cfg.superadmin_id:
            return Out(screen=Screen("Пользователь не найден. Он должен хотя бы раз запустить бота.", [nav("ad:adm")]),
                       state="ad:admin_add", state_data={})
        await repo.update_user(u["id"], role="admin", admin_perms=",".join(DEFAULT_ADMIN_PERMS))
        await repo.audit(ctx.uid, "admin_add", str(u["id"]))
        out = await _admin_card(ctx, u["id"])
        out.clear_state = True
        out.notify = [(u["id"], Screen("Вам выданы права администратора бота. Команда /admin открывает панель."))]
        return out
    if state == "ad:sw_add" and ctx.can("users"):
        word = text.strip().lower()
        if not 2 <= len(word) <= 30 or " " in word:
            return Out(screen=Screen("Нужно одно слово от 2 до 30 букв.", [nav("ad:dict")]), state="ad:sw_add", state_data=data)
        await repo.add_stopword(word, data.get("kind", "stub"))
        await repo.audit(ctx.uid, "stopword_add", word)
        return Out(screen=Screen("Добавлено ✅", [nav("ad:dict")]), clear_state=True)
    if state == "ad:alias_add" and ctx.can("users"):
        if "=" not in text:
            return Out(screen=Screen("Формат: <code>матеша = Математика</code>", [nav("ad:al")]), state="ad:alias_add", state_data={})
        alias, subject = (x.strip() for x in text.split("=", 1))
        if not alias or not subject or len(alias) > 40 or len(subject) > 80:
            return Out(screen=Screen("Проверьте формат: синоним = предмет.", [nav("ad:al")]), state="ad:alias_add", state_data={})
        await repo.add_alias(alias, subject)
        return Out(screen=Screen("Синоним добавлен ✅", [nav("ad:al")]), clear_state=True)
    return Out(screen=await menu_screen(ctx), clear_state=True)


# ---------------- файлы ----------------
async def on_document(ctx: Ctx, state: str, filename: str, data: bytes) -> Out:
    if not ctx.is_admin:
        return _deny()
    repo = ctx.repo
    if state == "ad:import" and ctx.can("schedule"):
        try:
            recs, errors = importer.parse_file(filename, data)
        except Exception as e:
            return Out(screen=Screen(f"Не удалось прочитать файл: {fm.esc(str(e)[:200])}", [nav("ad:sch")]),
                       state="ad:import", state_data={})
        if errors:
            return Out(screen=Screen("<b>В файле есть ошибки, ничего не загружено:</b>\n" + "\n".join(
                fm.esc(e) for e in errors[:10]) + "\n\nИсправьте и пришлите файл снова.", [nav("ad:sch")]),
                       state="ad:import", state_data={})
        sync = ctx.services.get("sync")
        if sync is None:
            return Out(toast="Сервис недоступен", alert=True)
        res = await sync.apply_import(recs)
        groups = len({r.group for r in recs})
        await repo.audit(ctx.uid, "import", f"{filename}:{len(recs)}")
        return Out(screen=Screen(f"Загружено занятий: {len(recs)} · групп: {groups} ✅\nОни помечены ✏️ и не "
                                 "перезаписываются автосинхронизацией.", [nav("ad:sch")]), clear_state=True)
    if state == "ad:dir_import" and ctx.can("schedule"):
        from app.providers import directory as dirp

        try:
            staff, units, errors = dirp.parse_directory_file(filename, data)
        except Exception as e:
            return Out(screen=Screen(f"Не удалось прочитать файл: {fm.esc(str(e)[:200])}", [nav("ad:dir")]),
                       state="ad:dir_import", state_data={})
        if errors or not staff:
            return Out(screen=Screen("<b>Ничего не загружено.</b>\n" + "\n".join(fm.esc(e) for e in errors[:10]) +
                                     "\nИсправьте файл и пришлите снова.", [nav("ad:dir")]),
                       state="ad:dir_import", state_data={})
        svc = ctx.services.get("directory")
        if svc is None:
            return Out(toast="Сервис недоступен", alert=True)
        msg = await svc.apply_file(staff, units)
        await repo.audit(ctx.uid, "dir_import", filename[:80])
        return Out(screen=Screen("Справочник загружен ✅\n" + fm.esc(msg), [nav("ad:dir")]), clear_state=True)
    if state == "ad:restore" and ctx.is_super:
        try:
            dump = bk.parse_backup(data)
        except ValueError as e:
            return Out(screen=Screen(fm.esc(str(e)), [nav("ad:bk")]), state="ad:restore", state_data={})
        _RESTORE[ctx.uid] = dump
        n = sum(len(v) for v in dump["tables"].values())
        when = datetime.fromtimestamp(int(dump.get("created", 0)), tu.tz()).strftime("%d.%m.%Y %H:%M")
        kb = [[Btn("⚠️ Да, заменить все данные", "ad:bky")], [Btn("Отмена", "ad:bk")]]
        return Out(screen=Screen(f"Бэкап от {when}, записей: {n}.\nВсе текущие данные будут заменены. Продолжить?", kb),
                   state="ad:restore_confirm", state_data={})
    return Out(toast="Сейчас файл не нужен", alert=True)
