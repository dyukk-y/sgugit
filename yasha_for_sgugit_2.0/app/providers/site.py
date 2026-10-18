"""Источник расписания: страница сайта вуза.

Парсер поддерживает текущую div-разметку sgugit.ru (/raspisanie/group/<id>/), а также
табличный формат как резервный вариант. Для незнакомой структуры возбуждается ParseError;
бот может продолжить работу на сохранённом расписании, а администратор — импортировать файл.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from app.models import LessonRec
from app.providers.importer import parse_day

log = logging.getLogger(__name__)

GROUP_RE = re.compile(r"(?<![А-Яа-яA-Za-z0-9])([А-ЯA-Z][А-Яа-яA-Za-z]{0,5}[-\s]?\d{2,3}(?:[.]\d+)?[А-Яа-я]?)(?![0-9])")
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})")
DM_RE = re.compile(r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
                   re.I)
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]
HEADER_KEYS = {
    "day": ("дата", "день", "число"), "time": ("время", "временной интервал"),
    "num": ("№", "пара", "номер"), "subject": ("дисциплин", "предмет", "занятие", "наименование"),
    "teacher": ("преподават", "педагог"), "room": ("аудитор", "ауд.", "кабинет", "место"),
    "kind": ("вид", "тип", "форма занятия"), "group": ("групп", "поток"),
}


def _expanded_rows(table) -> list[list[str]]:
    """Expand rowspan/colspan into a rectangular grid; many schedule sites use merged cells."""
    grid: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}
    for tr in table.find_all("tr"):
        row: list[str] = []
        col = 0
        cells = tr.find_all(["th", "td"], recursive=False)
        for cell in cells:
            while col in pending and pending[col][0] > 0:
                remaining, value = pending[col]
                row.append(value)
                pending[col] = (remaining - 1, value)
                col += 1
            value = _text(cell)
            try: colspan = max(1, min(20, int(cell.get("colspan", 1))))
            except (TypeError, ValueError): colspan = 1
            try: rowspan = max(1, min(100, int(cell.get("rowspan", 1))))
            except (TypeError, ValueError): rowspan = 1
            for offset in range(colspan):
                row.append(value)
                if rowspan > 1:
                    pending[col + offset] = (rowspan - 1, value)
            col += colspan
        while col in pending and pending[col][0] > 0:
            remaining, value = pending[col]
            row.append(value)
            pending[col] = (remaining - 1, value)
            col += 1
        grid.append(row)
    return grid


class ParseError(Exception):
    pass


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def _day_from_text(s: str, today: date) -> str | None:
    d = parse_day(s.strip())
    if d:
        return d
    m = DM_RE.search(s)
    if m:
        mo = MONTHS.index(m.group(2).lower()) + 1
        try:
            cand = date(today.year, mo, int(m.group(1)))
        except ValueError:
            return None
        if (today - cand).days > 200:
            cand = date(today.year + 1, mo, int(m.group(1)))
        return cand.isoformat()
    m2 = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b", s)
    return parse_day(m2.group(1)) if m2 else None


def _group_near(table) -> str | None:
    cap = table.find("caption")
    cands = [cap] if cap else []
    prev = table
    for _ in range(6):
        prev = prev.find_previous(["h1", "h2", "h3", "h4", "h5", "strong", "b", "p", "div"])
        if prev is None:
            break
        cands.append(prev)
    for c in cands:
        m = GROUP_RE.search(_text(c))
        if m:
            return m.group(1).replace(" ", "-").upper() if "-" not in m.group(1) else m.group(1).upper()
    return None


def parse_html(html: str, today: date) -> list[LessonRec]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: list[LessonRec] = []

    # Current sgugit.ru schedule is not a table: it is rendered as
    # .rasp_wrapper > .half_week > .date_info + .day > .day_hours.
    # Parse this official structure first, preserving empty lesson slots as gaps
    # (but do not create LessonRec rows for them).
    title = soup.find("h1")
    group_match = GROUP_RE.search(_text(title)) if title else None
    page_group = group_match.group(1).upper().replace(" ", "-") if group_match else None
    wrappers = soup.select(".rasp_wrapper")
    if wrappers and page_group:
        for wrapper in wrappers:
            # Не полагаемся на строгое вложение :scope > ...: шаблон сайта
            # периодически меняет уровни вложенности блоков.
            for half in (wrapper.select(".half_week") or [wrapper]):
                date_nodes = half.select(".date_info")
                for date_info in date_nodes:
                    date_el = date_info.select_one(".date")
                    day_iso = _day_from_text(_text(date_el), today) if date_el else None
                    if not day_iso:
                        continue
                    day_container = date_info.find_next_sibling(class_="day")
                    if day_container is None:
                        # Резерв: ближайший следующий .day внутри текущей половины недели,
                        # но не перескакиваем через следующий заголовок даты.
                        nxt_date = date_info.find_next(class_="date_info")
                        candidate = date_info.find_next(class_="day")
                        if candidate is not None and (nxt_date is None or candidate.sourceline is None or
                                                       nxt_date.sourceline is None or candidate.sourceline < nxt_date.sourceline):
                            day_container = candidate
                    if day_container is None:
                        continue
                    # Убираем вложенные дубли .day_hours, если они встречаются в разметке.
                    slots = day_container.select(".day_hours")
                    for num, slot in enumerate(slots, start=1):
                        start_end = [_text(x) for x in slot.select(".hour p")]
                        if len(start_end) < 2:
                            continue
                        start_m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", start_end[0])
                        end_m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", start_end[1])
                        if not start_m or not end_m:
                            continue
                        info = slot.select_one(".lesson_info")
                        if info is None:
                            # Пустые слоты на сайте нормальны, их пропускаем.
                            continue
                        subject_el = info.select_one(".lesson_name:not(.empty)")
                        subject = _text(subject_el) if subject_el else ""
                        if not subject:
                            continue
                        teacher_el = info.select_one(".teach_name")
                        teacher = _text(teacher_el) if teacher_el else ""
                        rooms = [_text(x) for x in info.select(".aud_num") if _text(x)]
                        kind_el = info.select_one(".lesson_type")
                        kind = _text(kind_el) if kind_el else ""
                        out.append(LessonRec(
                            group=page_group, day=day_iso, num=num,
                            start=f"{int(start_m.group(1)):02d}:{start_m.group(2)}",
                            end=f"{int(end_m.group(1)):02d}:{end_m.group(2)}",
                            subject=subject, teacher=teacher, room=", ".join(rooms), kind=kind,
                        ))
        if out:
            return out

    # Fallback for older / alternative pages that expose schedule as a table.
    for table in soup.find_all("table"):
        rows = _expanded_rows(table)
        header_idx, cols = None, {}
        for i, row in enumerate(rows[:10]):
            cells = [c.lower() for c in row]
            mapping: dict[str, int] = {}
            for j, c in enumerate(cells):
                for f, keys in HEADER_KEYS.items():
                    if f not in mapping and any(k in c for k in keys):
                        mapping[f] = j
            if "subject" in mapping and ("time" in mapping or "num" in mapping or "day" in mapping):
                header_idx, cols = i, mapping
                break
        if header_idx is None:
            continue
        table_group = _group_near(table)
        cur_day: str | None = None
        counter = 0
        for tds in rows[header_idx + 1:]:
            tds = [str(c).strip() for c in tds]
            if not tds:
                continue
            if len(tds) == 1 or (tds and len(set(tds)) == 1):  # разделитель даты, в том числе colspan
                d = _day_from_text(tds[0], today)
                if d:
                    cur_day, counter = d, 0
                continue

            def cell(f: str) -> str:
                j = cols.get(f)
                return tds[j] if j is not None and j < len(tds) else ""

            day = _day_from_text(cell("day"), today) if "day" in cols else None
            if day:
                if day != cur_day:
                    counter = 0
                cur_day = day
            tm = TIME_RE.search(cell("time")) if "time" in cols else None
            subject = re.sub(r"\s+", " ", cell("subject")).strip(" —-\t")
            if not (cur_day and tm and subject):
                continue
            counter += 1
            try:
                num = int(re.sub(r"\D", "", cell("num"))) if cell("num") else counter
            except ValueError:
                num = counter
            group = cell("group") or table_group
            gm = GROUP_RE.search(group or "")
            if not gm:
                continue
            out.append(LessonRec(
                group=gm.group(1).upper(), day=cur_day, num=num,
                start=f"{int(tm.group(1)):02d}:{tm.group(2)}", end=f"{int(tm.group(3)):02d}:{tm.group(4)}",
                subject=subject, teacher=cell("teacher"), room=cell("room"), kind=cell("kind")))
    if not out:
        raise ParseError("Не удалось распознать расписание на странице (структура страницы незнакома боту).")
    return out


async def fetch_site(url: str, today: date) -> list[LessonRec]:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; SGUGiTScheduleBot/1.0)", "Accept-Language": "ru"}
    async with httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=25, headers=headers) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ConnectionError(f"Сайт недоступен: {type(e).__name__}: {e}") from e
    return parse_html(resp.text, today)


GROUP_URL_RE = re.compile(r"/raspisanie/group/(\d+)/?")


def parse_group_links(html: str, page_url: str) -> list[tuple[str, str]]:
    """Извлекает URL групп из HTML, включая ссылки в скриптах и JSON-разметке.

    Каталог СГУГиТ может отдавать список через JS/атрибуты, а не только через
    обычные <a href="...">. Поэтому сначала читаем DOM, затем ищем URL в сыром
    HTML с учётом экранированных слешей и относительных ссылок.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    soup = BeautifulSoup(html, "lxml")
    found: dict[str, tuple[str, str]] = {}

    def add(href: str, name: str = "") -> None:
        href = (href or "").strip().replace("\\/", "/")
        if not href:
            return
        absolute = urljoin(page_url, href)
        match = GROUP_URL_RE.search(urlparse(absolute).path)
        if not match:
            # Некоторые JS-конфиги хранят только относительную часть group/<id>/.
            match = re.search(r"(?:^|/)group/(\d+)/?$", urlparse(absolute).path)
        if not match:
            return
        gid = match.group(1)
        clean_url = urljoin(page_url, f"/raspisanie/group/{gid}/")
        label = " ".join((name or "").split()) or f"Группа ID {gid}"
        found.setdefault(gid, (label, clean_url))

    for a in soup.find_all("a", href=True):
        add(str(a.get("href", "")), _text(a))

    # Ссылки могут быть записаны в data-*, option[value], JSON или JS как строка.
    for el in soup.find_all(True):
        for attr, value in el.attrs.items():
            vals = value if isinstance(value, list) else [value]
            for val in vals:
                if isinstance(val, str):
                    for m in re.finditer(r"(?:https?://[^\"'\s<>]+)?/?raspisanie/?group/?(\d+)/?", val):
                        add(m.group(0), _text(el))
                    if attr.lower() in {"value", "data-id", "data-group-id", "data-href", "data-url"}:
                        add(val, _text(el))

    # Резерв для JS-объектов и HTML, где URL экранирован внутри script.
    raw = html.replace("\\/", "/").replace("&amp;", "&")
    for m in re.finditer(r"(?:https?://[^/\"'\s<>]+)?/?raspisanie/group/(\d+)/?", raw, re.I):
        add(m.group(0))
    for m in re.finditer(r"(?:group|group_id|groupId)[\"'\s:=]+(\d+)", raw, re.I):
        gid = m.group(1)
        add(f"/raspisanie/group/{gid}/")

    return list(found.values())


async def fetch_all_groups(base_url: str, today: date) -> list[LessonRec]:
    """Загружает каталог, находит URL каждой группы и собирает расписания со страниц групп."""
    import asyncio
    import httpx
    from urllib.parse import urljoin

    base_url = base_url.rstrip("/") + "/"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SGUGiTScheduleBot/1.0)",
               "Accept-Language": "ru"}
    async with httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=30,
                                 headers=headers) as client:
        try:
            response = await client.get(base_url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ConnectionError(f"Не удалось загрузить каталог групп {base_url}: {type(e).__name__}: {e}") from e

        groups = parse_group_links(response.text, str(response.url))
        # Добавляем встроенные, ранее подтверждённые ссылки даже если каталог вернул
        # только часть списка. Они помогают не зависеть полностью от страницы каталога.
        from pathlib import Path
        import json
        manifest_path = Path(__file__).resolve().parents[2] / "data" / "group_url_candidates.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            known_links = [(str(item.get("name", f"Группа ID {item['id']}")), str(item["url"]))
                           for item in manifest.get("known_groups", [])
                           if isinstance(item, dict) and str(item.get("id", "")).isdigit()
                           and GROUP_URL_RE.search(str(item.get("url", "")))]
            seen_urls = {url.rstrip("/") for _, url in groups}
            groups.extend((name, url) for name, url in known_links if url.rstrip("/") not in seen_urls)
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            pass
        # Если в конфигурации уже указана конкретная страница группы, поддерживаем этот режим.
        if not groups and GROUP_URL_RE.search(str(response.url)):
            return parse_html(response.text, today)

        # Некоторые версии сайта используют www-домен для каталога, а расписание
        # отдельных групп доступно на основном домене. Пробуем оба канонических адреса.
        if not groups:
            from urllib.parse import urlparse
            parsed = urlparse(str(response.url))
            alternate_host = "www.sgugit.ru" if parsed.hostname == "sgugit.ru" else "sgugit.ru"
            alternate_url = f"{parsed.scheme}://{alternate_host}{parsed.path or '/raspisanie/'}"
            if parsed.query:
                alternate_url += "?" + parsed.query
            if alternate_url.rstrip("/") != str(response.url).rstrip("/"):
                try:
                    alternate = await client.get(alternate_url)
                    alternate.raise_for_status()
                    alt_groups = parse_group_links(alternate.text, str(alternate.url))
                    if alt_groups:
                        groups = alt_groups
                        log.info("Каталог групп найден через альтернативный домен: %s", alternate.url)
                except httpx.HTTPError as e:
                    log.debug("Альтернативный адрес каталога недоступен (%s): %s", alternate_url, e)

        if len(groups) < 100:
            # Каталог /raspisanie/ на некоторых ответах сайта содержит только
            # навигацию (список групп может подгружаться динамически). Резервный
            # путь: проверяем диапазон ID страниц групп. Проверяем именно заголовок
            # «Группа ...», поэтому не считаем произвольные страницы валидными.
            # ID сгруппированы в небольшом диапазоне, характерном для текущих URL
            # СГУГиТ; проверка запускается только если обычный каталог не сработал.
            from bs4 import BeautifulSoup
            from pathlib import Path
            import json
            # Встроенный в проект каталог кандидатов: не зависит от того, отдал ли
            # сайт ссылки в HTML. Это URL-кандидаты, а не утверждение, что каждый ID
            # существует; ниже каждая страница проверяется по заголовку.
            manifest_path = Path(__file__).resolve().parents[2] / "data" / "group_url_candidates.json"
            seed_ids = {1616, 1659, 1688, 1693, 1697, 1712, 1723, 1727,
                        1732, 1743, 1745, 1746, 1748, 1776, 1780, 1788, 1791, 1839}
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                seed_ids.update(int(x["id"]) for x in manifest.get("known_groups", []) if str(x.get("id", "")).isdigit())
                manifest_ids = {int(m.group(1)) for url in manifest.get("candidate_urls", [])
                                if (m := GROUP_URL_RE.search(str(url)))}
            except (OSError, ValueError, TypeError, AttributeError):
                manifest_ids = set()
            candidate_ids = sorted(seed_ids | manifest_ids | set(range(1450, 2101)))
            probe_sem = asyncio.Semaphore(12)
            discovered: dict[str, tuple[str, str]] = {}
            # Сохраняем обнаруженные реальные группы, чтобы не опрашивать сотни ID
            # при каждом плановом обновлении. Список ссылок устойчив, расписание — нет.
            cache_path = Path("data/group_urls.json")
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cached_groups = cached.get("groups", [])
                if cached_groups:
                    merged = {str(GROUP_URL_RE.search(str(url)).group(1)): (str(name), str(url))
                              for name, url in groups if GROUP_URL_RE.search(str(url))}
                    for item in cached_groups:
                            if isinstance(item, list) and len(item) == 2:
                                m = GROUP_URL_RE.search(str(item[1]))
                            if m:
                                merged.setdefault(m.group(1), (str(item[0]), str(item[1])))
                    groups = list(merged.values())
                    log.info("Объединён каталог групп с кэшем: %s ссылок", len(groups))
            except (OSError, ValueError, TypeError, AttributeError):
                pass

            async def probe_group(gid: int) -> None:
                url = urljoin(base_url, f"/raspisanie/group/{gid}/")
                async with probe_sem:
                    try:
                        probe = await client.get(url, timeout=12)
                        if probe.status_code != 200:
                            return
                        soup = BeautifulSoup(probe.text, "lxml")
                        # Разные шаблоны сайта могут использовать h1, h2 или title.
                        heading_texts = [_text(el) for el in soup.find_all(["h1", "h2", "h3"])]
                        if soup.title:
                            heading_texts.append(_text(soup.title))
                        page_text = _text(soup.body or soup)
                        heading_texts.append(page_text[:500])
                        match = None
                        for candidate_heading in heading_texts:
                            match = re.search(r"(?:^|[|—–-]\s*)Группа\s+([^|\n\r]+?)\s*(?:$|[|—–])", candidate_heading, re.I)
                            if match:
                                break
                        if not match:
                            return
                        group_name = match.group(1).strip()
                        # Не добавляем заголовок, похожий на текст ошибки/страницы.
                        if not re.fullmatch(r"(?:[А-ЯA-Z]{1,6}[- ]?\d{2,3}(?:\.\d+)?[А-Яа-я]?|\d+[А-ЯA-Z]{1,6}\.\d+)", group_name, re.I):
                            return
                        discovered[str(gid)] = (group_name, url)
                    except Exception as exc:
                        log.debug("Проверка ID группы %s не удалась: %s", gid, exc)

            # Даже если каталог вернул часть ссылок, он иногда обрезан или отдаёт
            # только текущую страницу. При небольшом каталоге дополняем его проверкой ID.
            # Существующие ссылки сохраняем и объединяем по ID, не заменяя каталог целиком.
            if len(groups) < 200:
                await asyncio.gather(*(probe_group(gid) for gid in candidate_ids))
                merged = {str(GROUP_URL_RE.search(str(url)).group(1)): (str(name), str(url))
                          for name, url in groups if GROUP_URL_RE.search(str(url))}
                merged.update(discovered)
                groups = list(merged.values())
                if discovered:
                    try:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps({"groups": groups}, ensure_ascii=False, indent=2), encoding="utf-8")
                    except OSError as exc:
                        log.warning("Не удалось сохранить локальный каталог групп: %s", exc)
                    log.info("Каталог групп дополнен проверкой ID: найдено %s дополнительных страниц", len(discovered))
            if not groups:
                soup = BeautifulSoup(response.text, "lxml")
                title = _text(soup.title) if soup.title else "без title"
                scripts = len(soup.find_all("script"))
                anchors = len(soup.find_all("a", href=True))
                raise ParseError(
                    "Каталог не содержит ссылок на группы; проверены встроенные URL-кандидаты "
                    "data/group_url_candidates.json (ID 1550–1900), но заголовки групп не распознаны: "
                    f"title={title!r}, anchors={anchors}, "
                    f"scripts={scripts}, bytes={len(response.content)}."
                )

        semaphore = asyncio.Semaphore(5)
        async def one(item: tuple[str, str]) -> list[LessonRec]:
            name, url = item
            async with semaphore:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    recs = parse_html(resp.text, today)
                    log.info("Расписание группы %s загружено: %s занятий (%s)", name, len(recs), url)
                    return recs
                except Exception as e:
                    log.warning("Не удалось загрузить расписание группы %s (%s): %s", name, url, e)
                    return []

        batches = await asyncio.gather(*(one(group) for group in groups))
        all_recs = [rec for batch in batches for rec in batch]
        if not all_recs:
            raise ParseError(f"Не удалось получить расписание ни одной из {len(groups)} найденных групп.")
        log.info("Каталог групп: найдено %s, успешно загружено расписаний для %s групп, занятий: %s",
                 len(groups), sum(bool(batch) for batch in batches), len(all_recs))
        return all_recs
