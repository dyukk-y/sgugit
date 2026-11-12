"""Подготовка HTML расписания для Telegram Rich Messages."""
from __future__ import annotations


def schedule_rich_html(text: str) -> str:
    """Преобразует HTML-экран расписания в блоки rich message, сохраняя inline-разметку."""
    blocks: list[str] = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if index == 0 and line.startswith("<b>") and "</b>" in line:
            end = line.find("</b>")
            blocks.append(f"<h1>{line[3:end]}</h1>{line[end + 4:]}")
        elif line.startswith("📅 <b>") and "</b>" in line:
            start = line.find("<b>") + 3
            end = line.find("</b>", start)
            blocks.append(f"<h2>{line[start:end]}</h2>{line[end + 4:]}")
        elif line.startswith("<i>") and line.endswith("</i>"):
            blocks.append(f"<blockquote>{line}</blockquote>")
        else:
            blocks.append(f"<p>{line}</p>")
    return "\n".join(blocks)
