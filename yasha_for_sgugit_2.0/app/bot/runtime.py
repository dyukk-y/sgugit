"""Единая точка обработки обновлений: загрузка пользователя, маршрутизация, сохранение состояния диалога."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.bot import router
from app.bot.core import Ctx, Out
from app.config import Settings
from app.db.repo import Repo


async def process(repo: Repo, cfg: Settings, uid: int, username: str | None, name: str | None, *,
                  callback: str | None = None, text: str | None = None, command: str | None = None,
                  args: str = "", document: tuple[str, bytes] | None = None, attachment_file_id: str | None = None,
                  attachment_kind: str | None = None, attachment_caption: str = "",
                  services: dict[str, Any] | None = None, bot_username: str = "bot",
                  now: datetime | None = None) -> Out:
    user = await repo.touch_user(uid, username, name)
    if user["banned"] and uid != cfg.superadmin_id:
        return Out()
    if user.get("bot_blocked"):
        await repo.update_user(uid, bot_blocked=0)
        user["bot_blocked"] = 0
    ctx = Ctx(repo, cfg, user, now=now, bot_username=bot_username)
    ctx.services = services or {}
    out: Out | None
    if command is not None:
        out = await router.handle_command(ctx, command, args)
    elif callback is not None:
        out = await router.handle_callback(ctx, callback)
    elif document is not None:
        out = await router.handle_document(ctx, document[0], document[1], attachment_file_id)
    elif attachment_file_id and attachment_kind == "photo":
        out = await router.handle_photo(ctx, attachment_file_id, attachment_caption)
    elif text is not None:
        out = await router.handle_text(ctx, text)
    else:
        out = Out()
    if out is None:
        return Out()
    if out.state:
        await repo.set_state(uid, out.state, out.state_data)
    elif out.clear_state:
        await repo.clear_state(uid)
    return out
