"""Задания группы: список, карточка, добавление, одобрение старостой."""
from __future__ import annotations

from datetime import date, timedelta

from app import timeutil as tu
from app.bot.core import Btn, Ctx, Kb, Out, Screen, daily_quota, home_btn, nav
from app.services import format as fm
from app.services.fio import short_name
from app.services.nlu import DUE_RE, HwPhrase, parse_when

SIZE = 5


def can_moderate(ctx: Ctx, hw: dict) -> bool:
    if ctx.is_super or (ctx.role == "admin" and ctx.can("homework")):
        return True
    return False


def _can_see(ctx: Ctx, hw: dict) -> bool:
    if hw["status"] == "deleted":
        return False
    if can_moderate(ctx, hw):
        return True
    if ctx.user.get("group_id") != hw["group_id"]:
        return False
    return hw["status"] == "approved" or (hw["status"] == "pending" and hw["author_id"] == ctx.uid)


def _due_label(hw: dict) -> str:
    return f"до {tu.fmt_dm(date.fromisoformat(hw['due_day']))}" if hw.get("due_day") else "без срока"


async def list_screen(ctx: Ctx, page: int = 0) -> Screen:
    gid = ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    rows, total = await ctx.repo.list_hw(gid, tu.iso(ctx.today), page * SIZE, SIZE)
    done = await ctx.repo.hw_done_set(ctx.uid, [r["id"] for r in rows])
    kb: Kb = []
    lines = ["<b>Задания группы</b>"]
    if not rows:
        lines.append("\nПока заданий нет.")
    for r in rows:
        mark = "✅ " if r["id"] in done else ""
        kb.append([Btn(f"{mark}{r['subject'][:22]} · {_due_label(r)}", f"h:v:{r['id']}")])
    if total > SIZE:
        from app.bot.core import pager
        kb.append(pager("h:l", page, total, SIZE))
    row = []
    if ctx.verified:
        row.append(Btn("➕ Добавить", "h:add:0"))
    if ctx.is_head:
        n = (await ctx.repo.pending_hw(gid, 1))[1]
        row.append(Btn(f"📋 На проверке ({n})", "h:q:0"))
    if row:
        kb.append(row)
    if not ctx.verified:
        lines.append("\n<i>Добавлять задания можно после подтверждения ФИО.</i>")
    kb.append([home_btn()])
    return Screen("\n".join(lines), kb)


async def day_list_screen(ctx: Ctx, day: str) -> Screen:
    gid = ctx.user.get("group_id")
    if not gid:
        return Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]])
    rows = await ctx.repo.hw_for_day(gid, day)
    d = tu.parse_iso(day)
    lines = [f"<b>Задания к парам · {tu.fmt_date(d)}</b>"]
    kb: Kb = []
    for r in rows:
        txt = r["text"] if len(r["text"]) <= 120 else r["text"][:117] + "…"
        lines.append(f"• <b>{fm.esc(r['subject'])}</b> ({_due_label(r)}): {fm.esc(txt)}")
        kb.append([Btn(f"{r['subject'][:22]} · открыть", f"h:v:{r['id']}")])
    if not rows:
        lines.append("\nПока ничего нет.")
    if ctx.verified:
        kb.append([Btn("➕ Добавить", f"h:add:{day}")])
    kb.append(nav(f"s:d:{day}"))
    return Screen("\n".join(lines), kb)


async def view_screen(ctx: Ctx, hid: int, back: str = "h:l:0") -> Out:
    hw = await ctx.repo.get_hw(hid)
    if not hw or not _can_see(ctx, hw):
        return Out(toast="Задание недоступно", alert=True)
    lines = [f"📚 <b>{fm.esc(hw['subject'])}</b>", f"Срок: {_due_label(hw)}"]
    if hw.get("lesson_day"):
        lines.append(f"К паре: {tu.fmt_date(tu.parse_iso(hw['lesson_day']))}")
    if ctx.repo.flag("hw_show_author"):
        author = await ctx.repo.get_user(hw["author_id"])
        lines.append(f"Добавил(а): {fm.esc(short_name(author.get('fio') if author else None))}")
    lines += ["", fm.esc(hw["text"])]
    if hw.get("media_file_id"):
        lines.append("\n📎 Прикреплено: " + fm.esc("фото" if hw.get("media_type") == "photo" else (hw.get("media_name") or "файл")))
    kb: Kb = []
    if hw["status"] == "pending":
        lines.insert(1, "⏳ <i>Ждёт одобрения старосты</i>")
        if can_moderate(ctx, hw):
            kb.append([Btn("✅ Одобрить", f"h:ok:{hid}"), Btn("❌ Отклонить", f"h:no:{hid}")])
    elif hw["status"] == "approved":
        done = await ctx.repo.hw_done_set(ctx.uid, [hid])
        kb.append([Btn("↩ Не сделано" if hid in done else "✅ Сделано", f"h:dn:{hid}")])
    if hw["author_id"] == ctx.uid or can_moderate(ctx, hw):
        kb.append([Btn("✏️ Текст", f"h:edit:{hid}"), Btn("📚 Предмет", f"h:editfield:{hid}:subject")])
        kb.append([Btn("📅 Срок", f"h:editfield:{hid}:due"), Btn("📎 Вложение", f"h:editfield:{hid}:media")])
        kb.append([Btn("🗑 Удалить", f"h:del:{hid}")])
    kb.append(nav(back))
    out = Out(screen=Screen("\n".join(lines), kb))
    if hw.get("media_file_id"):
        out.media = (hw["media_file_id"], hw.get("media_type") or "document", hw.get("media_name"))
        out.new_message = True
    return out


async def start_add(ctx: Ctx, day: str) -> Out:
    gid = ctx.user.get("group_id")
    if not gid or not ctx.verified:
        return Out(toast="Добавлять задания можно после подтверждения ФИО", alert=True)
    if day and day != "0":
        subs = await ctx.repo.upcoming_subjects(gid, day, day)
        lesson_day: str | None = day
    else:
        subs = await ctx.repo.upcoming_subjects(gid, tu.iso(ctx.today), tu.iso(ctx.today + timedelta(days=14)))
        lesson_day = None
    if not subs:
        return Out(screen=Screen("В расписании на эти дни не нашёл предметов. Выберите другой день в расписании.",
                                 [nav("h:l:0")]))
    subs = subs[:12]
    kb: Kb = []
    for i in range(0, len(subs), 2):
        kb.append([Btn(s[:28], f"h:sub:{i + j}") for j, s in enumerate(subs[i:i + 2])])
    kb.append([Btn("❌ Отмена", "h:cancel")])
    return Out(screen=Screen("К какому предмету задание?", kb), state="hw:pick",
               state_data={"subs": subs, "day": lesson_day})


async def _default_due(ctx: Ctx, gid: int, subject: str, lesson_day: str | None) -> str | None:
    start = tu.parse_iso(lesson_day) if lesson_day else ctx.today
    rows = await ctx.repo.next_lessons(gid, tu.iso(start + timedelta(days=1)), 30)
    for l in rows:
        if l["subject"] == subject:
            return l["day"]
    return None


def _looks_like_assignment(text: str) -> bool:
    """Мягкая защита от явного мусора; не оценивает правильность задания."""
    import re
    value = " ".join((text or "").split())
    if len(value) < 3 or len(value) > 1000:
        return False
    letters = sum(ch.isalpha() for ch in value)
    digits = sum(ch.isdigit() for ch in value)
    if len(value) >= 12 and letters + digits == 0:
        return False
    if re.search(r"(.)\1{11,}", value):
        return False
    # Не пропускаем длинные цепочки бессмысленных символов, но формулы и номера допускаются.
    if len(value) >= 24 and sum(ch.isalnum() for ch in value) / max(1, len(value)) < 0.18:
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value)
    if len(words) >= 4 and len(set(w.casefold() for w in words)) == 1:
        return False
    return True


def _preview(ctx: Ctx, data: dict) -> Screen:
    due = f"до {tu.fmt_dm(date.fromisoformat(data['due']))}" if data.get("due") else "без срока"
    note = "\n\n<i>После публикации задание сразу появится у группы. Перед отправкой бот проверит только явный мусор.</i>"
    attachment = "\n\n📎 Вложение прикреплено." if data.get("media_file_id") else ""
    text = f"<b>Проверьте задание</b>\n📚 {fm.esc(data['subject'])} · {due}\n\n{fm.esc(data['text'])}{attachment}{note}"
    kb = [[Btn("✅ Отправить", "h:save"), Btn("✏️ Заново", f"h:add:{data.get('day') or 0}")],
          [Btn("❌ Отмена", "h:cancel")]]
    return Screen(text, kb)


async def quick_add(ctx: Ctx, phrase: HwPhrase) -> Out:
    gid = ctx.user.get("group_id")
    if not gid or not ctx.verified:
        return Out(screen=Screen("Добавлять задания можно после подтверждения ФИО.", [[home_btn()]]))
    due = tu.iso(phrase.due) if phrase.due else await _default_due(ctx, gid, phrase.subject, None)
    data = {"subject": phrase.subject, "day": None, "text": phrase.text[:1000], "due": due}
    return Out(screen=_preview(ctx, data), state="hw:confirm", state_data=data)


async def on_text_hw(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if state == "hw:edit_subject":
        hid = int(data.get("hid", 0)); hw = await ctx.repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True, clear_state=True)
        value = text.strip()
        if not 2 <= len(value) <= 120:
            return Out(screen=Screen("Название предмета должно содержать 2–120 символов."), state=state, state_data=data)
        await ctx.repo.db.execute("UPDATE homework SET subject = ? WHERE id = ?", value, hid)
        await ctx.repo.audit(ctx.uid, "hw_edit_subject", str(hid))
        out = await view_screen(ctx, hid); out.clear_state = True; out.toast = "Предмет изменён"; return out
    if state == "hw:edit_due":
        hid = int(data.get("hid", 0)); hw = await ctx.repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True, clear_state=True)
        value = text.strip()
        if value.lower() in {"-", "нет", "без срока"}:
            due = None
        else:
            parsed, _ = parse_when(value, ctx.today)
            if not parsed:
                try: parsed = date.fromisoformat(value)
                except ValueError: parsed = None
            if not parsed:
                return Out(screen=Screen("Укажите дату (ДД.ММ.ГГГГ или ГГГГ-ММ-ДД), например 25.10.2026, либо «без срока»."), state=state, state_data=data)
            due = tu.iso(parsed)
        await ctx.repo.db.execute("UPDATE homework SET due_day = ? WHERE id = ?", due, hid)
        await ctx.repo.audit(ctx.uid, "hw_edit_due", str(hid))
        out = await view_screen(ctx, hid); out.clear_state = True; out.toast = "Срок изменён"; return out
    if state == "hw:edit_text":
        hid = int(data.get("hid", 0)); hw = await ctx.repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True, clear_state=True)
        body = text.strip()
        if not 3 <= len(body) <= 1000:
            return Out(screen=Screen("Текст должен содержать от 3 до 1000 символов."), state=state, state_data=data)
        await ctx.repo.update_hw(hid, text=body)
        await ctx.repo.audit(ctx.uid, "hw_edit", str(hid))
        out = await view_screen(ctx, hid); out.clear_state = True; return out
    if state == "hw:text":
        body = text.strip()
        due: str | None = None
        m = DUE_RE.search(body.lower().replace("ё", "е"))
        if m:
            d, _ = parse_when(m.group(0), ctx.today)
            if d:
                due = tu.iso(d)
                body = (body[:m.start()] + " " + body[m.end():]).strip(" ,.;-")
        if len(body) < 3:
            return Out(screen=Screen("Слишком коротко. Напишите задание подробнее."), state="hw:text", state_data=data)
        if len(body) > 1000:
            return Out(screen=Screen("Слишком длинно (максимум 1000 символов). Сократите, пожалуйста."),
                       state="hw:text", state_data=data)
        gid = ctx.user.get("group_id")
        if due is None and gid:
            due = await _default_due(ctx, gid, data["subject"], data.get("day"))
        new = {"subject": data["subject"], "day": data.get("day"), "text": body, "due": due,
               **{k: data[k] for k in ("media_file_id", "media_type", "media_name") if data.get(k)}}
        return Out(screen=_preview(ctx, new), state="hw:confirm", state_data=new)
    return Out(screen=await list_screen(ctx), clear_state=True)


async def _notify_moderators(ctx: Ctx, gid: int, hid: int, data: dict) -> list[tuple[int, Screen]]:
    heads = [u["id"] for u in await ctx.repo.heads_of_group(gid)]
    if not heads:
        for a in await ctx.repo.users_with_role("admin"):
            if "homework" in (a.get("admin_perms") or "").split(","):
                heads.append(a["id"])
    g = await ctx.group()
    due = f"до {tu.fmt_dm(date.fromisoformat(data['due']))}" if data.get("due") else "без срока"
    text = (f"📝 <b>Новое задание на проверку</b> · {fm.esc(g['name']) if g else ''}\n"
            f"От: {fm.esc(short_name(ctx.user.get('fio')))}\n📚 {fm.esc(data['subject'])} · {due}\n\n{fm.esc(data['text'])}")
    kb = [[Btn("✅ Одобрить", f"h:ok:{hid}"), Btn("❌ Отклонить", f"h:no:{hid}")]]
    return [(h, Screen(text, kb)) for h in heads if h != ctx.uid]


async def on_cb_hw(ctx: Ctx, parts: list[str]) -> Out:
    act = parts[0] if parts else "l"
    repo = ctx.repo
    gid = ctx.user.get("group_id")
    if not gid and act in ("l", "d", "dn", "add", "sub", "save", "cancel", "q"):
        return Out(screen=Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]]))
    if act == "l":
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return Out(screen=await list_screen(ctx, page), clear_state=True)
    if act == "d" and len(parts) > 1:
        return Out(screen=await day_list_screen(ctx, parts[1]))
    if act == "v" and len(parts) > 1 and parts[1].isdigit():
        return await view_screen(ctx, int(parts[1]))
    if act == "dn" and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1])
        hw = await repo.get_hw(hid)
        if not hw or hw["group_id"] != gid or hw["status"] != "approved":
            return Out(toast="Задание недоступно", alert=True)
        await repo.toggle_hw_done(ctx.uid, hid)
        out = await view_screen(ctx, hid)
        out.toast = "Отмечено"
        return out
    if act == "editfield" and len(parts) > 2 and parts[1].isdigit():
        hid = int(parts[1]); field = parts[2]; hw = await repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True)
        if field == "subject":
            return Out(screen=Screen("Введите новое название предмета (2–120 символов).", [nav(f"h:v:{hid}")]), state="hw:edit_subject", state_data={"hid": hid})
        if field == "due":
            return Out(screen=Screen("Введите новую дату: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД. Чтобы убрать срок, отправьте «без срока»." , [nav(f"h:v:{hid}")]), state="hw:edit_due", state_data={"hid": hid})
        if field == "media":
            kb = [[Btn("📎 Заменить вложение", f"h:editmedia:{hid}"), Btn("🗑 Удалить вложение", f"h:removemedia:{hid}")], nav(f"h:v:{hid}")]
            return Out(screen=Screen("Вложение задания. Можно заменить фото/файл следующим сообщением или удалить текущее.", kb))
    if act == "editmedia" and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1]); hw = await repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True)
        return Out(screen=Screen("Отправьте новое фото или документ как следующее сообщение.", [nav(f"h:v:{hid}")]), state="hw:replace_media", state_data={"hid": hid})
    if act == "removemedia" and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1]); hw = await repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True)
        await repo.db.execute("UPDATE homework SET media_file_id = NULL, media_type = NULL, media_name = NULL WHERE id = ?", hid)
        await repo.audit(ctx.uid, "hw_remove_media", str(hid))
        return await view_screen(ctx, hid)
    if act == "edit" and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1]); hw = await repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True)
        return Out(screen=Screen("Отправьте новый текст задания одним сообщением (3–1000 символов).", [[Btn("❌ Отмена", "h:cancel")]]), state="hw:edit_text", state_data={"hid": hid})
    if act == "del" and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1])
        hw = await repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True)
        if len(parts) > 2 and parts[2] == "y":
            await repo.set_hw_status(hid, "deleted", ctx.uid)
            await repo.audit(ctx.uid, "hw_delete", str(hid))
            return Out(screen=await list_screen(ctx), toast="Удалено")
        return Out(screen=Screen("Удалить это задание?", [[Btn("Да, удалить", f"h:del:{hid}:y"),
                                                           Btn("Отмена", f"h:v:{hid}")]]))
    if act in ("ok", "no") and len(parts) > 1 and parts[1].isdigit():
        hid = int(parts[1])
        hw = await repo.get_hw(hid)
        if not hw or not can_moderate(ctx, hw):
            return Out(toast="Нет прав", alert=True)
        if hw["status"] != "pending":
            return Out(toast="Уже обработано", alert=True)
        new = "approved" if act == "ok" else "rejected"
        await repo.set_hw_status(hid, new, ctx.uid)
        await repo.audit(ctx.uid, f"hw_{new}", str(hid))
        out = Out(screen=await queue_screen(ctx, 0) if ctx.is_admin else Screen("Готово.", [nav("m:home")]),
                  toast="Одобрено ✅" if act == "ok" else "Отклонено")
        verdict = "одобрено ✅" if act == "ok" else "отклонено ❌"
        out.notify = [(hw["author_id"], Screen(f"Ваше задание по предмету «{fm.esc(hw['subject'])}» {verdict}."))] \
            if hw["author_id"] != ctx.uid else []
        return out
    if act == "q":
        if not (ctx.is_super or (ctx.role == "admin" and ctx.can("homework"))):
            return Out(toast="Очередь заданий доступна администраторам", alert=True)
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return Out(screen=await queue_screen(ctx, page))
    if act == "add":
        return await start_add(ctx, parts[1] if len(parts) > 1 else "0")
    if act == "sub" and len(parts) > 1 and parts[1].isdigit():
        state, data = await repo.get_state(ctx.uid)
        subs = data.get("subs") or []
        idx = int(parts[1])
        if state != "hw:pick" or idx >= len(subs):
            return Out(toast="Выбор устарел, начните заново", alert=True)
        intro = repo.setting("hw_intro_text") or "Напишите задание одним сообщением. Срок можно указать словами: «до пятницы», «к 25.10». Без срока оно будет до следующей пары. Можно также прикрепить фото или файл."
        return Out(screen=Screen(f"📚 <b>{fm.esc(subs[idx])}</b>\n{fm.esc(intro)}",
                                 [[Btn("❌ Отмена", "h:cancel")]]),
                   state="hw:text", state_data={"subject": subs[idx], "day": data.get("day")})
    if act == "cancel":
        return Out(screen=await list_screen(ctx), clear_state=True)
    if act == "save":
        state, data = await repo.get_state(ctx.uid)
        if state != "hw:confirm" or not data.get("text"):
            return Out(toast="Черновик устарел, начните заново", alert=True)
        if not ctx.verified:
            return Out(toast="Нужно подтверждённое ФИО", alert=True)
        limit = repo.int_setting("hw_daily_limit") or 10
        if not await daily_quota(repo, "hw", ctx.uid, limit, tu.iso(ctx.today)):
            return Out(screen=Screen("Достигнут дневной лимит заданий. Попробуйте завтра.", [[home_btn()]]),
                       clear_state=True)
        if not _looks_like_assignment(data["text"]):
            return Out(screen=Screen("Похоже, в тексте слишком много случайных символов или повторов. Напишите само задание понятнее — проверка не требует идеальной формулировки.", [[Btn("✏️ Исправить", f"h:add:{data.get('day') or 0}"), Btn("❌ Отмена", "h:cancel")]]), clear_state=True)
        # Задания публикуются сразу: только явный мусор отсеивается мягкой проверкой.
        hid = await repo.add_hw(gid, data["subject"], data.get("day"), data["text"], data.get("due"), ctx.uid, "approved")
        return Out(screen=Screen("✅ Задание опубликовано и уже доступно группе.", [[Btn("📝 Задания", "h:l:0"), home_btn()]]), clear_state=True)
    return Out(toast="Неизвестное действие")


async def queue_screen(ctx: Ctx, page: int) -> Screen:
    gid = ctx.user.get("group_id")
    rows, total = await ctx.repo.pending_hw(gid, SIZE, page * SIZE)
    lines = [f"<b>На проверке: {total}</b>"]
    kb: Kb = []
    if not rows:
        lines.append("\nНовых заданий нет.")
    for r in rows:
        kb.append([Btn(f"{r['subject'][:18]}: {r['text'][:24]}", f"h:v:{r['id']}")])
    if total > SIZE:
        from app.bot.core import pager
        kb.append(pager("h:q", page, total, SIZE))
    kb.append(nav("ad:hw:0" if ctx.is_admin else "m:home"))
    return Screen("\n".join(lines), kb)
