"""Выгрузка данных в XLSX для суперадмина."""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook

from app.db.repo import Repo
from app.timeutil import tz


def safe_cell(v):
    """Защита от формул в Excel: строки, начинающиеся с = + - @, экранируются."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _ts(v) -> str:
    return datetime.fromtimestamp(int(v), tz()).strftime("%Y-%m-%d %H:%M") if v else ""


async def export_xlsx(repo: Repo, kind: str) -> tuple[str, bytes]:
    wb = Workbook()
    ws = wb.active
    if kind == "users":
        ws.title = "Пользователи"
        ws.append(["Telegram ID", "Username", "Группа", "ФИО", "Статус ФИО", "Роль", "Бан", "Оценок", "Заданий",
                   "Регистрация", "Последняя активность"])
        rows = await repo.db.fetchall(
            "SELECT u.id AS id, u.username AS username, g.name AS gname, u.fio AS fio, u.fio_status AS st, u.role AS role, "
            "u.banned AS banned, u.created_at AS created_at, u.last_seen AS last_seen, "
            "(SELECT COUNT(*) FROM ratings r WHERE r.user_id = u.id) AS n_r, "
            "(SELECT COUNT(*) FROM homework h WHERE h.author_id = u.id) AS n_h "
            "FROM users u LEFT JOIN groups g ON g.id = u.group_id ORDER BY u.created_at")
        for r in rows:
            ws.append([r["id"], safe_cell(r["username"] or ""), r["gname"] or "", safe_cell(r["fio"] or ""), r["st"],
                       r["role"], "да" if r["banned"] else "", r["n_r"], r["n_h"], _ts(r["created_at"]), _ts(r["last_seen"])])
    elif kind == "ratings":
        ws.title = "Оценки"
        ws.append(["Telegram ID", "ФИО студента", "Группа", "Преподаватель", "Оценка", "Обновлено"])
        rows = await repo.db.fetchall(
            "SELECT u.id AS uid, u.fio AS fio, g.name AS gname, t.name AS tname, r.stars AS stars, r.updated_at AS ts "
            "FROM ratings r JOIN teachers t ON t.id = r.teacher_id LEFT JOIN users u ON u.id = r.user_id "
            "LEFT JOIN groups g ON g.id = u.group_id ORDER BY r.updated_at DESC")
        for r in rows:
            ws.append([r["uid"], safe_cell(r["fio"] or ""), r["gname"] or "", safe_cell(r["tname"]), r["stars"], _ts(r["ts"])])
    elif kind == "homework":
        ws.title = "Задания"
        ws.append(["ID", "Группа", "Предмет", "Текст", "Срок", "Автор (ФИО)", "Статус", "Создано"])
        rows = await repo.db.fetchall(
            "SELECT h.id AS id, g.name AS gname, h.subject AS subject, h.text AS text, h.due_day AS due, u.fio AS fio, "
            "h.status AS status, h.created_at AS ts FROM homework h LEFT JOIN groups g ON g.id = h.group_id "
            "LEFT JOIN users u ON u.id = h.author_id ORDER BY h.id DESC")
        for r in rows:
            ws.append([r["id"], r["gname"] or "", safe_cell(r["subject"]), safe_cell(r["text"]), r["due"] or "",
                       safe_cell(r["fio"] or ""), r["status"], _ts(r["ts"])])
    else:
        raise ValueError("Неизвестный тип выгрузки")
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(50, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return f"{kind}-{datetime.now(tz()).strftime('%Y%m%d')}.xlsx", buf.getvalue()
