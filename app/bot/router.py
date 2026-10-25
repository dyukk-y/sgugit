"""Маршрутизация: превращает нажатия, тексты и команды в результат Out. Не зависит от aiogram."""
from __future__ import annotations

from datetime import timedelta

from app import timeutil as tu
from app.bot import logic_admin, logic_head, logic_hw, logic_schedule as ls, logic_teachers, logic_user
from app.bot.core import Btn, Ctx, Out, Screen, home_btn
from app.services import format as fm
from app.services.nlu import Intent, detect_intent, parse_hw_phrase

UNKNOWN_HINT = ("Не понял вопрос 🤔 Попробуйте, например: «какие завтра пары?», «где завтра первая пара?», "
                "«что задали?» — или пользуйтесь кнопками.")

# состояния, в которых бот ждёт нажатия кнопки, а не текста
BUTTON_STATES = {"hw:pick", "hw:confirm", "reg:fio_confirm", "ad:bc_confirm", "ad:restore_confirm", "hd:bc_confirm"}


def _maintenance(ctx: Ctx) -> Out | None:
    if ctx.repo.flag("maintenance") and not ctx.is_admin:
        return Out(screen=Screen("🛠 Идут технические работы. Скоро всё заработает, попробуйте чуть позже."))
    return None


async def handle_callback(ctx: Ctx, data: str) -> Out:
    if data == "noop":
        return Out()
    block = _maintenance(ctx)
    if block:
        return block
    parts = data.split(":")
    head, rest = parts[0], parts[1:]
    if head == "m":
        return Out(screen=await logic_user.main_menu(ctx), clear_state=True)
    if head == "ad":
        return await logic_admin.on_cb(ctx, rest)
    if head == "r":
        return await logic_user.on_cb_register(ctx, rest)
    if head == "me":
        return await logic_user.on_cb_me(ctx, rest)
    if head == "hd":
        return Out(toast="Панель старост отключена", alert=True)
    if head in ("s", "h", "t") and not ctx.registered:
        return await logic_user.start(ctx)
    if head == "s":
        act = rest[0] if rest else "d"
        other = _gid(rest[2]) if len(rest) > 2 and act in ("d", "w", "c") else None
        arg = rest[1] if len(rest) > 1 else ("today" if act == "d" else "cur")
        if act == "d":
            return Out(screen=await ls.day_screen(ctx, arg, other), clear_state=True)
        if act == "w":
            return Out(screen=await ls.week_screen(ctx, arg, other), clear_state=True)
        if act == "c":
            return Out(screen=await ls.calendar_screen(ctx, arg, other))
        if act == "n":
            return Out(screen=await ls.next_lesson_screen(ctx))
        return Out(toast="Неизвестное действие")
    if head == "h":
        return await logic_hw.on_cb_hw(ctx, rest)
    if head == "t":
        return await logic_teachers.on_cb(ctx, rest)
    return Out(toast="Неизвестное действие")


def _gid(s: str) -> int | None:
    return int(s) if s.isdigit() else None


async def handle_text(ctx: Ctx, text: str) -> Out:
    """Текст в личном чате: ввод для текущего шага или вопрос обычными словами."""
    block = _maintenance(ctx)
    if block:
        return block
    state, data = await ctx.repo.get_state(ctx.uid)
    if state:
        if state in BUTTON_STATES:
            return Out()
        prefix = state.split(":")[0]
        if prefix == "reg":
            return await logic_user.on_text_register(ctx, state, data, text)
        if prefix == "me":
            return await logic_user.on_text_me(ctx, state, data, text)
        if prefix == "hw":
            return await logic_hw.on_text_hw(ctx, state, data, text)
        if prefix == "t":
            return await logic_teachers.on_text(ctx, state, data, text)
        if prefix == "ad":
            return await logic_admin.on_text(ctx, state, data, text)
        if prefix == "hd":
            return await logic_head.on_text(ctx, state, data, text)
    if not ctx.registered:
        return await logic_user.start(ctx)
    gid = ctx.user["group_id"]
    catalog = await ctx.repo.subject_catalog()
    phrase = parse_hw_phrase(text, catalog, ctx.today)
    if phrase:
        return await logic_hw.quick_add(ctx, phrase)
    intent = detect_intent(text, ctx.today, catalog, await ctx.repo.known_surnames())
    if intent is not None:
        answer = await ls.answer_intent(ctx, intent, gid, ctx.user.get("subgroup"))
        if answer is not None:
            if answer.kb is None:
                answer.kb = [[home_btn()]]
            return Out(screen=answer)
    menu = await logic_user.main_menu(ctx)
    hint = ctx.repo.setting("unknown_text") or UNKNOWN_HINT
    menu.text = hint + "\n\n" + menu.text
    return Out(screen=menu)


async def handle_document(ctx: Ctx, filename: str, blob: bytes, file_id: str | None = None) -> Out:
    state, data = await ctx.repo.get_state(ctx.uid)
    if state and state.startswith("ad:"):
        return await logic_admin.on_document(ctx, state, filename, blob)
    if state == "hw:replace_media" and file_id:
        hid = int(data.get("hid", 0)); hw = await ctx.repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or logic_hw.can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True, clear_state=True)
        await ctx.repo.update_hw(hid, media_file_id=file_id, media_type="document", media_name=filename[:120])
        await ctx.repo.audit(ctx.uid, "hw_replace_media", str(hid))
        out = await logic_hw.view_screen(ctx, hid); out.clear_state = True; return out
    if state in ("hw:text", "hw:confirm") and file_id:
        data.update(media_file_id=file_id, media_type="document", media_name=filename[:120])
        if state == "hw:confirm":
            return Out(screen=logic_hw._preview(ctx, data), state=state, state_data=data)
        data.setdefault("text", filename)
        return Out(screen=Screen("Файл добавлен к черновику. Теперь отправьте текст задания или продолжите кнопкой.",
                                 [[Btn("❌ Отмена", "h:cancel")]]), state=state, state_data=data)
    return Out()


async def handle_photo(ctx: Ctx, file_id: str, caption: str = "") -> Out:
    state, data = await ctx.repo.get_state(ctx.uid)
    if state == "ad:bc_text" and ctx.can("broadcast"):
        data.update(media_file_id=file_id, media_type="photo")
        if caption.strip():
            data["text"] = caption.strip()[:900]
            n = len(await logic_admin._recipients(ctx, data))
            return Out(screen=Screen(f"<b>Предпросмотр рассылки с фото</b>\n\n{fm.esc(caption[:900])}\n\nПолучателей: {n}",
                                     [[Btn(f"✅ Отправить ({n})", "ad:bcy"), Btn("❌ Отмена", "ad:bc")]]),
                       state="ad:bc_confirm", state_data=data)
        return Out(screen=Screen("📷 Фото добавлено к рассылке. Теперь отправьте текст подписи или нажмите «Отправить без текста».",
                                 [[Btn("📤 Отправить без текста", "ad:bcp"), Btn("❌ Отмена", "ad:bc")]]),
                   state="ad:bc_text", state_data=data)
    if state == "hw:replace_media":
        hid = int(data.get("hid", 0)); hw = await ctx.repo.get_hw(hid)
        if not hw or not (hw["author_id"] == ctx.uid or logic_hw.can_moderate(ctx, hw)):
            return Out(toast="Нет прав", alert=True, clear_state=True)
        await ctx.repo.update_hw(hid, media_file_id=file_id, media_type="photo", media_name="photo")
        await ctx.repo.audit(ctx.uid, "hw_replace_media", str(hid))
        out = await logic_hw.view_screen(ctx, hid); out.clear_state = True; return out
    if state not in ("hw:text", "hw:confirm"):
        return Out(screen=Screen("Чтобы прикрепить фото, сначала начните добавление задания."))
    data.update(media_file_id=file_id, media_type="photo", media_name="photo")
    if caption.strip():
        data["text"] = caption.strip()[:1000]
        return Out(screen=logic_hw._preview(ctx, data), state="hw:confirm", state_data=data)
    return Out(screen=Screen("Фото добавлено к черновику. Отправьте текст задания следующим сообщением.",
                             [[Btn("❌ Отмена", "h:cancel")]]), state=state, state_data=data)


async def handle_command(ctx: Ctx, name: str, args: str = "") -> Out | None:
    """Команды в личном чате. None - команда не распознана (для скрытых админ-команд)."""
    block = _maintenance(ctx) if name != "admin" else None
    if block:
        return block
    if name == "start":
        if args.startswith("hw_") and args[3:].isdigit() and ctx.registered:
            out = await logic_hw.view_screen(ctx, int(args[3:]))
            return out
        return await logic_user.start(ctx)
    if name in ("menu", "home"):
        return Out(screen=await logic_user.main_menu(ctx), clear_state=True) if ctx.registered else await logic_user.start(ctx)
    if name == "ping" and ctx.is_admin:
        return Out(screen=Screen(f"🏓 Бот отвечает. Ваша роль: {ctx.role}. Время: {ctx.now:%d.%m.%Y %H:%M}."), clear_state=True)
    if name == "admin":
        if not ctx.is_admin:
            return None
        return Out(screen=await logic_admin.menu_screen(ctx), clear_state=True)
    if not ctx.registered:
        return await logic_user.start(ctx)
    if name == "today":
        return Out(screen=await ls.day_screen(ctx, "today"), clear_state=True)
    if name == "tomorrow":
        return Out(screen=await ls.day_screen(ctx, "tom"), clear_state=True)
    if name == "week":
        return Out(screen=await ls.week_screen(ctx, "cur"), clear_state=True)
    if name == "next":
        return Out(screen=await ls.next_lesson_screen(ctx))
    if name == "hw":
        return Out(screen=await logic_hw.list_screen(ctx, 0), clear_state=True)
    if name == "help":
        return Out(screen=Screen(ls.HELP_TEXT, [[home_btn()]]))
    return None


# ---------------- группы ----------------
GROUP_COMMANDS = {"today", "tomorrow", "week", "next", "hw", "schedule", "homework"}
GROUP_COMMAND_ALIASES = {"schedule": "today", "homework": "hw"}


async def group_command(ctx: Ctx, gid: int, name: str) -> Screen | None:
    name = GROUP_COMMAND_ALIASES.get(name, name)
    if name == "today":
        return await ls.answer_intent(ctx, Intent("day", day=ctx.today, explicit_day=True), gid, None, allow_kb=False)
    if name == "tomorrow":
        return await ls.answer_intent(ctx, Intent("day", day=ctx.today + timedelta(days=1), explicit_day=True), gid, None,
                                      allow_kb=False)
    if name == "week":
        return await ls.answer_intent(ctx, Intent("week", week_shift=0), gid, None, allow_kb=False)
    if name == "next":
        return await ls.answer_intent(ctx, Intent("next"), gid, None, allow_kb=False)
    if name == "hw":
        return await ls.answer_intent(ctx, Intent("hw"), gid, None, allow_kb=False)
    return None


KEYWORD_INTENTS = {"day", "first", "last", "next", "count", "room", "teacher", "week", "hw", "when_subject", "exam",
                   "subject_day", "find_teacher"}


async def group_text(ctx: Ctx, gid: int, text: str, mode: str, addressed: bool) -> Screen | None:
    """Ответ на сообщение в группе. mode: off | mention | keywords. addressed - упомянули бота или ответили ему."""
    if mode == "off":
        return None
    if mode in ("mention", "active") and not addressed:
        return None  # в активном режиме вопросы без обращения обрабатывает QuestionService (с ожиданием)
    catalog = await ctx.repo.subject_catalog()
    intent = detect_intent(text, ctx.today, catalog, await ctx.repo.known_surnames())
    if intent is None:
        return None
    if intent.name in ("greet", "thanks") and not addressed:
        return None
    if not addressed and intent.name not in KEYWORD_INTENTS:
        return None
    return await ls.answer_intent(ctx, intent, gid, None, allow_kb=False)
