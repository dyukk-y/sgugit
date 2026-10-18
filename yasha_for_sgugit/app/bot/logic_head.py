"""Панель старосты: проверка заданий, рассылка группе, ручные пары."""
from __future__ import annotations

from dataclasses import replace

from app import timeutil as tu
from app.bot.core import Btn, Ctx, Kb, Out, Screen, daily_quota, home_btn, nav
from app.providers.importer import parse_manual_line
from app.services import format as fm


def _deny() -> Out:
    return Out(toast="Только для старост", alert=True)


async def menu(ctx: Ctx) -> Screen:
    gid = ctx.user.get("group_id")
    pending = (await ctx.repo.pending_hw(gid, 1))[1] if gid else 0
    g = await ctx.group()
    kb: Kb = [[Btn(f"📋 Задания на проверке ({pending})", "h:q:0")],
              [Btn("📣 Рассылка группе", "hd:bc")],
              [Btn("➕ Пара вручную", "hd:ml"), Btn("🗑 Ручные пары", "hd:mls")],
              nav("me:menu")]
    return Screen(f"<b>Панель старосты</b>\nГруппа {fm.esc(g['name']) if g else '—'}", kb)


async def on_cb(ctx: Ctx, parts: list[str]) -> Out:
    if not ctx.is_head or not ctx.user.get("group_id"):
        return _deny()
    act = parts[0] if parts else "menu"
    repo = ctx.repo
    gid = ctx.user["group_id"]
    if act == "menu":
        return Out(screen=await menu(ctx), clear_state=True)
    if act == "bc":
        return Out(screen=Screen("Напишите сообщение для всей группы одним сообщением. Лимит: 3 рассылки в сутки.",
                                 [nav("hd:menu")]), state="hd:bc_text", state_data={})
    if act == "bcy":
        state, data = await repo.get_state(ctx.uid)
        if state != "hd:bc_confirm" or not data.get("text"):
            return Out(toast="Черновик устарел", alert=True)
        if not await daily_quota(repo, "hdbc", ctx.uid, 3, tu.iso(ctx.today)):
            return Out(screen=Screen("Лимит рассылок на сегодня исчерпан.", [nav("hd:menu")]), clear_state=True)
        users = [u for u in await repo.group_users(gid) if not u["bot_blocked"] and u["id"] != ctx.uid]
        g = await ctx.group()
        text = f"📣 <b>Староста {fm.esc(g['name']) if g else ''}</b>\n\n{fm.esc(data['text'])}"
        await repo.audit(ctx.uid, "head_broadcast", f"{gid}:{len(users)}")
        out = Out(screen=Screen(f"Рассылка поставлена в очередь: {len(users)} получателей.", [nav("hd:menu")]), clear_state=True)
        out.notify = [(u["id"], Screen(text)) for u in users]
        return out
    if act == "ml":
        return Out(screen=Screen("Одна пара одной строкой:\n<code>дата;начало;конец;предмет;преподаватель;аудитория;тип</code>\n"
                                 "Например: <code>25.10;10:00;11:30;Консультация;Иванов И. И.;310;консультация</code>\n"
                                 "Преподавателя, аудиторию и тип можно не писать.", [nav("hd:menu")]),
                   state="hd:ml_text", state_data={})
    if act == "mls":
        rows = await repo.manual_lessons(gid, tu.iso(ctx.today), 10)
        kb: Kb = [[Btn(f"🗑 {tu.fmt_dm(tu.parse_iso(r['day']))} {r['start_t']} {r['subject'][:18]}", f"hd:mld:{r['id']}")]
                  for r in rows]
        kb.append(nav("hd:menu"))
        return Out(screen=Screen("<b>Ручные пары</b> (нажмите, чтобы удалить)" + ("" if rows else "\nПока нет."), kb))
    if act == "mld" and len(parts) > 1 and parts[1].isdigit():
        l = await repo.get_lesson(int(parts[1]))
        if not l or l["group_id"] != gid or not l["manual"]:
            return Out(toast="Нельзя удалить", alert=True)
        await repo.delete_manual_lesson(l["id"])
        await repo.audit(ctx.uid, "manual_lesson_delete", str(l["id"]))
        out = await on_cb(ctx, ["mls"])
        out.toast = "Удалено"
        return out
    return Out(toast="Неизвестное действие")


async def on_text(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if not ctx.is_head or not ctx.user.get("group_id"):
        return _deny()
    gid = ctx.user["group_id"]
    if state == "hd:bc_text":
        if len(text) > 2000:
            return Out(screen=Screen("Слишком длинно (максимум 2000 символов)."), state="hd:bc_text", state_data={})
        n = len([u for u in await ctx.repo.group_users(gid) if not u["bot_blocked"] and u["id"] != ctx.uid])
        kb = [[Btn(f"✅ Отправить ({n})", "hd:bcy"), Btn("❌ Отмена", "hd:menu")]]
        return Out(screen=Screen(f"<b>Предпросмотр</b>\n\n📣 {fm.esc(text)}\n\nПолучателей: {n}", kb),
                   state="hd:bc_confirm", state_data={"text": text})
    if state == "hd:ml_text":
        g = await ctx.group()
        rec, err = parse_manual_line(text, g["name"] if g else "", ctx.today)
        if rec is None:
            return Out(screen=Screen(f"{fm.esc(err)}\nПопробуйте ещё раз."), state="hd:ml_text", state_data={})
        existing = await ctx.repo.lessons_day(gid, rec.day)
        num = 1 + sum(1 for l in existing if l["start_t"] < rec.start)
        await ctx.repo.add_manual_lesson(gid, replace(rec, num=num))
        await ctx.repo.audit(ctx.uid, "manual_lesson_add", f"{rec.day} {rec.subject}")
        return Out(screen=Screen(f"Добавлено ✅\n{tu.fmt_date(tu.parse_iso(rec.day))}, {rec.start}–{rec.end} · {fm.esc(rec.subject)}",
                                 [[Btn("➕ Ещё", "hd:ml"), Btn("◀ Панель", "hd:menu")]]), clear_state=True)
    return Out(screen=await menu(ctx), clear_state=True)
