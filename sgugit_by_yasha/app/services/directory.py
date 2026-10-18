"""Синхронизация справочника преподавателей (подразделение и кабинет)."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from app.db.repo import Repo
from app.timeutil import now_ts

log = logging.getLogger(__name__)
Crawler = Callable[[], Awaitable[tuple[list[dict], list[dict]]]]


class DirectorySync:
    def __init__(self, repo: Repo, crawl: Crawler, on_alert: Callable[[str], Awaitable[None]] | None = None):
        self.repo, self.crawl, self.on_alert = repo, crawl, on_alert

    async def run_once(self) -> tuple[bool, str]:
        try:
            staff, units = await self.crawl()
        except Exception as e:  # noqa: BLE001 - справочник не критичен, бот работает на сохранённых данных
            msg = f"{type(e).__name__}: {e}"
            log.warning("Справочник не обновлён: %s", msg)
            await self.repo.set_setting("dir_error", msg[:300])
            return False, msg
        old = await self.repo.count("staff")
        if old >= 20 and len(staff) < 0.5 * old:
            msg = f"Источник вернул подозрительно мало преподавателей ({len(staff)} вместо {old}), справочник не изменён."
            await self.repo.set_setting("dir_error", msg)
            return False, msg
        await self.repo.replace_directory(staff, units)
        return True, await self._finish("site", len(staff), len(units), sum(1 for u in units if u.get("room")))

    async def apply_file(self, staff: list[dict], units: list[dict]) -> str:
        await self.repo.replace_directory(staff, units)
        return await self._finish("file", len(staff), len(units), sum(1 for u in units if u.get("room")))

    async def _finish(self, source: str, n_staff: int, n_units: int, n_rooms: int) -> str:
        await self.repo.set_setting("dir_source", source)
        await self.repo.set_setting("dir_last_ok", str(now_ts()))
        await self.repo.set_setting("dir_error", "")
        msg = f"Преподавателей: {n_staff}, подразделений: {n_units}, с указанным кабинетом: {n_rooms}."
        if n_staff and not n_units:
            msg += " Подразделения не определены: карточки на сайте устроены иначе, загрузите справочник файлом."
        elif n_units and not n_rooms:
            msg += " Кабинеты не определены: загрузите справочник файлом или сообщите, как устроена страница подразделения."
        return msg
