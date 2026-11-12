"""Преобразование расписания в нативные структурированные Telegram Rich Messages.

Используем поддерживаемые Telegram блоки, а не имитацию карточек пробелами:
дни недели сворачиваются, пары раскрываются отдельно, время и предмет остаются
в заголовке пары, подробности — внутри.
"""
from __future__ import annotations

import re


_LESSON_HEAD = re.compile(r"^(?:<s>)?<b>\d{2}</b>")
_STATUS_SUBJECT = re.compile(r"(?:Сейчас идёт|Следующая):?\s*<b>(.*?)</b>")


def _lesson_card(lines: list[str]) -> str:
    """Собирает три строки пары и её служебные пометки в раскрываемую карточку."""
    head = lines[0]
    subject = lines[1] if len(lines) > 1 else ""
    meta = lines[2] if len(lines) > 2 else ""
    summary = f"{head} · {subject}"
    body = [f"<p>{meta}</p>"] if meta else []
    body.extend(f"<p>{line}</p>" for line in lines[3:])
    return f"<details open><summary>{summary}</summary>{''.join(body)}</details>"


def schedule_rich_html(text: str) -> str:
    """Преобразует экраны расписания в rich-блоки с днями и карточками занятий."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    status_subjects = {
        match.group(1)
        for line in lines
        if line.startswith(("▶️", "⏭"))
        for match in [_STATUS_SUBJECT.search(line)]
        if match
    }

    blocks: list[str] = []
    loose_lines: list[str] = []
    day_open = False
    day_count = 0
    current_day_lines: list[str] = []

    def flush_loose() -> None:
        nonlocal loose_lines
        if loose_lines:
            blocks.append(_render_day_lines(loose_lines))
            loose_lines = []

    def flush_day() -> None:
        nonlocal day_open, current_day_lines, day_count
        if not day_open:
            return
        rendered = _render_day_lines(current_day_lines)
        # День с текущей/следующей парой раскрываем автоматически, остальные
        # остаются компактными и открываются по нажатию.
        is_relevant = any(subject in "\n".join(current_day_lines) for subject in status_subjects)
        opened = " open" if is_relevant or day_count == 0 else ""
        blocks.append(f"<details{opened}><summary>{current_day_title}</summary>{rendered}</details>")
        day_open = False
        current_day_lines = []
        day_count += 1

    current_day_title = ""

    for index, line in enumerate(lines):
        if index == 0 and line.startswith("<b>") and "</b>" in line:
            end = line.find("</b>")
            blocks.append(f"<h1>{line[3:end]}</h1>{line[end + 4:]}")
            continue

        if line.startswith("📅 <b>") and "</b>" in line:
            flush_loose()
            flush_day()
            start = line.find("<b>") + 3
            end = line.find("</b>", start)
            current_day_title = line[start:end] + line[end + 4:]
            day_open = True
            continue

        if day_open:
            current_day_lines.append(line)
        else:
            loose_lines.append(line)

    flush_loose()
    flush_day()
    if not blocks:
        return ""
    return "\n".join(blocks)


def _render_day_lines(lines: list[str]) -> str:
    rendered: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _LESSON_HEAD.match(line):
            card = [line]
            index += 1
            # Формат пары: время/номер, предмет, тип/преподаватель/аудитория,
            # затем необязательные пометки об отмене, ручной правке и заданиях.
            if index < len(lines) and ("📘" in lines[index] or "<s>📘" in lines[index]):
                card.append(lines[index])
                index += 1
            if index < len(lines) and lines[index].startswith(("🎓", "🧪", "🛠", "📚")):
                card.append(lines[index])
                index += 1
            while index < len(lines) and lines[index].startswith(("❌", "➕", "✏️", "📎")):
                card.append(lines[index])
                index += 1
            rendered.append(_lesson_card(card))
            continue

        if line.startswith(("▶️", "⏭")):
            rendered.append(f"<blockquote>{line}</blockquote>")
        elif line.startswith("🕐"):
            rendered.append(f"<p><i>{line}</i></p>")
        elif line.startswith("<i>") and line.endswith("</i>"):
            rendered.append(f"<footer>{line}</footer>")
        else:
            rendered.append(f"<p>{line}</p>")
        index += 1
    return "".join(rendered)
