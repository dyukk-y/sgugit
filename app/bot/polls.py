"""Проверка параметров группового опроса."""
from __future__ import annotations


def parse_poll_spec(raw: str) -> tuple[str, list[str]] | None:
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) < 3:
        return None
    question, options = parts[0], parts[1:]
    if not question or len(question) > 300 or not 2 <= len(options) <= 10:
        return None
    if any(not option or len(option) > 100 for option in options):
        return None
    return question, options
