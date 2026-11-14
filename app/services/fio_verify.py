"""Автоматическое подтверждение ФИО только при сильном независимом подтверждении."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Awaitable, Callable

from app.db.repo import Repo
from app.services.fio import FioContext, describe_reasons, fio_key, surname_keys, validate_fio
from app.timeutil import now_ts

log = logging.getLogger(__name__)
Notify = Callable[[int, str], Awaitable[None]]
MIN_MANUAL_ROSTER_MATCHES = 2


def _manual_group_surnames(rows: list[dict]) -> dict[int, dict[str, int]]:
    """Фамилии, подтверждённые администратором минимум у двух разных студентов одной группы.

    Событие fio_ok — ручное подтверждение; fio_auto_verified намеренно не участвует,
    чтобы автоматические решения не обучали сами себя.
    """
    # Для каждого пользователя учитываем только самое позднее событие изменения/подтверждения ФИО.
    latest: dict[int, tuple[tuple[int, int], dict]] = {}
    for row in rows:
        uid = int(row["id"])
        marker = (int(row.get("verification_ts") or 0), int(row.get("audit_id") or 0))
        if uid not in latest or marker > latest[uid][0]:
            latest[uid] = (marker, row)

    evidence: dict[tuple[int, str], set[str]] = defaultdict(set)
    for uid, (_, row) in latest.items():
        if row.get("verification_action", "fio_ok") != "fio_ok":
            continue
        group_id = row.get("group_id")
        fio = " ".join((row.get("fio") or "").split())
        if not group_id or len(fio.split()) < 2:
            continue
        surname = fio.split()[0]
        canonical = min(surname_keys(surname), key=lambda value: (len(value), value))
        evidence[(int(group_id), canonical)].add(fio_key(fio))
    result: dict[int, dict[str, int]] = defaultdict(dict)
    for (group_id, surname), identities in evidence.items():
        if len(identities) >= MIN_MANUAL_ROSTER_MATCHES:
            result[group_id][surname] = len(identities)
    return dict(result)


def _auto_context(base: FioContext, trusted_surnames: set[str]) -> FioContext:
    """Изолированный контекст: только фамилии с независимым ручным подтверждением в этой группе."""
    trusted: set[str] = set()
    for surname in trusted_surnames:
        trusted.update(surname_keys(surname))
    return FioContext(
        known_surnames=frozenset(trusted),
        staff_pairs=base.staff_pairs,
        require_known_surname=True,
        official_only=True,
    )


async def auto_verify_pending(repo: Repo, notify: Notify | None = None, now: int | None = None) -> dict[str, int]:
    """Автоматически подтверждает только ФИО, прошедшие строгую проверку и roster-evidence.

    Фамилия должна быть вручную подтверждена администратором минимум у двух разных ФИО
    в той же учебной группе. Автоматически подтверждённые записи и фамилии преподавателей
    не являются доказательством. Остальные записи остаются pending для ручной проверки.
    """
    now = now or now_ts()
    cutoff = now - max(0, repo.int_setting("fio_auto_delay_min")) * 60
    rows = await repo.db.fetchall(
        "SELECT id, fio, group_id, fio_submitted_at FROM users WHERE fio_status = 'pending' AND fio IS NOT NULL AND banned = 0 "
        "AND fio_submitted_at IS NOT NULL AND fio_submitted_at <= ?", cutoff)
    stats = {"checked": len(rows), "verified": 0, "manual": 0}
    if not rows:
        return stats

    # Только ручные решения администраторов. Автоматические подтверждения не попадают в этот набор.
    manual_rows = await repo.db.fetchall(
        "SELECT u.id, u.group_id, u.fio, a.action AS verification_action, "
        "a.ts AS verification_ts, a.id AS audit_id FROM users u JOIN audit a ON "
        "((a.action = 'fio_ok' AND CAST(a.details AS BIGINT) = u.id) OR "
        "(a.action IN ('fio_auto_verified', 'fio_changed') AND a.actor = u.id)) "
        "WHERE u.fio_status = 'verified' AND u.fio IS NOT NULL AND u.group_id IS NOT NULL")
    roster = _manual_group_surnames(manual_rows)
    stop, bad = await repo.stoplists()
    base_ctx = await repo.fio_context()

    for row in rows:
        group_id = int(row["group_id"]) if row["group_id"] is not None else 0
        trusted = roster.get(group_id, {})
        auto_ctx = _auto_context(base_ctx, set(trusted))
        res = validate_fio(row["fio"], stop, bad, strict=True, ctx=auto_ctx)
        why = ""
        if res.verdict != "ok" or not res.confident:
            why = describe_reasons(res.code) or "не пройдена строгая проверка"
        elif not trusted:
            why = "нет двух независимых ФИО, вручную подтверждённых в этой группе"
        elif await repo.fio_duplicate(row["group_id"], res.fio, row["id"]):
            why = "в группе уже есть такое ФИО"
        elif await repo.fio_changes_since(row["id"], now - 86400) >= 3:
            why = "ФИО меняли 3 раза и чаще за сутки"
        if why:
            stats["manual"] += 1
            if await repo.first_time(f"fior:{row['id']}:{row['fio_submitted_at']}"):
                await repo.audit(row["id"], "fio_needs_review", why)
            continue

        reference_count = trusted.get(min(surname_keys(res.fio.split()[0]), key=lambda value: (len(value), value)), 0)
        await repo.update_user(row["id"], fio_status="verified")
        await repo.audit(row["id"], "fio_auto_verified",
                         f"строгая проверка; фамилия вручную подтверждена в группе у {reference_count} разных ФИО")
        stats["verified"] += 1
        if notify:
            await notify(row["id"], "✅ ФИО автоматически проверено. Теперь доступны функции, для которых требуется подтверждение.")
    return stats
