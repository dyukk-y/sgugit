"""Справочник преподавателей: сайт вуза (список -> карточка -> подразделение -> кабинет) или файл CSV/XLSX.

ВНИМАНИЕ: страницы https://sgugit.ru/teachers/ при разработке открыть не удалось (сервер зациклил редиректы
для автоматических запросов), поэтому разбор эвристический и проверен только на образцах. Если сайт устроен
иначе, обход честно вернёт ошибку или пустой результат, а справочник можно загрузить файлом
(``фио;подразделение;кабинет``). Под реальные страницы настраиваются только функции parse_*.
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

from app.providers import importer
from app.services.fio import COMMON_NAMES, is_patronymic

log = logging.getLogger(__name__)

FIO_RE = re.compile(r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?(?:\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?){1,2}")
UNIT_LABEL = re.compile(r"структурн\w*\s+подразделен\w*|подразделен\w*|кафедр\w*", re.I)
ROOM_LABEL = re.compile(r"кабинет|аудитор|местонахожден|расположен|адрес|помещен", re.I)
ROOM_RE = re.compile(r"(?:корпус|корп\.?)\s*([0-9]+|[А-Яа-я])?[\s,;]*(?:каб(?:инет)?\.?|ауд(?:итория)?\.?)\s*№?\s*"
                     r"([0-9]{1,4}[А-Яа-яA-Za-z]?)|(?:каб(?:инет)?\.?|ауд(?:итория)?\.?)\s*№?\s*([0-9]{1,4}[А-Яа-яA-Za-z]?)",
                     re.I)
UNIT_HREF = re.compile(r"/(struct|department|kafedr|faculty|unit|subdivision|podrazdel)", re.I)
MAX_PAGES, MAX_TEACHERS, MAX_UNITS = 80, 1500, 300


class DirectoryError(Exception):
    pass


def _clean(s: str, limit: int = 160) -> str:
    return " ".join((s or "").split())[:limit].strip(" :;,-–—")


_INITIALS_FIO = re.compile(r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.")


def looks_like_fio(text: str) -> bool:
    """Строже, чем FIO_RE: отсекает пункты меню вроде «Об Университете» (три слова с отчеством, ФИО с инициалами
    или фамилия + известное имя)."""
    t = " ".join(text.split())
    if _INITIALS_FIO.fullmatch(t):
        return True
    if not FIO_RE.fullmatch(t):
        return False
    words = t.split()
    if len(words) == 3:
        return is_patronymic(words[2])
    return words[1].lower().replace("ё", "е") in COMMON_NAMES


def parse_teacher_links(html: str, page_url: str) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        text = _clean(a.get_text(" ", strip=True), 80)
        if looks_like_fio(text) and not a["href"].startswith(("mailto:", "tel:", "#")):
            out.setdefault(text, urljoin(page_url, a["href"]))
    return list(out.items())


def parse_pagination(html: str, page_url: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    host = urlparse(page_url).netloc
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = _clean(a.get_text(" ", strip=True), 20).lower()
        if not (text.isdigit() or text in ("»", ">", "следующая", "вперёд", "вперед", "далее", "next")
                or re.search(r"page|pagen|[?&]p=", href, re.I)):
            continue
        full = urljoin(page_url, href)
        if urlparse(full).netloc == host and full != page_url and full not in urls:
            urls.append(full)
    return urls


def parse_teacher_page(html: str, page_url: str) -> tuple[str, str]:
    """Extract the actual structural unit from a teacher card, preferring department links.

    SGUGiT cards include faculty/navigation links around the metadata. A broad ancestor
    search can therefore accidentally return just «Факультет». Inspect the value paired
    with «Наименование структурного подразделения» first and prefer /kafedry/ links.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    # Strongest signal: the official field label and its value in a table/list/dl layout.
    labels = soup.find_all(string=re.compile(r"наименование\s+структурного\s+подразделения|структурное\s+подразделение", re.I))
    for node in labels:
        holder = node.parent
        scopes = [holder, holder.find_next_sibling(), holder.parent,
                  holder.parent.find_next_sibling() if holder.parent else None]
        for scope in scopes:
            if scope is None or not hasattr(scope, "find_all"):
                continue
            links = ([scope] if getattr(scope, "name", None) == "a" and scope.get("href") else []) + scope.find_all("a", href=True)
            # Never take a generic faculty link when an actual department link exists.
            dep = next((a for a in links if "/kafedry/" in a.get("href", "").lower()), None)
            if dep:
                return _clean(dep.get_text(" ", strip=True)), urljoin(page_url, dep["href"])
            for a in links:
                value = _clean(a.get_text(" ", strip=True))
                if value and re.search(r"кафедр", value, re.I):
                    return value, urljoin(page_url, a["href"])
            # Structured label/value pairs often put the value in the next cell or dd.
            value = _clean(scope.get_text(" ", strip=True), 300)
            value = re.sub(r"^.*?(?:наименование\s+структурного\s+подразделения|структурное\s+подразделение)\s*[:—–-]?\s*", "", value, flags=re.I)
            if value and re.search(r"кафедр", value, re.I):
                return value, ""
    # Plain-text metadata fallback (accept institutes/faculties, but never a generic label).
    full = _clean(soup.get_text(" ", strip=True), 10000)
    m = re.search(r"(?:наименование\s+структурного\s+подразделения|структурное\s+подразделение)\s*[:—–-]?\s*(.{3,180}?)(?=\s+(?:уровень образования|адрес|ученая степень|учёная степень|перечень преподаваемых|сведения о)|$)", full, re.I)
    if m:
        value = _clean(m.group(1))
        if value and value.casefold() not in {"факультет", "подразделение", "структурное подразделение"}:
            return value, ""
    return "", ""


def parse_unit_page(html: str) -> str:
    """Кабинет (при возможности с корпусом) со страницы структурного подразделения."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for node in soup.find_all(string=ROOM_LABEL):
        holder = node.parent
        candidates = [_clean(holder.get_text(" ", strip=True), 300)]
        sib = holder.find_next_sibling()
        if sib is not None:
            candidates.append(_clean(sib.get_text(" ", strip=True), 300))
        for c in candidates:
            m = ROOM_RE.search(c)
            if m:
                return _format_room(m)
        # метка без номера: берём значение после двоеточия как есть, если оно короткое
        full = candidates[0]
        mm = re.search(r"(?:кабинет|аудитор\w*|местонахожден\w*|расположен\w*)\s*[:\-–—]\s*(.{2,80})", full, re.I)
        if mm:
            return _clean(mm.group(1), 80)
    text = soup.get_text(" ", strip=True)
    m = ROOM_RE.search(text)
    return _format_room(m) if m else ""


def _format_room(m: re.Match) -> str:
    corp, room1, room2 = m.group(1), m.group(2), m.group(3)
    room = room1 or room2
    if corp and room1:
        return f"корпус {corp}, каб. {room}"
    return f"каб. {room}"


# ---------------- обход сайта ----------------
async def crawl_directory(list_url: str, fetch=None) -> tuple[list[dict], list[dict]]:
    """Возвращает (staff, units). fetch(url) -> html; по умолчанию httpx с вежливыми паузами."""
    close = None
    if fetch is None:
        import httpx

        client = httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=25,
                                   headers={"User-Agent": "Mozilla/5.0 (compatible; SGUGiTScheduleBot/1.0)",
                                            "Accept-Language": "ru"})
        sem = asyncio.Semaphore(3)

        async def fetch(url: str) -> str:  # type: ignore[misc]
            async with sem:
                await asyncio.sleep(0.2)
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text

        close = client.aclose
    try:
        teachers: dict[str, str] = {}
        queue, seen = [list_url], set()
        while queue and len(seen) < MAX_PAGES and len(teachers) < MAX_TEACHERS:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                html = await fetch(url)
            except Exception as e:  # noqa: BLE001
                if url == list_url:
                    raise DirectoryError(f"Страница списка недоступна: {type(e).__name__}: {e}") from e
                log.warning("Страница %s пропущена: %s", url, e)
                continue
            for name, link in parse_teacher_links(html, url):
                teachers.setdefault(name, link)
            queue += [u for u in parse_pagination(html, url) if u not in seen and u not in queue]
        if not teachers:
            raise DirectoryError("На странице не найден список преподавателей (структура сайта незнакома боту).")

        async def one(name: str, link: str) -> tuple[str, str, str]:
            try:
                unit, unit_url = parse_teacher_page(await fetch(link), link)
            except Exception as e:  # noqa: BLE001
                log.warning("Карточка %s не прочитана: %s", name, e)
                return name, "", ""
            return name, unit, unit_url

        results = await asyncio.gather(*(one(n, u) for n, u in teachers.items()))
        units: dict[str, dict] = {}
        for _, unit, unit_url in results:
            if unit and unit not in units and len(units) < MAX_UNITS:
                units[unit] = {"name": unit, "room": "", "url": unit_url}

        async def room_of(u: dict) -> None:
            if not u["url"]:
                return
            try:
                u["room"] = parse_unit_page(await fetch(u["url"]))
            except Exception as e:  # noqa: BLE001
                log.warning("Страница подразделения %s не прочитана: %s", u["name"], e)

        await asyncio.gather(*(room_of(u) for u in units.values()))
        staff = [{"name": n, "unit": unit, "url": link} for (n, unit, _), link in
                 zip(results, (teachers[n] for n, _, _ in results))]
        return staff, list(units.values())
    finally:
        if close:
            await close()


# ---------------- файл CSV/XLSX ----------------
_HEADERS = {
    "name": ("фио", "преподаватель", "фамилия имя отчество", "сотрудник"),
    "unit": ("подразделение", "структурное подразделение", "кафедра"),
    "room": ("кабинет", "аудитория", "ауд", "каб"),
}


def parse_directory_rows(rows: list[list[str]]) -> tuple[list[dict], list[dict], list[str]]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], [], ["Файл пустой."]
    header = [c.strip().lower() for c in rows[0]]
    mapping = {f: header.index(n) for f, names in _HEADERS.items() for n in names if n in header}
    start = 1
    if "name" not in mapping:
        mapping, start = {"name": 0, "unit": 1, "room": 2}, 0
    staff: list[dict] = []
    units: dict[str, dict] = {}
    errors: list[str] = []
    for n, row in enumerate(rows[start:], start=start + 1):
        def get(f: str) -> str:
            i = mapping.get(f)
            return row[i].strip() if i is not None and i < len(row) else ""

        name, unit, room = get("name"), get("unit"), get("room")
        if not FIO_RE.fullmatch(" ".join(name.split())):
            errors.append(f"Строка {n}: «{name[:30]}» не похоже на ФИО.")
            if len(errors) >= 10:
                break
            continue
        staff.append({"name": name, "unit": unit, "url": ""})
        if unit:
            u = units.setdefault(unit, {"name": unit, "room": "", "url": ""})
            if room and not u["room"]:
                u["room"] = room
    return staff, list(units.values()), errors


def parse_directory_file(filename: str, data: bytes) -> tuple[list[dict], list[dict], list[str]]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        rows = importer.read_xlsx(data)
    elif name.endswith((".csv", ".txt")):
        rows = importer.read_csv(data)
    else:
        raise ValueError("Поддерживаются файлы .xlsx и .csv")
    return parse_directory_rows(rows)
