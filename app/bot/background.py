"""Фоновые задачи: синхронизация, уведомления, ожидающие вопросы, бэкапы, уборка."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InputMediaDocument

from app import timeutil as tu
from app.bot import tg
from app.services import backup as bk
from app.services.directory import DirectorySync
from app.services.notifier import Notifier
from app.services.fio_verify import auto_verify_pending
from app.bot.core import Screen
from app.services.sync import SyncService

log = logging.getLogger(__name__)


async def _forever(name: str, interval: float, job: Callable[[], Awaitable[None]], first_delay: float = 0) -> None:
    """Запускает job по кругу; ошибка одной итерации не останавливает задачу."""
    if first_delay:
        await asyncio.sleep(first_delay)
    while True:
        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в фоновой задаче %s", name)
        await asyncio.sleep(interval)


async def notify_super(app: tg.App, text: str) -> None:
    try:
        await app.bot.send_message(app.cfg.superadmin_id, text[:4000])
    except TelegramAPIError as e:
        log.warning("Не удалось написать главному админу: %s", e)


async def push_backup(app: tg.App, reason: str) -> None:
    """Бэкап живёт в ОДНОМ сообщении у главного админа: первый раз бот присылает файл, дальше каждый час
    заменяет файл в этом же сообщении (edit_message_media) и дописывает строку в историю в подписи.
    Telegram хранит в сообщении только один файл, поэтому предыдущие версии лежат в BACKUP_DIR на сервере."""
    repo, cfg = app.repo, app.cfg
    name, blob = await bk.make_backup(repo)
    try:
        bk.save_local(cfg.backup_dir, name, blob, keep=72)
    except OSError:
        log.warning("Локальная копия бэкапа не сохранена")
    try:
        history = json.loads(repo.setting("backup_history") or "[]")
    except ValueError:
        history = []
    history.append(f"{tu.now_local():%d.%m %H:%M} — {reason}")
    history = history[-10:]
    caption = ("💾 Резервная копия базы (файл обновляется в этом сообщении)\n"
               f"Последнее обновление: {history[-1]}\n\nИстория:\n" + "\n".join(f"• {h}" for h in reversed(history)))[:1000]
    msg_id = int(repo.setting("backup_msg_id") or 0)
    if msg_id:
        try:
            await app.bot.edit_message_media(
                chat_id=cfg.superadmin_id, message_id=msg_id,
                media=InputMediaDocument(media=BufferedInputFile(blob, filename=name), caption=caption))
            await repo.set_setting("backup_history", json.dumps(history, ensure_ascii=False))
            return
        except TelegramAPIError as e:
            # сообщение удалено или недоступно для правки — отправим новое и дальше будем править его
            log.info("Бэкап: правка сообщения не удалась (%s), отправляю новое", e)
    try:
        sent = await app.bot.send_document(cfg.superadmin_id, BufferedInputFile(blob, filename=name), caption=caption)
    except TelegramAPIError as e:
        log.warning("Бэкап не отправлен: %s", e)
        return
    await repo.set_setting("backup_msg_id", str(sent.message_id))
    await repo.set_setting("backup_history", json.dumps(history, ensure_ascii=False))


def start_all(app: tg.App, sync: SyncService, directory: DirectorySync, notifier: Notifier) -> list[asyncio.Task]:
    repo, cfg = app.repo, app.cfg
    state = {"hourly": 0.0}

    async def sync_job() -> None:
        if repo.flag("sync_enabled"):
            await sync.run_once()

    async def directory_job() -> None:
        if repo.setting("dir_source") == "file":
            return  # справочник загружен файлом: автоматически не перезаписываем
        last = int(repo.setting("dir_last_ok") or 0)
        if tu.now_ts() - last >= 6 * 86400:  # раз в неделю
            ok, msg = await directory.run_once()
            if not ok:
                await repo.set_setting("dir_last_try", str(tu.now_ts()))

    async def notify_job() -> None:
        await notifier.tick()

    async def questions_job() -> None:
        await tg.answer_due_questions(app)

    async def auto_verify_fio_job() -> None:
        # Подтверждаем только уверенные случаи (строгая проверка + реальная фамилия); сомнительные остаются админам.
        async def notify(uid: int, text: str) -> None:
            await app.sender.enqueue(uid, Screen(text))

        await auto_verify_pending(repo, notify)

    async def send_backup(reason: str) -> None:
        await push_backup(app, reason)

    async def backup_job() -> None:
        now = tu.now_local()
        if not repo.setting("backup_msg_id"):  # первый запуск: файл придёт отдельным сообщением, дальше оно правится
            repo.db.dirty = False
            state["hourly"] = time.monotonic()
            await send_backup("первый запуск")
            return
        if now.hour >= 3 and await repo.first_time(f"bk:{tu.iso(now.date())}"):
            await send_backup("ежедневная")
            app.repo.db.dirty = False
            state["hourly"] = time.monotonic()
            return
        if repo.db.kind == "sqlite" and repo.db.dirty and time.monotonic() - state["hourly"] > 3300:
            repo.db.dirty = False  # сбрасываем до копирования: изменения во время копирования пометят базу снова
            state["hourly"] = time.monotonic()
            await send_backup("после изменений")

    async def unpin_job() -> None:
        """Открепляет сводки, у которых наступило время начала первой пары."""
        for row in await repo.due_pins(tu.now_ts()):
            try:
                await app.bot.unpin_chat_message(int(row["chat_id"]), message_id=int(row["message_id"]))
            except TelegramAPIError as e:
                log.info("Не удалось открепить сообщение %s в чате %s: %s", row["message_id"], row["chat_id"], e)
            await repo.delete_pin(row["id"])

    async def scheduled_deletions_job() -> None:
        rows = await repo.db.fetchall("SELECT id, chat_id, message_id FROM scheduled_deletions WHERE delete_at <= ? ORDER BY id LIMIT 100", tu.now_ts())
        for row in rows:
            try:
                await app.bot.delete_message(int(row["chat_id"]), int(row["message_id"]))
            except TelegramAPIError:
                pass  # сообщение уже удалено или больше недоступно
            await repo.db.execute("DELETE FROM scheduled_deletions WHERE id = ?", row["id"])

    async def housekeeping_job() -> None:
        await repo.cleanup_notif_log()
        await repo.purge_old()

    specs = [
        ("sync", cfg.sync_interval_min * 60, sync_job, 0),
        ("directory", 3600, directory_job, 90),
        ("notify", 30, notify_job, 10),
        ("questions", 30, questions_job, 20),
        ("fio_auto_verify", 600, auto_verify_fio_job, 60),
        ("backup", 300, backup_job, 120),
        ("housekeeping", 3600, housekeeping_job, 300),
        ("scheduled_deletions", 30, scheduled_deletions_job, 15),
        ("unpin", 30, unpin_job, 25),
    ]
    return [asyncio.create_task(_forever(n, i, j, d), name=n) for n, i, j, d in specs]
