"""Рейтинг преподавателей: список с листанием, поиск, карточка, оценка 1–5."""
from __future__ import annotations

from app.bot.core import Btn, Ctx, Kb, Out, Screen, home_btn, nav, pager
from app.services import format as fm
from app.services.nlu import find_subject

SIZE = 6


def _stars_text(avg: float | None, cnt: int, min_votes: int) -> str:
    if cnt >= min_votes and avg is not None:
        return f"⭐ {avg:.1f}".replace(".", ",") + f" · {cnt} {_plural(cnt)}"
    return f"оценок пока мало ({cnt} из {min_votes})" if cnt else "оценок пока нет"


def _plural(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "оценок"
    return {1: "оценка", 2: "оценки", 3: "оценки", 4: "оценки"}.get(n % 10, "оценок")


def _disabled() -> Out:
    return Out(toast="Раздел сейчас недоступен", alert=True)


async def list_screen(ctx: Ctx, mode: str = "m", page: int = 0) -> Screen:
    gid = ctx.user.get("group_id")
    note = ""
    ids: set[int] | None = None
    if mode == "m" and gid:
        ids = await ctx.repo.teacher_ids_for_group(gid)
        if not ids:
            ids, mode = None, "a"
            note = "\n<i>У вашей группы пока нет преподавателей в расписании, показываю всех.</i>"
    rows, total = await ctx.repo.list_teachers(page * SIZE, SIZE, ids)
    min_votes = ctx.repo.int_setting("min_votes") or 5
    kb: Kb = []
    for r in rows:
        label = r["name"][:30]
        if r["cnt"] >= min_votes and r["avg"] is not None:
            label += f" ⭐{r['avg']:.1f}".replace(".", ",")
        kb.append([Btn(label, f"t:v:{r['id']}:{mode}:{page}")])
    if total > SIZE:
        kb.append(pager(f"t:l:{mode}", page, total, SIZE))
    kb.append([Btn("🔎 Поиск", "t:s"),
               Btn("Все преподаватели" if mode == "m" else "Мои преподаватели", f"t:l:{'a' if mode == 'm' else 'm'}:0")])
    kb.append([home_btn()])
    title = "<b>Преподаватели</b> · " + ("ваши" if mode == "m" else "все")
    if not rows:
        title += "\n\nПока никого нет."
    return Screen(title + note, kb)


async def card(ctx: Ctx, tid: int, mode: str = "m", page: int = 0) -> Out:
    t = await ctx.repo.get_teacher(tid)
    if not t or t["hidden"]:
        return Out(toast="Преподаватель недоступен", alert=True)
    min_votes = ctx.repo.int_setting("min_votes") or 5
    subs = await ctx.repo.teacher_subjects(t["norm"])
    mine = await ctx.repo.my_rating(ctx.uid, tid)
    lines = [f"<b>{fm.esc(t['name'])}</b>"]
    if subs:
        lines.append("Предметы: " + fm.esc(", ".join(subs)))
    lines.append(_stars_text(t["avg"], t["cnt"], min_votes))
    if mine:
        lines.append(f"Ваша оценка: {'⭐' * mine}")
    kb: Kb = []
    if ctx.verified:
        lines.append("\nПоставьте оценку:")
        kb.append([Btn(f"{n}⭐", f"t:r:{tid}:{n}:{mode}:{page}") for n in range(1, 6)])
    else:
        lines.append("\n<i>Оценки доступны после подтверждения ФИО.</i>")
    kb.append(nav(f"t:l:{mode}:{page}"))
    return Out(screen=Screen("\n".join(lines), kb))


async def on_cb(ctx: Ctx, parts: list[str]) -> Out:
    if not ctx.repo.flag("rating_enabled"):
        return _disabled()
    if not ctx.registered:
        return Out(screen=Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]]))
    act = parts[0] if parts else "l"
    if act == "l":
        mode = parts[1] if len(parts) > 1 and parts[1] in ("m", "a") else "m"
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        return Out(screen=await list_screen(ctx, mode, page), clear_state=True)
    if act == "s":
        return Out(screen=Screen("Напишите фамилию преподавателя или название предмета.", [nav("t:l:m:0")]),
                   state="t:search", state_data={})
    if act == "v" and len(parts) > 1 and parts[1].isdigit():
        mode = parts[2] if len(parts) > 2 and parts[2] in ("m", "a", "s") else "m"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        return await card(ctx, int(parts[1]), mode if mode != "s" else "m", page)
    if act == "r" and len(parts) > 2 and parts[1].isdigit() and parts[2].isdigit():
        tid, stars = int(parts[1]), int(parts[2])
        mode = parts[3] if len(parts) > 3 and parts[3] in ("m", "a") else "m"
        page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        if not ctx.verified:
            return Out(toast="Оценки доступны после подтверждения ФИО", alert=True)
        if not 1 <= stars <= 5:
            return Out(toast="Неверная оценка", alert=True)
        t = await ctx.repo.get_teacher(tid)
        if not t or t["hidden"]:
            return Out(toast="Преподаватель недоступен", alert=True)
        if ctx.repo.flag("rate_only_own") and not ctx.is_admin:
            own = await ctx.repo.teacher_ids_for_group(ctx.user["group_id"])
            if tid not in own:
                return Out(toast="Оценивать можно только своих преподавателей", alert=True)
        status, days = await ctx.repo.rate_teacher(ctx.uid, tid, stars, ctx.repo.int_setting("rate_cooldown_days"))
        if status == "cooldown":
            return Out(toast=f"Оценку можно изменить через {days} дн.", alert=True)
        out = await card(ctx, tid, mode, page)
        out.toast = "Эта оценка уже стоит" if status == "same" else "Спасибо! Оценка сохранена ✅"
        return out
    return Out(toast="Неизвестное действие")


async def on_text(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if not ctx.repo.flag("rating_enabled"):
        return Out(screen=Screen("Раздел сейчас недоступен.", [[home_btn()]]), clear_state=True)
    found = await ctx.repo.search_teachers(text)
    seen = {t["id"] for t in found}
    catalog = await ctx.repo.subject_catalog()
    subj = find_subject(text, catalog)
    if subj:
        for t in await ctx.repo.teachers_by_subject(subj):
            if t["id"] not in seen:
                found.append(t)
                seen.add(t["id"])
    found = found[:8]
    if not found:
        return Out(screen=Screen("Никого не нашёл. Попробуйте другую фамилию или предмет.", [nav("t:l:m:0")]),
                   state="t:search", state_data={})
    kb: Kb = [[Btn(t["name"][:32], f"t:v:{t['id']}:s:0")] for t in found]
    kb.append(nav("t:l:m:0"))
    return Out(screen=Screen("Нашёл:", kb), clear_state=True)
