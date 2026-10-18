"""Общие структуры данных."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LessonRec:
    group: str
    day: str          # YYYY-MM-DD
    num: int
    start: str        # HH:MM
    end: str          # HH:MM
    subject: str
    teacher: str = ""
    room: str = ""
    kind: str = ""
    subgroup: int | None = None

    def key(self) -> tuple:
        return (self.day, self.num, self.start, self.end, self.subject, self.teacher, self.room, self.kind,
                self.subgroup or 0)
