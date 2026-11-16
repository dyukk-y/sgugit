"""Safe parsing of student-reported group schedule changes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app import timeutil as tu
from app.services.nlu import _lesson_number, find_subject, parse_when


@dataclass
class ChangeDraft:
    action: str
    day: str
    num: int
    subject: str
    start: str
    end: str


_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")


def _resolve_subject(text: str, catalog: list[tuple[str, str]]) -> str | None:
    exact = find_subject(text, catalog)
    if exact:
        return exact
    tokens = re.findall(r"[а-яa-z]{5,}", text.lower().replace("ё", "е"))
    candidates = set()
    for alias, subject in catalog:
        alias_tokens = re.findall(r"[а-яa-z]{5,}", alias.lower().replace("ё", "е"))
        if any(a.startswith(t) or t.startswith(a) for a in alias_tokens for t in tokens):
            candidates.add(subject)
    return next(iter(candidates)) if len(candidates) == 1 else None


def parse_group_change(text: str, today: date, catalog: list[tuple[str, str]],
                       lessons: list[dict]) -> tuple[ChangeDraft | None, str | None]:
    """Return a safe draft or clarification; never guesses between multiple lessons."""
    raw = (text or "").strip()
    low = raw.lower().replace("ё", "е")
    if not raw or "?" in raw or re.search(
        r"\\b(если бы|может быть|а вдруг|кто знает|будет ли|будут ли|есть ли|когда|какая|какой|сколько)\\b",
        low,
    ):
        return None, None

    cancel = bool(re.search(r"\\b(не будет|не состоится|отмен\\w*|не провод\\w*)\\b", low))
    add = bool(re.search(r"\\b(будет|добав\\w*|постав\\w*|перенес\\w*|перенос|замен\\w*|начнется|начинается)\\b", low))
    if not cancel and not add:
        return None, None

    day, _ = parse_when(raw, today)
    day = day or today
    day_iso = tu.iso(day)
    day_lessons = [lesson for lesson in lessons if lesson.get("day") == day_iso]
    subject = _resolve_subject(raw, catalog)
    num = _lesson_number(re.findall(r"[а-яa-z0-9]+", low))
    tm = _TIME_RE.search(low)
    start = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""
    move_verb = bool(re.search(r"\\bперенес\\w*\\b", low))

    if cancel:
        if subject:
            matches = [
                lesson for lesson in day_lessons
                if lesson.get("subject", "").casefold() == subject.casefold()
                and (num is None or int(lesson["num"]) == num)
                and (not start or lesson.get("start_t") == start)
            ]
        elif num is not None:
            matches = [
                lesson for lesson in day_lessons
                if int(lesson["num"]) == num and (not start or lesson.get("start_t") == start)
            ]
        elif start:
            matches = [lesson for lesson in day_lessons if lesson.get("start_t") == start]
        else:
            matches = day_lessons if len(day_lessons) == 1 else []

        if len(matches) != 1:
            if not day_lessons:
                return None, f"На {tu.fmt_date(day)} в расписании группы занятий нет. Уточните дату."
            if not subject and num is None and not start:
                return None, "Какую именно пару отменяют? Укажите предмет, номер пары или время."
            if not matches:
                return None, f"Не нашёл подходящую пару на {tu.fmt_date(day)}. Уточните предмет или номер пары."
            return None, f"На {tu.fmt_date(day)} подходит несколько пар. Уточните предмет или номер пары."
        lesson = matches[0]
        return ChangeDraft(
            "cancel", day_iso, int(lesson["num"]), lesson["subject"],
            lesson["start_t"], lesson["end_t"],
        ), None

    if not subject:
        return None, "Не понял, какой предмет добавляют или переносят. Напишите название предмета."
    subject_lessons = [
        lesson for lesson in day_lessons
        if lesson.get("subject", "").casefold() == subject.casefold()
    ]
    if move_verb and num is None and not start:
        return None, f"На какую пару перенесли «{subject}» {tu.fmt_date(day)}? Напишите номер пары или время начала."

    # A stated start time must match a known group timetable slot. End time is taken from the timetable.
    if start:
        slots = [lesson for lesson in lessons if lesson.get("start_t") == start]
        if not slots:
            return None, f"Не нашёл в расписании начало пары в {start}. Уточните номер пары."
        slot_nums = {int(lesson["num"]) for lesson in slots}
        if len(slot_nums) != 1:
            return None, f"Время {start} соответствует нескольким вариантам. Уточните номер пары."
        num = next(iter(slot_nums))
    if num is None and len(subject_lessons) == 1:
        num = int(subject_lessons[0]["num"])
    if num is None:
        return None, f"На какую пару поставить «{subject}» {tu.fmt_date(day)}? Напишите номер пары или время начала."
    templates = [lesson for lesson in lessons if int(lesson["num"]) == num]
    if start:
        templates = [lesson for lesson in templates if lesson.get("start_t") == start]
    if not templates:
        return None, f"Не нашёл время для пары №{num}. Уточните время начала или номер пары."
    template = templates[0]
    if subject_lessons and any(int(lesson["num"]) == num for lesson in subject_lessons):
        return None, f"«{subject}» уже стоит {tu.fmt_date(day)} {template['start_t']}–{template['end_t']}."
    if len(subject_lessons) > 1:
        return None, f"У «{subject}» {tu.fmt_date(day)} несколько пар. Уточните номер пары; расписание пока не менял."
    action = "move" if subject_lessons else "add"
    return ChangeDraft(action, day_iso, num, subject, template["start_t"], template["end_t"]), None
