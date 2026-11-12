"""Ядро логики бота: структуры экранов и контекст запроса. Не зависит от aiogram, поэтому тестируется."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app import timeutil as tu
from app.config import Settings
from app.db.repo import Repo

ALL_PERMS = ("users", "requests", "schedule", "homework", "teachers", "broadcast", "stats")
PERM_LABELS = {"users": "Пользователи", "requests": "Заявки старост", "schedule": "Расписание",
               "homework": "Задания", "teachers": "Рейтинг", "broadcast": "Рассылки", "stats": "Статистика"}
PAGE = 6


@dataclass
class Btn:
    text: str
    data: str | None = None
    url: str | None = None


Kb = list[list[Btn]]


@dataclass
class Screen:
    text: str
    kb: Kb | None = None


@dataclass
class Out:
    screen: Screen | None = None
    toast: str | None = None
    alert: bool = False
    state: str | None = None
    state_data: dict | None = None
    clear_state: bool = False
    notify: list[tuple[int, Screen]] = field(default_factory=list)
    notify_media: list[tuple[int, str, str, str | None]] = field(default_factory=list)  # uid, file_id, kind, caption
    notify_timed: list[tuple[int, Screen, int]] = field(default_factory=list)  # chat_id, screen, delete_after_seconds
    file: tuple[str, bytes, str | None] | None = None
    media: tuple[str, str, str | None] | None = None  # file_id, kind(photo/document), caption
    new_message: bool = False   # отправить отдельным сообщением, а не править экран
    broadcast_group: int | None = None  # служебное: массовая отправка


def b(text: str, data: str) -> Btn:
    return Btn(text, data)


def home_btn() -> Btn:
    return Btn("🏠 Меню", "m:home")


def nav(back: str | None = None) -> list[Btn]:
    row = []
    if back:
        row.append(Btn("◀ Назад", back))
    row.append(home_btn())
    return row


def pager(prefix: str, page: int, total: int, size: int = PAGE) -> list[Btn]:
    pages = max(1, -(-total // size))
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(Btn("◀", f"{prefix}:{page - 1}"))
    row.append(Btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        row.append(Btn("▶", f"{prefix}:{page + 1}"))
    return row


class Ctx:
    def __init__(self, repo: Repo, cfg: Settings, user: dict, now: datetime | None = None,
                 bot_username: str = "bot"):
        self.repo, self.cfg, self.user = repo, cfg, user
        self.now = now or tu.now_local()
        self.bot_username = bot_username
        self._group: dict | None = None
        self._group_loaded = False
        self.services: dict = {}

    @property
    def uid(self) -> int:
        return int(self.user["id"])

    @property
    def today(self) -> date:
        return self.now.date()

    @property
    def role(self) -> str:
        if self.uid == self.cfg.superadmin_id:
            return "super"
        return self.user.get("role") or "student"

    @property
    def is_admin(self) -> bool:
        return self.role in ("super", "admin")

    @property
    def is_super(self) -> bool:
        return self.role == "super"

    @property
    def is_head(self) -> bool:
        # Совместимость со старыми записями БД; роль больше не выдаётся через интерфейс.
        return self.role == "head"

    @property
    def perms(self) -> set[str]:
        if self.is_super:
            return set(ALL_PERMS)
        if self.role == "admin":
            return {p for p in (self.user.get("admin_perms") or "").split(",") if p}
        return set()

    def can(self, perm: str) -> bool:
        return perm in self.perms

    @property
    def registered(self) -> bool:
        return self.user.get("group_id") is not None

    @property
    def verified(self) -> bool:
        return self.user.get("fio_status") == "verified"

    async def group(self) -> dict | None:
        if not self._group_loaded:
            self._group = await self.repo.get_group(self.user.get("group_id"))
            self._group_loaded = True
        return self._group

    def parity_anchor(self) -> date | None:
        s = self.repo.setting("parity_anchor")
        try:
            return date.fromisoformat(s) if s else None
        except ValueError:
            return None

    def parity(self, d: date) -> str | None:
        return tu.week_parity(d, self.parity_anchor())


def md(text: str) -> str:
    return text


async def daily_quota(repo: Repo, prefix: str, uid: int, limit: int, today_iso: str) -> bool:
    """True, если лимит на сегодня ещё не исчерпан (и занимает одну попытку)."""
    for i in range(1, limit + 1):
        if await repo.first_time(f"{prefix}:{uid}:{today_iso}:{i}"):
            return True
    return False
