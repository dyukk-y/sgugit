"""Автоматическое подтверждение ФИО: только уверенные случаи, всё остальное остаётся админам."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from app.db.repo import Repo
from app.services.fio import FioContext, describe_reasons, surname_keys, validate_fio
from app.timeutil import now_ts

log = logging.getLogger(__name__)
Notify = Callable[[int, str], Awaitable[None]]


def _auto_context(base: FioContext, official_surnames: set[str]) -> FioContext:
    """Изолированный контекст автопроверки: только официальные фамилии из staff."""
    trusted: set[str] = set()
    for surname in official_surnames:
        trusted.update(surname_keys(surname))
    return FioContext(
        known_surnames=frozenset(trusted),
        staff_pairs=base.staff_pairs,
        require_known_surname=True,
        official_only=True,
    )


async def auto_verify_pending(repo: Repo, notify: Notify | None = None, now: int | None = None) -> dict[str, int]:
    """Подтверждает ФИО, которые прошли ВСЕ проверки и «отлежали» паузу.

    Условия: вердикт ``ok`` в строгом режиме и ``confident`` (известное имя, отчество от известного мужского имени,
    фамилия из официального справочника преподавателей), нет двойника в группе, нет бана и частых
    правок ФИО за сутки. Остальные записи не трогаем, их разбирает администратор.
    """
    now = now or now_ts()
    cutoff = now - max(0, repo.int_setting("fio_auto_delay_min")) * 60
    rows = await repo.db.fetchall(
        "SELECT id, fio, group_id, fio_submitted_at FROM users WHERE fio_status = 'pending' AND fio IS NOT NULL AND banned = 0 "
        "AND fio_submitted_at IS NOT NULL AND fio_submitted_at <= ?", cutoff)
    stats = {"checked": len(rows), "verified": 0, "manual": 0}
    if not rows:
        return stats
    stop, bad = await repo.stoplists()
    base_ctx = await repo.fio_context()
    # Фамилии студентов не становятся доказательством для новых автоматических решений.
    auto_ctx = _auto_context(base_ctx, await repo.known_surnames())
    for row in rows:
        res = validate_fio(row["fio"], stop, bad, strict=True, ctx=auto_ctx)
        why = ""
        if res.verdict != "ok" or not res.confident:
            why = describe_reasons(res.code) or "не пройдена строгая проверка"
        elif await repo.fio_duplicate(row["group_id"], res.fio, row["id"]):
            why = "в группе уже есть такое ФИО"
        elif await repo.fio_changes_since(row["id"], now - 86400) >= 3:
            why = "ФИО меняли 3 раза и чаще за сутки"
        if why:
            stats["manual"] += 1
            if await repo.first_time(f"fior:{row['id']}:{row['fio_submitted_at']}"):
                await repo.audit(row["id"], "fio_needs_review", why)
            continue
        await repo.update_user(row["id"], fio_status="verified")
        await repo.audit(row["id"], "fio_auto_verified", "все проверки пройдены")
        stats["verified"] += 1
        if notify:
            await notify(row["id"], "✅ ФИО автоматически проверено. Теперь доступны функции, для которых требуется подтверждение.")
    return stats
