"""Синхронизация расписания с источником: кэш, снимки, уведомления об изменениях и сбоях."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.db.repo import ApplyResult, Repo
from app.models import LessonRec
from app.timeutil import now_ts

log = logging.getLogger(__name__)

Fetcher = Callable[[], Awaitable[list[LessonRec]]]


@dataclass
class SyncReport:
    ok: bool
    message: str
    result: ApplyResult | None = None


class SyncService:
    def __init__(self, repo: Repo, fetcher: Fetcher,
                 on_changes: Callable[[ApplyResult], Awaitable[None]] | None = None,
                 on_alert: Callable[[str], Awaitable[None]] | None = None):
        self.repo, self.fetcher, self.on_changes, self.on_alert = repo, fetcher, on_changes, on_alert
        self._lock = asyncio.Lock()
        self._last_report: SyncReport | None = None
        self._last_finished_monotonic = 0.0

    async def run_once(self) -> SyncReport:
        # Синхронизация может стартовать и фоновым заданием, и по запросу пользователя.
        # Не допускаем параллельную загрузку и двойное применение одного снимка.
        waiting_for_existing = self._lock.locked()
        async with self._lock:
            # Если вызов пришёл во время уже идущей синхронизации, используем её результат.
            # Последующие самостоятельные вызовы (например, плановое обновление) работают штатно.
            if waiting_for_existing and self._last_report is not None:
                return self._last_report
            import time
            report = await self._run_once_locked()
            self._last_report = report
            self._last_finished_monotonic = time.monotonic()
            return report

    async def _run_once_locked(self) -> SyncReport:
        try:
            recs = await self.fetcher()
            if not recs:
                raise ValueError("Источник вернул пустое расписание.")
        except Exception as e:  # сеть, разбор, пустой ответ: бот продолжает работать на сохранённых данных
            return await self._fail(f"{type(e).__name__}: {e}")
        try:
            result = await self.repo.apply_lessons(recs, manual=False)
            await self.repo.save_snapshot("site", recs)
        except Exception as e:
            log.exception("Ошибка применения расписания")
            return await self._fail(f"Ошибка записи: {type(e).__name__}: {e}")
        fails = self.repo.int_setting("sync_fail_count") if self.repo.setting("sync_fail_count") else 0
        await self.repo.set_setting("sync_last_ok", str(now_ts()))
        await self.repo.set_setting("sync_last_count", str(result.total))
        await self.repo.set_setting("sync_last_error", "")
        await self.repo.set_setting("sync_fail_count", "0")
        if fails >= 3 and self.on_alert:
            await self.on_alert("✅ Синхронизация расписания восстановилась.")
        if result.skipped and self.on_alert:
            await self.on_alert("⚠️ Расписание для групп " + ", ".join(result.skipped) +
                                " не обновлено: источник вернул подозрительно мало занятий.")
        if result.changes and self.on_changes:
            await self.on_changes(result)
        return SyncReport(True, f"Обновлено занятий: {result.total}", result)

    async def _fail(self, message: str) -> SyncReport:
        log.warning("Синхронизация не удалась: %s", message)
        fails = (self.repo.int_setting("sync_fail_count") if self.repo.setting("sync_fail_count") else 0) + 1
        await self.repo.set_setting("sync_fail_count", str(fails))
        await self.repo.set_setting("sync_last_error", message[:300])
        if fails == 3 and self.on_alert:
            await self.on_alert("⚠️ Расписание не обновляется (3 неудачи подряд): " + message[:300] +
                                "\nБот показывает сохранённое расписание.")
        return SyncReport(False, message)

    async def apply_import(self, recs: list[LessonRec]) -> ApplyResult:
        """Ручной импорт файла: записи помечаются как ручные и не затираются синхронизацией."""
        result = await self.repo.apply_lessons(recs, manual=True, guard=False)
        if result.changes and self.on_changes:
            await self.on_changes(result)
        return result

    async def rollback(self, snapshot_id: int) -> bool:
        recs = await self.repo.load_snapshot(snapshot_id)
        if not recs:
            return False
        await self.repo.apply_lessons(recs, manual=False, guard=False)
        return True
