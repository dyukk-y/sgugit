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


def parse_group_change(text: str, today: date, catalog: list[tuple[str, str]],
                       lessons: list[dict]) -> tuple[ChangeDraft | None, str | None]:
    """Return a safe draft or a short clarification. Never guesses between multiple lessons."""
    raw = (text or "").strip()
    low = raw.lower().replace("ё", "е")
    if not raw or "?" in raw or re.search(r"\b(если бы|может быть|а вдруг|кто знает|будет ли|будут ли|есть ли|когда|какая|какой|сколько)\b", low):
        return None, None

    cancel = bool(re.search(r"\b(не будет|не состоится|отмен\w*|не провод\w*)\b", low))
    add = bool(re.search(r"\b(будет|добав\w*|постав\w*|перенес\w*|перенос|замен\w*|начнется|начинается)\b", low))
    if not cancel and not add:
        return None, None

    subject = find_subject(raw, catalog)
    if not subject:
        return None, "Не понял, о каком предмете речь. Напишите название предмета."
    day, _ = parse_when(raw, today)
    day = day or today
    day_iso = tu.iso(day)
    day_lessons = [l for l in lessons if l.get("day") == day_iso]
    subject_lessons = [l for l in day_lessons if l.get("subject", "").casefold() == subject.casefold()]
    num = _lesson_number(re.findall(r"[а-яa-z0-9]+", low))
    tm = _TIME_RE.search(low)
    start = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""

    if cancel:
        if num is not None:
            matches = [l for l in subject_lessons if int(l["num"]) == num]
        else:
            matches = subject_lessons
        if len(matches) != 1:
            if not matches:
                return None, f"На {tu.fmt_date(day)} не нашёл пару «{subject}». Уточните номер пары."
            return None, f"На {tu.fmt_date(day)} у «{subject}» несколько пар. Уточните номер пары."
        l = matches[0]
        return ChangeDraft("cancel", day_iso, int(l["num"]), subject, l["start_t"], l["end_t"]), None

    # A stated start time must match a known group timetable slot. End time is taken from the timetable.
    if start:
        slots = [l for l in lessons if l.get("start_t") == start]
        if not slots:
            return None, f"Не нашёл в расписании начало пары в {start}. Уточните номер пары."
        slot_nums = {int(l["num"]) for l in slots}
        if len(slot_nums) != 1:
            return None, f"Время {start} соответствует нескольким вариантам. Уточните номер пары."
        num = next(iter(slot_nums))
    if num is None and len(subject_lessons) == 1:
        num = int(subject_lessons[0]["num"])
    if num is None:
        return None, f"На какую пару поставить «{subject}» {tu.fmt_date(day)}? Напишите номер пары или время начала."
    templates = [l for l in lessons if int(l["num"]) == num]
    if start:
        templates = [l for l in templates if l.get("start_t") == start]
    if not templates:
        return None, f"Не нашёл время для пары №{num}. Уточните время начала или номер пары."
    template = templates[0]
    if subject_lessons and any(int(l["num"]) == num for l in subject_lessons):
        # Existing same subject and slot: no schedule change is needed.
        return None, f"«{subject}» уже стоит {tu.fmt_date(day)} {template['start_t']}–{template['end_t']}."
    if len(subject_lessons) > 1:
        return None, f"У «{subject}» {tu.fmt_date(day)} несколько пар. Чтобы не перенести не ту, уточните номер пары; расписание пока не менял."
    action = "move" if subject_lessons else "add"
    return ChangeDraft(action, day_iso, num, subject, template["start_t"], template["end_t"]), None
