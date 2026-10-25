"""Время и даты: часовой пояс, русские названия, чётность недель."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone, tzinfo

DAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
              "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

_TZ: tzinfo = timezone(timedelta(hours=7))


def set_timezone(name: str) -> None:
    global _TZ
    try:
        from zoneinfo import ZoneInfo

        _TZ = ZoneInfo(name)
    except Exception:  # нет tzdata или неверное имя: Новосибирск = UTC+7 без перехода на летнее время
        _TZ = timezone(timedelta(hours=7))


def tz() -> tzinfo:
    return _TZ


def now_local() -> datetime:
    return datetime.now(_TZ)


def today() -> date:
    return now_local().date()


def now_ts() -> int:
    return int(time.time())


def iso(d: date) -> str:
    return d.isoformat()


def parse_iso(s: str) -> date:
    return date.fromisoformat(s)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def fmt_date(d: date, weekday: bool = True) -> str:
    base = f"{d.day} {MONTHS_GEN[d.month - 1]}"
    return f"{DAYS_SHORT[d.weekday()]}, {base}" if weekday else base


def fmt_dm(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}"


def hhmm_to_min(s: str) -> int | None:
    try:
        h, m = s.strip().split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def min_to_hhmm(m: int) -> str:
    m %= 24 * 60
    return f"{m // 60:02d}:{m % 60:02d}"


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


def week_parity(d: date, anchor: date | None) -> str | None:
    """'нечётная'/'чётная' относительно якорной даты (любой день нечётной недели). None, если якорь не задан."""
    if anchor is None:
        return None
    weeks = (monday_of(d) - monday_of(anchor)).days // 7
    return "нечётная" if weeks % 2 == 0 else "чётная"


def local_to_utc(d: date, hhmm: str) -> datetime:
    m = hhmm_to_min(hhmm) or 0
    local = datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=_TZ)
    return local.astimezone(timezone.utc)
