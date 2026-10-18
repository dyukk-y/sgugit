"""Настройки группового чата. Не зависит от aiogram."""
from __future__ import annotations

from app.bot.core import Btn, Kb, Screen
from app.db.repo import Repo
from app.services import format as fm

SMART_MODES = ["off", "mention", "keywords", "active"]
SMART_LABEL = {"off": "выключены", "mention": "по упоминанию и ответу боту", "keywords": "сразу по ключевым фразам",
               "active": "активный: отвечу, если никто не ответил"}
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


async def screen(repo: Repo, chat: dict) -> Screen:
    g = await repo.get_group(chat.get("group_id"))
    cid = chat["chat_id"]
    ad = chat["autodelete_min"]
    text = ("<b>Настройки чата</b>\n"
            f"Группа: {fm.esc(g['name']) if g else 'не привязана'}\n"
            f"Умные ответы: {SMART_LABEL.get(chat['smart_mode'], chat['smart_mode'])}\n"
            f"Ожидание ответа людей (активный режим): {chat.get('wait_min', 60)} мин\n"
            f"Автоудаление ответов: {'выкл' if not ad else f'через {ad} мин'}\n"
            f"Вечерняя сводка: {'в ' + chat['evening_time'] if chat['evening_on'] else 'выкл'}")
    kb: Kb = [[Btn("🔄 Привязать к моей группе", f"cs:{cid}:grp")],
              [Btn("💬 Умные ответы", f"cs:{cid}:sm"), Btn("🧹 Автоудаление", f"cs:{cid}:ad")],
              [Btn("⏳ Время ожидания", f"cs:{cid}:wt")],
              [Btn("🌙 Сводка вкл/выкл", f"cs:{cid}:ev"), Btn("🕘 Время сводки", f"cs:{cid}:et")]]
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
    else:
        return "Неизвестное действие"
    return None
