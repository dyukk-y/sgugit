"""Уведомления: вечерняя сводка, напоминания перед парой, изменения расписания, сводки в чатах."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from app import timeutil as tu
from app.bot.core import Btn, Screen
from app.db.repo import ApplyResult, Repo
from app.services import format as fm

log = logging.getLogger(__name__)

SendFn = Callable[[int, Screen], Awaitable[None]]
CATCHUP_MIN = 180        # не отправлять вечернюю сводку, если с запланированного времени прошло больше 3 часов
BREAK_FOR_REMINDER = 40  # напоминать перед парой, если до неё не было занятий минимум 40 минут


def _parity(repo: Repo, d) -> str | None:
    s = repo.setting("parity_anchor")
    try:
        return tu.week_parity(d, tu.parse_iso(s)) if s else None
    except ValueError:
        return None


class Notifier:
    def __init__(self, repo: Repo, send: SendFn):
        self.repo, self.send = repo, send

    async def tick(self, now: datetime | None = None) -> None:
        now = now or tu.now_local()
        await self._evening(now)
        await self._before_lesson(now)
        await self._chat_evening(now)

    # ---------- вечерняя сводка ----------
    async def _evening(self, now: datetime) -> None:
        minutes = now.hour * 60 + now.minute
        today_iso = tu.iso(now.date())
        tomorrow = now.date() + timedelta(days=1)
        users = await self.repo.db.fetchall(
            "SELECT id, group_id, subgroup, n_evening_time FROM users WHERE n_enabled = 1 AND n_evening = 1 AND group_id IS NOT NULL "
            "AND banned = 0 AND bot_blocked = 0")
        cache: dict[tuple, list[dict]] = {}
        for u in users:
            sched = tu.hhmm_to_min(u["n_evening_time"])
            if sched is None or not (sched <= minutes < sched + CATCHUP_MIN):
                continue
            if not await self.repo.first_time(f"ev:{u['id']}:{today_iso}"):
                continue
            key = (u["group_id"], u["subgroup"])
            if key not in cache:
                cache[key] = await self.repo.lessons_day(u["group_id"], tu.iso(tomorrow), u["subgroup"])
            lessons = cache[key]
            if not lessons:
                continue
            hw = await self.repo.hw_counts_for_day(u["group_id"], tu.iso(tomorrow))
            text = "🌙 <b>Расписание на завтра</b>\n\n" + fm.day_text(tomorrow, lessons, _parity(self.repo, tomorrow), hw)
            kb = [[Btn("📅 Открыть расписание", "s:d:tom")]]
            await self.send(u["id"], Screen(text, kb))

    # ---------- перед парой ----------
    async def _before_lesson(self, now: datetime) -> None:
        minutes = now.hour * 60 + now.minute
        today_iso = tu.iso(now.date())
        users = await self.repo.db.fetchall(
            "SELECT id, group_id, subgroup, n_before FROM users WHERE n_enabled = 1 AND n_before > 0 AND group_id IS NOT NULL "
            "AND banned = 0 AND bot_blocked = 0")
        cache: dict[int, list[dict]] = {}
        for u in users:
            gid = u["group_id"]
            if gid not in cache:
                cache[gid] = await self.repo.lessons_day(gid, today_iso)
            lessons = [l for l in cache[gid] if l["subgroup"] is None or u["subgroup"] is None or l["subgroup"] == u["subgroup"]]
            for i, l in enumerate(lessons):
                s = tu.hhmm_to_min(l["start_t"])
                if s is None:
                    continue
                until = s - minutes
                if not (0 < until <= u["n_before"]):
                    continue
                prev_end = tu.hhmm_to_min(lessons[i - 1]["end_t"]) if i > 0 else None
                if prev_end is not None and s - prev_end < BREAK_FOR_REMINDER:
                    continue
                if not await self.repo.first_time(f"bl:{u['id']}:{l['id']}"):
                    continue
                text = f"⏰ <b>Через {tu.fmt_duration(until)}</b>\n{fm.short_lesson(l)}"
                await self.send(u["id"], Screen(text))

    # ---------- сводки в групповых чатах ----------
    async def _chat_evening(self, now: datetime) -> None:
        minutes = now.hour * 60 + now.minute
        today_iso = tu.iso(now.date())
        tomorrow = now.date() + timedelta(days=1)
        for c in await self.repo.evening_chats():
            sched = tu.hhmm_to_min(c["evening_time"])
            if sched is None or not (sched <= minutes < sched + CATCHUP_MIN):
                continue
            if not await self.repo.first_time(f"cev:{c['chat_id']}:{today_iso}"):
                continue
            lessons = await self.repo.lessons_day(c["group_id"], tu.iso(tomorrow))
            if not lessons:
                continue
            text = "🌙 <b>Расписание на завтра</b>\n\n" + fm.day_text(tomorrow, lessons, _parity(self.repo, tomorrow))
            await self.send(c["chat_id"], Screen(text))

    # ---------- изменения расписания ----------
    async def notify_changes(self, result: ApplyResult) -> int:
        sent = 0
        for gid, changes in result.changes.items():
            group = await self.repo.get_group(gid)
            if not group:
                continue
            text = fm.changes_text(group["name"], changes)
            kb = [[Btn("📅 Расписание", "s:d:today")]]
            users = await self.repo.db.fetchall(
                "SELECT id FROM users WHERE group_id = ? AND n_enabled = 1 AND n_changes = 1 AND banned = 0 AND bot_blocked = 0", gid)
            for u in users:
                await self.send(u["id"], Screen(text, kb))
                sent += 1
            for c in await self.repo.chats_for_group(gid):
                await self.send(c["chat_id"], Screen(text))
                sent += 1
        return sent
