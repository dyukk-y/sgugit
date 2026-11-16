"""Компактное анонимное оценивание преподавателей по реальным видам занятий."""
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
    criteria = await ctx.repo.teacher_rating_criteria(t["norm"])
    summaries = {r["criterion"]: r for r in await ctx.repo.teacher_rating_score_summary(tid)}
    lines = [f"<b>{fm.esc(t['name'])}</b>"]
    if subs:
        lines.append("Предметы: " + fm.esc(", ".join(subs)))
    lines.append(_stars_text(t["avg"], t["cnt"], min_votes))
    if mine:
        lines.append(f"Ваша общая оценка: {'⭐' * mine}")
    pros, cons = [], []
    for item in criteria:
        summary = summaries.get(item["key"])
        if not summary or not summary.get("cnt"):
            continue
        avg = float(summary["avg"])
        lines.append(f"· {fm.esc(item['label'])}: {avg:.1f}/5 ({summary['cnt']})".replace(".", ","))
        if avg >= 4.0:
            pros.append(item["label"].lower())
        elif avg <= 3.0:
            cons.append(item["label"].lower())
    if pros:
        lines.append("👍 Сильные стороны: " + ", ".join(pros[:4]))
    if cons:
        lines.append("👎 Что можно улучшить: " + ", ".join(cons[:4]))
    comments = await ctx.repo.public_teacher_rating_comments(tid, 3)
    if comments:
        lines.append("\n<b>Комментарии студентов</b>")
        for item in comments:
            # В публичной выборке нет user_id, username или имени автора.
            lines.append("“" + fm.esc(item["comment"]) + "”")
    kb: Kb = []
    if ctx.verified or ctx.is_admin:
        if criteria:
            kb.append([Btn("⭐ Оценить преподавателя", f"t:begin:{tid}:{mode}:{page}")])
            lines.append("\nОценка доступна по тем видам занятий, которые есть в расписании этого преподавателя.")
        else:
            lines.append("\n<i>В расписании пока нет видов занятий для оценки.</i>")
    else:
        lines.append("\n<i>Оценки доступны после подтверждения ФИО.</i>")
    if ctx.is_admin:
        kb.append([Btn("🔐 Авторы комментариев (админ)", f"t:admincomments:{tid}:{mode}:{page}")])
    kb.append(nav(f"t:l:{mode}:{page}"))
    return Out(screen=Screen("\n".join(lines), kb))


async def _rating_step(ctx: Ctx, tid: int, criteria: list[dict], index: int, mode: str, page: int) -> Out:
    if index >= len(criteria):
        return Out(screen=Screen("Оценки по всем доступным пунктам сохранены. Хотите добавить комментарий?\n\n"
                                 "Он будет опубликован без имени автора. Идентификатор отправителя доступен только администрации.",
                                 [[Btn("✍️ Добавить комментарий", f"t:comment:{tid}:{mode}:{page}")],
                                  [Btn("Пропустить", f"t:skipcomment:{tid}:{mode}:{page}")]]),
                   state="t:comment", state_data={"tid": tid, "mode": mode, "page": page})
    item = criteria[index]
    kb = [[Btn(f"{n}⭐", f"t:score:{tid}:{index}:{n}:{mode}:{page}") for n in range(1, 6)],
          [Btn("✖ Отменить", f"t:cancel:{tid}:{mode}:{page}")]]
    return Out(screen=Screen(f"<b>{fm.esc(item['label'])}</b>\n\nНасколько хорошо преподаватель ведёт этот вид занятий?\nВыберите оценку от 1 до 5.\n\nПункт {index + 1} из {len(criteria)}", kb),
               state="t:rating", state_data={"tid": tid, "criteria": criteria, "index": index,
                                             "mode": mode, "page": page})


async def on_cb(ctx: Ctx, parts: list[str]) -> Out:
    if not ctx.repo.flag("rating_enabled"):
        return _disabled()
    if not ctx.registered:
        return Out(screen=Screen("Сначала выберите группу: нажмите /start.", [[home_btn()]]))
    if not ctx.verified and not ctx.is_admin:
        if ctx.user.get("fio_status") == "pending":
            prompt = Screen("ФИО уже отправлено на проверку. Раздел откроется после подтверждения.",
                            [[Btn("👤 Профиль", "me:prof")], [home_btn()]])
        else:
            return Out(screen=Screen(
                "Чтобы пользоваться оценками преподавателей, сначала укажите ФИО.\n\n"
                "Введите полностью: <code>Фамилия Имя Отчество</code>. Бот проверит данные и после подтверждения откроет раздел.",
                [[home_btn()]]), state="reg:fio", state_data={})
        return Out(screen=prompt)
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
    if act == "begin" and len(parts) >= 2 and parts[1].isdigit():
        tid = int(parts[1]); mode = parts[2] if len(parts) > 2 else "m"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        teacher = await ctx.repo.get_teacher(tid)
        if not teacher or teacher["hidden"]:
            return Out(toast="Преподаватель недоступен", alert=True)
        if ctx.repo.flag("rate_only_own") and not ctx.is_admin:
            own = await ctx.repo.teacher_ids_for_group(ctx.user["group_id"])
            if tid not in own:
                return Out(toast="Оценивать можно только своих преподавателей", alert=True)
        criteria = await ctx.repo.teacher_rating_criteria(teacher["norm"])
        if not criteria:
            return Out(toast="В расписании нет пунктов для оценки", alert=True)
        return await _rating_step(ctx, tid, criteria, 0, mode, page)
    if act == "score" and len(parts) >= 6 and all(parts[i].isdigit() for i in (1, 2, 3)):
        tid, index, stars = int(parts[1]), int(parts[2]), int(parts[3])
        mode = parts[4] if parts[4] in ("m", "a") else "m"
        page = int(parts[5]) if parts[5].isdigit() else 0
        state, data = await ctx.repo.get_state(ctx.uid)
        if state != "t:rating" or int(data.get("tid", 0)) != tid:
            return Out(toast="Сессия оценки устарела. Откройте карточку заново.", alert=True)
        criteria = data.get("criteria") or []
        if not 0 <= index < len(criteria) or not 1 <= stars <= 5:
            return Out(toast="Некорректная оценка", alert=True)
        teacher = await ctx.repo.get_teacher(tid)
        if not teacher or teacher["hidden"]:
            return Out(toast="Преподаватель недоступен", alert=True)
        if ctx.repo.flag("rate_only_own") and not ctx.is_admin:
            own = await ctx.repo.teacher_ids_for_group(ctx.user["group_id"])
            if tid not in own:
                return Out(toast="Оценивать можно только своих преподавателей", alert=True)
        await ctx.repo.save_teacher_rating_score(ctx.uid, tid, criteria[index]["key"], stars)
        await ctx.repo.audit(ctx.uid, "teacher_criterion_rating", f"{tid}:{criteria[index]['key']}:{stars}")
        if index + 1 >= len(criteria):
            own_scores = await ctx.repo.my_teacher_rating_scores(ctx.uid, tid)
            values = [own_scores[item["key"]] for item in criteria if item["key"] in own_scores]
            if values:
                overall = max(1, min(5, int(round(sum(values) / len(values)))))
                await ctx.repo.rate_teacher(ctx.uid, tid, overall, 0)
        return await _rating_step(ctx, tid, criteria, index + 1, mode, page)
    if act == "comment" and len(parts) >= 2 and parts[1].isdigit():
        tid = int(parts[1]); mode = parts[2] if len(parts) > 2 else "m"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        return Out(screen=Screen("Напишите короткий комментарий (до 600 символов). Не указывайте личные данные.", 
                                 [[Btn("Пропустить", f"t:skipcomment:{tid}:{mode}:{page}")]]),
                   state="t:comment", state_data={"tid": tid, "mode": mode, "page": page})
    if act == "admincomments" and len(parts) >= 2 and parts[1].isdigit():
        if not ctx.is_admin:
            return Out(toast="Недостаточно прав", alert=True)
        tid = int(parts[1])
        rows = await ctx.repo.admin_teacher_rating_comments(tid)
        lines = ["<b>Комментарии и авторы (только администрация)</b>"]
        for row in rows:
            who = ("@" + row["username"]) if row.get("username") else (row.get("tg_name") or str(row["user_id"]))
            lines.append(f"\n<b>{fm.esc(str(who))}</b> · ID <code>{row['user_id']}</code>\n{fm.esc(row['comment'])}")
        if not rows:
            lines.append("\nКомментариев пока нет.")
        return Out(screen=Screen("\n".join(lines), [nav(f"t:v:{tid}:m:0")]))
    if act == "skipcomment" and len(parts) >= 2 and parts[1].isdigit():
        tid = int(parts[1]); mode = parts[2] if len(parts) > 2 else "m"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        out = await card(ctx, tid, mode, page); out.clear_state = True; return out
    if act == "cancel" and len(parts) >= 2 and parts[1].isdigit():
        tid = int(parts[1]); mode = parts[2] if len(parts) > 2 else "m"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        out = await card(ctx, tid, mode, page); out.clear_state = True; return out
    # Старые callback-ссылки безопасно перенаправляем на карточку.
    if act in ("r", "c") and len(parts) > 1 and parts[1].isdigit():
        return await card(ctx, int(parts[1]))
    return Out(toast="Неизвестное действие")


async def on_text(ctx: Ctx, state: str, data: dict, text: str) -> Out:
    if not ctx.repo.flag("rating_enabled"):
        return Out(screen=Screen("Раздел сейчас недоступен.", [[home_btn()]]), clear_state=True)
    if state == "t:rating":
        return Out(screen=Screen("Пожалуйста, выберите оценку кнопкой от 1 до 5."), state=state, state_data=data)
    if state == "t:comment":
        tid = int(data.get("tid", 0))
        if not tid:
            return Out(screen=Screen("Не удалось определить преподавателя. Откройте карточку заново.", [[home_btn()]]), clear_state=True)
        comment = text.strip()
        if len(comment) > 600:
            return Out(screen=Screen("Комментарий слишком длинный. Максимум — 600 символов. Сократите его и отправьте ещё раз."),
                       state="t:comment", state_data=data)
        if comment and not ctx.verified and not ctx.is_admin:
            return Out(screen=Screen("Для отправки комментария нужно подтверждённое ФИО.", [[home_btn()]]), clear_state=True)
        if comment:
            await ctx.repo.save_teacher_rating_comment(ctx.uid, tid, comment)
            await ctx.repo.audit(ctx.uid, "teacher_rating_comment", str(tid))
        out = await card(ctx, tid, data.get("mode", "m"), int(data.get("page", 0))); out.clear_state = True; return out
    if not ctx.verified and not ctx.is_admin:
        if ctx.user.get("fio_status") == "pending":
            prompt = Screen("ФИО уже отправлено на проверку. Раздел откроется после подтверждения.",
                            [[Btn("👤 Профиль", "me:prof")], [home_btn()]])
        else:
            return Out(screen=Screen(
                "Чтобы пользоваться оценками преподавателей, сначала укажите ФИО.\n\n"
                "Введите полностью: <code>Фамилия Имя Отчество</code>. Бот проверит данные и после подтверждения откроет раздел.",
                [[home_btn()]]), state="reg:fio", state_data={})
        return Out(screen=prompt, clear_state=True)
    found = await ctx.repo.search_teachers(text)
    seen = {t["id"] for t in found}
    catalog = await ctx.repo.subject_catalog()
    subj = find_subject(text, catalog)
    if subj:
        for t in await ctx.repo.teachers_by_subject(subj):
            if t["id"] not in seen:
                found.append(t); seen.add(t["id"])
    found = found[:8]
    if not found:
        return Out(screen=Screen("Никого не нашёл. Попробуйте другую фамилию или предмет.", [nav("t:l:m:0")]),
                   state="t:search", state_data={})
    kb: Kb = [[Btn(t["name"][:32], f"t:v:{t['id']}:s:0")] for t in found]
    kb.append(nav("t:l:m:0"))
    return Out(screen=Screen("Нашёл:", kb), clear_state=True)
