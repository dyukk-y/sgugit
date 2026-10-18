"""Фоновые задачи: синхронизация, уведомления, ожидающие вопросы, бэкапы, уборка."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from app import timeutil as tu
from app.bot import tg
from app.services import backup as bk
from app.services.directory import DirectorySync
from app.services.notifier import Notifier
from app.services.fio import validate_fio
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
        # Автоматически подтверждаем только правдоподобные ФИО без дублей; сомнительные остаются админам.
        cutoff = tu.now_ts() - 90 * 60
        rows = await repo.db.fetchall(
            "SELECT id, fio, group_id FROM users WHERE fio_status = 'pending' AND fio IS NOT NULL AND fio_submitted_at IS NOT NULL AND fio_submitted_at <= ?",
            cutoff)
        stop, bad = await repo.stoplists()
        for row in rows:
            result = validate_fio(row["fio"], stop, bad, strict=False)
            if result.verdict != "ok":
                continue
            duplicate = await repo.db.fetchone(
                "SELECT id FROM users WHERE group_id = ? AND fio = ? AND id <> ? AND fio_status = 'verified'",
                row["group_id"], result.fio, row["id"]) if row["group_id"] else None
            if duplicate:
                continue
            await repo.update_user(row["id"], fio_status="verified")
            await repo.audit(row["id"], "fio_auto_verified", "automatic after 90 minutes")
            await app.sender.enqueue(row["id"], Screen(
                "✅ ФИО автоматически проверено. Теперь доступны функции, для которых требуется подтверждение."))

    async def send_backup(reason: str) -> None:
        name, blob = await bk.make_backup(repo)
        try:
            bk.save_local(cfg.backup_dir, name, blob)
        except OSError:
            log.warning("Локальная копия бэкапа не сохранена")
        try:
            await app.bot.send_document(cfg.superadmin_id, BufferedInputFile(blob, filename=name),
                                        caption=f"💾 Резервная копия ({reason})")
        except TelegramAPIError as e:
            log.warning("Бэкап не отправлен: %s", e)

    async def backup_job() -> None:
        now = tu.now_local()
        if now.hour >= 3 and await repo.first_time(f"bk:{tu.iso(now.date())}"):
            await send_backup("ежедневная")
            app.repo.db.dirty = False
            state["hourly"] = time.monotonic()
            return
        if repo.db.kind == "sqlite" and repo.db.dirty and time.monotonic() - state["hourly"] > 3300:
            repo.db.dirty = False  # сбрасываем до копирования: изменения во время копирования пометят базу снова
            state["hourly"] = time.monotonic()
            await send_backup("после изменений")

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
    ]
    return [asyncio.create_task(_forever(n, i, j, d), name=n) for n, i, j, d in specs]
