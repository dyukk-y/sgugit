"""HTTP API and static Telegram Mini App for group settings."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.exceptions import TelegramAPIError

from app.bot import logic_chat
from app import timeutil as tu

log = logging.getLogger(__name__)
MAX_AUTH_AGE = 24 * 60 * 60
SMART_MODES = {"off", "mention", "keywords", "active"}
WAIT_VALUES = {15, 30, 60, 120}
AUTODEL_VALUES = {0, 1, 5, 15, 60}
EVENING_TIMES = {"19:00", "20:00", "21:00", "22:00"}
BOOL_FIELDS = {"notifications_on", "evening_on", "pin_on", "changes_on", "cleanup_on"}
FIELD_NAMES = BOOL_FIELDS | {"smart_mode", "wait_min", "autodelete_min", "evening_time", "group_id"}


def validate_init_data(init_data: str, bot_token: str, now: int | None = None) -> dict:
    """Validate Telegram WebApp initData; never trust initDataUnsafe from the browser."""
    if not init_data or len(init_data) > 8192:
        raise ValueError("Пустые или слишком большие данные Telegram")
    values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    supplied_hash = values.pop("hash", "")
    if not supplied_hash:
        raise ValueError("Нет подписи Telegram")
    auth_date = int(values.get("auth_date", "0"))
    current = int(time.time()) if now is None else int(now)
    if auth_date <= 0 or current - auth_date > MAX_AUTH_AGE or auth_date > current + 60:
        raise ValueError("Сессия Telegram устарела. Закройте приложение и откройте снова.")
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(bot_token.encode(), b"WebAppData", hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash):
        raise ValueError("Подпись Telegram не прошла проверку")
    user = json.loads(values.get("user", "{}"))
    if not isinstance(user, dict) or not user.get("id"):
        raise ValueError("Telegram не передал пользователя")
    return user


async def _bot_permissions(app, chat_id: int) -> dict:
    try:
        member = await app.bot.get_chat_member(chat_id, app.bot.id)
        status = getattr(member.status, "value", member.status)
        admin = status in ("creator", "administrator")
        return {
            "status": status,
            "can_pin_messages": status == "creator" or (admin and bool(getattr(member, "can_pin_messages", False))),
            "can_delete_messages": status == "creator" or (admin and bool(getattr(member, "can_delete_messages", False))),
            "can_manage_chat": status == "creator" or (admin and bool(getattr(member, "can_manage_chat", False))),
            "can_send_messages": status not in ("left", "kicked"),
        }
    except TelegramAPIError as exc:
        log.info("Cannot inspect bot permissions in %s: %s", chat_id, exc)
        return {"status": "unknown", "can_pin_messages": False, "can_delete_messages": False,
                "can_manage_chat": False, "can_send_messages": False}


async def _user_can_manage(app, uid: int, chat: dict) -> tuple[bool, dict]:
    user = await app.repo.get_user(uid)
    tg_admin = False
    try:
        member = await app.bot.get_chat_member(int(chat["chat_id"]), uid)
        status = getattr(member.status, "value", member.status)
        tg_admin = status in ("creator", "administrator")
    except TelegramAPIError:
        status = "unknown"
    allowed = logic_chat.can_manage(user, chat, app.cfg.superadmin_id, tg_admin)
    return allowed, {"status": status, "telegram_admin": tg_admin}


async def _chat_payload(app, chat: dict) -> dict:
    group = await app.repo.get_group(chat.get("group_id"))
    return {
        "chat_id": int(chat["chat_id"]),
        "title": chat.get("title") or "Групповой чат",
        "group_id": chat.get("group_id"),
        "group_name": group["name"] if group else None,
        "smart_mode": chat.get("smart_mode", "mention"),
        "wait_min": int(chat.get("wait_min", 60)),
        "autodelete_min": int(chat.get("autodelete_min", 5)),
        "evening_on": bool(chat.get("evening_on", 0)),
        "evening_time": chat.get("evening_time", "20:00"),
        "pin_on": bool(chat.get("pin_on", 1)),
        "changes_on": bool(chat.get("changes_on", 1)),
        "notifications_on": bool(chat.get("notifications_on", 1)),
        "cleanup_on": bool(chat.get("cleanup_on", 0)),
    }


async def _authorized_chat(app, uid: int, chat_id: int) -> tuple[dict, dict, dict]:
    chat = await app.repo.get_chat(chat_id)
    if not chat or not chat.get("active"):
        raise web.HTTPNotFound(text="Чат не найден или бот больше не состоит в нём")
    allowed, user_status = await _user_can_manage(app, uid, chat)
    if not allowed:
        raise web.HTTPForbidden(text="Управлять настройками могут только администраторы группы и добавивший бота пользователь")
    return chat, user_status, await _bot_permissions(app, chat_id)


def create_webapp(app) -> web.Application:
    from pathlib import Path

    root = Path(__file__).resolve().parent / "web"

    @web.middleware
    async def no_cache(request, handler):
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    webapp = web.Application(client_max_size=16 * 1024, middlewares=[no_cache])

    async def index(request):
        return web.FileResponse(root / "index.html")

    def auth(request) -> dict:
        raw = request.headers.get("X-Telegram-Init-Data", "")
        try:
            return validate_init_data(raw, app.cfg.bot_token)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise web.HTTPUnauthorized(text=str(exc)) from exc

    async def bootstrap(request):
        user = auth(request)
        uid = int(user["id"])
        rows = await app.repo.db.fetchall("SELECT * FROM chats WHERE active = 1 ORDER BY title")
        available = []
        for chat in rows:
            allowed, user_status = await _user_can_manage(app, uid, chat)
            if not allowed:
                continue
            available.append({
                "chat": await _chat_payload(app, chat),
                "user": user_status,
                "bot": await _bot_permissions(app, int(chat["chat_id"])),
            })
        if not available:
            return web.json_response({"user": {"id": uid, "name": user.get("first_name", "Пользователь")},
                                      "chats": [], "groups": []})
        requested = request.query.get("chat_id", "")
        if requested:
            selected = next((x for x in available if str(x["chat"]["chat_id"]) == requested), None)
            if selected is None:
                raise web.HTTPForbidden(text="У вас нет доступа к настройкам этого чата")
        else:
            selected = available[0]
        groups = await app.repo.all_groups()
        return web.json_response({
            "user": {"id": uid, "name": user.get("first_name", "Пользователь")},
            "chats": available,
            "selected_chat_id": selected["chat"]["chat_id"],
            "groups": [{"id": int(g["id"]), "name": g["name"]} for g in groups],
        })

    async def update_settings(request):
        user = auth(request)
        uid = int(user["id"])
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="Некорректный JSON") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Ожидался объект настроек")
        try:
            chat_id = int(body.get("chat_id", 0))
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="Не указан чат") from exc
        chat, _, bot_perms = await _authorized_chat(app, uid, chat_id)
        updates = {k: v for k, v in body.items() if k in FIELD_NAMES}
        if not updates:
            raise web.HTTPBadRequest(text="Нет настроек для сохранения")
        for key in BOOL_FIELDS & updates.keys():
            if not isinstance(updates[key], bool):
                raise web.HTTPBadRequest(text=f"Неверное значение {key}")
            updates[key] = int(updates[key])
        if "smart_mode" in updates and updates["smart_mode"] not in SMART_MODES:
            raise web.HTTPBadRequest(text="Неизвестный режим ответов")
        if "wait_min" in updates and updates["wait_min"] not in WAIT_VALUES:
            raise web.HTTPBadRequest(text="Недопустимое время ожидания")
        if "autodelete_min" in updates and updates["autodelete_min"] not in AUTODEL_VALUES:
            raise web.HTTPBadRequest(text="Недопустимое время автоудаления")
        if "evening_time" in updates and updates["evening_time"] not in EVENING_TIMES:
            raise web.HTTPBadRequest(text="Недопустимое время вечерней сводки")
        if "group_id" in updates:
            try:
                gid = int(updates["group_id"]) if updates["group_id"] not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise web.HTTPBadRequest(text="Неверная учебная группа") from exc
            if gid is not None and not await app.repo.get_group(gid):
                raise web.HTTPBadRequest(text="Учебная группа не найдена")
            updates["group_id"] = gid
        if updates.get("evening_on") and not (updates.get("group_id", chat.get("group_id"))):
            raise web.HTTPBadRequest(text="Сначала привяжите учебную группу")
        await app.repo.update_chat(chat_id, **updates)
        updated = await app.repo.get_chat(chat_id)
        return web.json_response({"ok": True, "chat": await _chat_payload(app, updated), "bot": bot_perms})

    webapp.router.add_get("/", index)
    webapp.router.add_get("/api/bootstrap", bootstrap)
    webapp.router.add_post("/api/settings", update_settings)
    return webapp
