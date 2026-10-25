"""Настройки группового чата. Не зависит от aiogram."""
from __future__ import annotations

from app.bot.core import Btn, Kb, Screen
from app.db.repo import Repo
from app.services import format as fm

SMART_MODES = ["off", "mention", "keywords", "active"]
SMART_LABEL = {"off": "выключены", "mention": "по упоминанию и ответу боту", "keywords": "сразу по ключевым фразам",
               "active": "активный: отвечу, если никто не ответил"}
SHORT_SMART = {"off": "выкл", "mention": "по упоминанию", "keywords": "по ключевым фразам", "active": "активный"}
WAIT_VALUES = [15, 30, 60, 120]
AUTODEL = [0, 1, 5, 15, 60]
EVENING_TIMES = ["19:00", "20:00", "21:00", "22:00"]


def can_manage(user: dict | None, chat: dict, super_id: int, tg_admin: bool = False) -> bool:
    """Управлять чатом может добавивший бота, староста этой группы, админ бота, админ чата в Telegram."""
    if user is None:
        return tg_admin
    uid = user["id"]
    if uid == super_id or uid == chat.get("added_by") or tg_admin:
        return True
    if user.get("role") == "admin":
        return True
    return user.get("role") == "head" and chat.get("group_id") is not None and user.get("group_id") == chat["group_id"]


def _onoff(on: bool) -> str:
    return "ВКЛ ✅" if on else "ВЫКЛ ⬜"


async def screen(repo: Repo, chat: dict) -> Screen:
    """Настройки чата. Каждая настройка — отдельная кнопка на всю ширину с текущим значением в подписи:
    на телефоне кнопки в несколько колонок обрезают текст, поэтому колонок нет."""
    g = await repo.get_group(chat.get("group_id"))
    cid = chat["chat_id"]
    ad = chat["autodelete_min"]
    ev_on, ch_on, pin_on = bool(chat["evening_on"]), bool(chat.get("changes_on", 1)), bool(chat.get("pin_on", 1))
    text = ("<b>Настройки чата</b>\n"
            f"Группа: {fm.esc(g['name']) if g else 'не привязана'}\n\n"
            "Нажмите на пункт, чтобы переключить его. Текущее значение написано на кнопке.\n\n"
            f"🌙 Вечерняя сводка на завтра: {'в ' + chat['evening_time'] if ev_on else 'выкл'}\n"
            f"📌 Закреп сводки: {'до начала первой пары' if ev_on and pin_on else 'выкл'}\n"
            f"🔔 Изменения расписания: {'присылать' if ch_on else 'не присылать'}\n"
            f"💬 Умные ответы: {SMART_LABEL.get(chat['smart_mode'], chat['smart_mode'])}")
    if ev_on and pin_on:
        text += "\n\nℹ️ Для закрепа боту нужно право «Закреплять сообщения» (сделайте его администратором)."
    kb: Kb = [
        [Btn(f"🌙 Вечерняя сводка: {_onoff(ev_on)}", f"cs:{cid}:ev")],
        [Btn(f"🕘 Время сводки: {chat['evening_time']}", f"cs:{cid}:et")],
        [Btn(f"📌 Закреп до первой пары: {_onoff(pin_on)}", f"cs:{cid}:pn")],
        [Btn(f"🔔 Изменения расписания: {_onoff(ch_on)}", f"cs:{cid}:ch")],
        [Btn(f"💬 Умные ответы: {SHORT_SMART.get(chat['smart_mode'], chat['smart_mode'])}", f"cs:{cid}:sm")],
        [Btn(f"⏳ Ждать ответа людей: {chat.get('wait_min', 60)} мин", f"cs:{cid}:wt")],
        [Btn(f"🧹 Автоудаление ответов: {'выкл' if not ad else f'{ad} мин'}", f"cs:{cid}:ad")],
        [Btn("🔗 Привязать к моей группе", f"cs:{cid}:grp")],
    ]
    return Screen(text, kb)


def _next(values: list, current) -> object:
    try:
        return values[(values.index(current) + 1) % len(values)]
    except ValueError:
        return values[0]


async def apply(repo: Repo, chat: dict, user: dict | None, act: str) -> str | None:
    """Применяет действие. Возвращает текст всплывающего уведомления при отказе, иначе None."""
    cid = chat["chat_id"]
    if act == "grp":
        if not user or not user.get("group_id"):
            return "Сначала зарегистрируйтесь в боте и выберите группу"
        await repo.update_chat(cid, group_id=user["group_id"])
    elif act == "sm":
        await repo.update_chat(cid, smart_mode=_next(SMART_MODES, chat["smart_mode"]))
    elif act == "wt":
        await repo.update_chat(cid, wait_min=_next(WAIT_VALUES, chat.get("wait_min", 60)))
    elif act == "ad":
        await repo.update_chat(cid, autodelete_min=_next(AUTODEL, chat["autodelete_min"]))
    elif act == "ev":
        if chat.get("group_id") is None:
            return "Сначала привяжите группу"
        await repo.update_chat(cid, evening_on=0 if chat["evening_on"] else 1)
    elif act == "et":
        await repo.update_chat(cid, evening_time=_next(EVENING_TIMES, chat["evening_time"]))
    elif act == "ch":
        await repo.update_chat(cid, changes_on=0 if chat.get("changes_on", 1) else 1)
    elif act == "pn":
        await repo.update_chat(cid, pin_on=0 if chat.get("pin_on", 1) else 1)
    else:
        return "Неизвестное действие"
    return None
