"""Понимание вопросов обычным текстом (правила и словари, без внешних сервисов)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = [("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("май", 5), ("июн", 6),
          ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12)]
_MONTH_RE = r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
_NUMDATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_DAYMONTH_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})")
WEEKDAY_ABBR = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
WEEKDAY_STEMS = [("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4),
                 ("суббот", 5), ("воскресень", 6)]
ORDINALS = [("перв", 1), ("втор", 2), ("трет", 3), ("четверт", 4), ("пят", 5), ("шест", 6), ("седьм", 7), ("восьм", 8)]
STOP = {"по", "на", "в", "и", "у", "с", "к", "о", "об", "а", "что", "как", "это", "нас", "нам", "мне", "мы"}


def norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s./:\-]", " ", t)
    return " ".join(t.split())


def _tokens(t: str) -> list[str]:
    return re.findall(r"[а-яa-z0-9]+(?:[./][0-9]+)*", t)


@dataclass
class Intent:
    name: str
    day: date | None = None
    num: int | None = None
    subject: str | None = None
    week_shift: int | None = None  # 0 - эта неделя, 1 - следующая (если спрашивали про неделю)
    explicit_day: bool = False
    teacher: str | None = None     # запрос преподавателя: «крылов» или «крылов аа»


def _resolve_numdate(m: re.Match, today: date) -> date | None:
    d, mo = int(m.group(1)), int(m.group(2))
    y = m.group(3)
    try:
        if y:
            yy = int(y)
            if yy < 100:
                yy += 2000
            return date(yy, mo, d)
        cand = date(today.year, mo, d)
        if cand < today - timedelta(days=60):
            cand = date(today.year + 1, mo, d)
        return cand
    except ValueError:
        return None


def parse_when(text: str, today: date) -> tuple[date | None, int | None]:
    """Возвращает (день, сдвиг недели). Сдвиг задан, если в тексте есть слово «неделя»."""
    t = norm(text)
    toks = _tokens(t)
    week_shift: int | None = None
    if any(tok.startswith("недел") for tok in toks):
        week_shift = 1 if any(tok.startswith(("след", "будущ")) for tok in toks) else 0
    day: date | None = None
    if "послезавтра" in toks or "после завтра" in t:
        day = today + timedelta(days=2)
    elif "позавчера" in toks:
        day = today - timedelta(days=2)
    elif "завтра" in toks or "завтрашн" in t:
        day = today + timedelta(days=1)
    elif "вчера" in toks:
        day = today - timedelta(days=1)
    elif any(x in toks for x in ("сегодня", "седня", "сегодняшн", "щас")) or "сегодняшн" in t:
        day = today
    if day is None:
        m = re.search(r"\bчерез\s+(\d{1,2})\s+(?:дн|день|дня)", t)
        if m:
            day = today + timedelta(days=int(m.group(1)))
        elif re.search(r"\bчерез\s+недел", t):
            day = today + timedelta(days=7)
    if day is None:
        m2 = _DAYMONTH_RE.search(t)
        if m2:
            mo = next((n for stem, n in MONTHS if m2.group(2).startswith(stem)), None)
            if mo:
                try:
                    cand = date(today.year, mo, int(m2.group(1)))
                    if cand < today - timedelta(days=60):
                        cand = date(today.year + 1, mo, int(m2.group(1)))
                    day = cand
                except ValueError:
                    pass
    if day is None:
        m3 = _NUMDATE_RE.search(t)
        if m3:
            day = _resolve_numdate(m3, today)
    if day is None:
        wd = None
        for tok in toks:
            if tok in WEEKDAY_ABBR:
                wd = WEEKDAY_ABBR[tok]
                break
            hit = next((n for stem, n in WEEKDAY_STEMS if tok.startswith(stem)), None)
            if hit is not None:
                wd = hit
                break
        if wd is not None:
            delta = (wd - today.weekday()) % 7
            if delta == 0:
                delta = 7
            day = today + timedelta(days=delta)
            if any(tok.startswith("след") for tok in toks) and week_shift is None:
                day += timedelta(days=7)
    return day, week_shift


def _lesson_number(toks: list[str]) -> int | None:
    def pairish(i: int) -> bool:
        return any(re.fullmatch(r"пар(а|ы|е|у|ой|ам|ах)?", toks[j]) for j in range(max(0, i - 2), min(len(toks), i + 3)))

    for i, tok in enumerate(toks):
        m = re.fullmatch(r"(\d)(?:-?(?:я|ая|ой|ую|ей|е))?", tok)
        if m and pairish(i) and 1 <= int(m.group(1)) <= 9:
            return int(m.group(1))
        for stem, n in ORDINALS:
            if tok.startswith(stem) and len(tok) <= len(stem) + 4 and pairish(i):
                return n
    return None


def _same_stem(a: str, t: str) -> bool:
    if a == t:
        return True
    if len(a) < 3 or len(t) < 3:
        return False
    cp = 0
    for x, y in zip(a, t):
        if x != y:
            break
        cp += 1
    if len(a) <= 4:
        return cp >= len(a) and len(t) <= len(a) + 3
    if cp >= 5 or (cp >= 4 and cp >= len(a) - 2):
        return True
    return len(a) >= 6 and len(t) >= 6 and difflib.SequenceMatcher(None, a, t).ratio() >= 0.86


def find_subject(text: str, catalog: list[tuple[str, str]]) -> str | None:
    """catalog: [(alias, subject)], где alias - как пишут люди, subject - официальное название."""
    toks = [x for x in _tokens(norm(text)) if x not in STOP]
    if not toks:
        return None
    best: tuple[float, int, str] | None = None
    for alias, subject in catalog:
        a_toks = [x for x in _tokens(norm(alias)) if x not in STOP and len(x) >= 2]
        if not a_toks:
            continue
        matched = sum(1 for a in a_toks if any(_same_stem(a, t) for t in toks))
        score = matched / len(a_toks)
        need = 1.0 if len(a_toks) <= 2 else 0.6
        if score >= need:
            key = (score, sum(len(a) for a in a_toks), subject)
            if best is None or key[:2] > best[:2]:
                best = key
    return best[2] if best else None


_NOT_SURNAMES = {"пара", "пары", "завтра", "сегодня", "какая", "какие", "когда", "где", "найти", "кабинет", "кафедра"}
_TEACHER_TRIGGERS = ("где", "найти", "найду", "искать", "ищу", "сидит", "находится", "кабинет", "каб", "аудитория", "аудитории",
                     "кафедра", "кафедре", "подразделение", "принимает", "прием", "приём", "контакты", "кто", "когда",
                     "пара", "пары", "видели", "видел", "препод", "преподаватель", "преподавателя", "лектор", "сейчас", "щас", "ведет", "ведёт")


def extract_teacher(text: str, known: set[str] | None) -> str | None:
    """Находит в тексте фамилию преподавателя из справочника (с учётом падежа) и инициалы после неё."""
    if not known:
        return None
    from app.services.names import surname_close

    raw = re.findall(r"[А-ЯЁ]\.\s?[А-ЯЁ]?\.?|[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)?", text or "")
    for i, tok in enumerate(raw):
        t = tok.lower().replace("ё", "е")
        if len(t) < 4 or t in _NOT_SURNAMES or "." in t:
            continue
        canon = t if t in known else next((k for k in sorted(known) if surname_close(t, k)), None)
        if canon is None:
            continue
        t = canon
        initials = ""
        if i + 1 < len(raw) and "." in raw[i + 1]:
            initials = re.sub(r"[^А-Яа-яЁё]", "", raw[i + 1]).lower()
        return f"{t} {initials}".strip()
    return None


_QUESTION_WORDS = {"какая", "какие", "какой", "какое", "когда", "где", "кто", "сколько", "куда", "будет", "будут", "есть",
                   "во", "почему", "зачем", "скажите", "подскажите", "подскажи", "скажи", "что", "чо", "че", "ли", "как"}


def looks_like_question(text: str) -> bool:
    t = norm(text)
    toks = _tokens(t)
    if "?" in (text or ""):
        return True
    return bool(toks) and (toks[0] in _QUESTION_WORDS or "ли" in toks or toks[-1] in ("будет", "будут", "есть"))


def _has(t: str, *subs: str) -> bool:
    return any(s in t for s in subs)


def _before(toks: list[str], first: tuple[str, ...], second: tuple[str, ...]) -> bool:
    """Есть слово из first, а после него (не обязательно рядом) слово, начинающееся с одного из second."""
    for i, tok in enumerate(toks):
        if tok in first:
            if any(x.startswith(second) for x in toks[i + 1:]):
                return True
    return False


_PAR_RE = re.compile(r"\bпар(а|ы|е|у|ой|ам|ах)?\b")


def detect_intent(text: str, today: date, catalog: list[tuple[str, str]] | None = None,
                  known_surnames: set[str] | None = None) -> Intent | None:
    t = norm(text)
    if not t:
        return None
    toks = _tokens(t)
    if not toks:
        return None
    catalog = catalog or []
    day, week_shift = parse_when(text, today)
    explicit = day is not None
    num = _lesson_number(toks)
    subject = find_subject(t, catalog) if catalog else None
    has_par = bool(_PAR_RE.search(t))

    teacher_q = extract_teacher(text, known_surnames) if known_surnames else None

    def mk(name: str, **kw) -> Intent:
        return Intent(name=name, day=kw.get("day", day), num=kw.get("num", num), subject=subject,
                      week_shift=week_shift, explicit_day=explicit, teacher=teacher_q)

    if _has(t, "помощь", "что умеешь", "что ты умеешь", "команды", "как пользоваться") or "help" in toks:
        return mk("help")
    if any(x in toks for x in ("спасибо", "благодарю", "спс", "thanks", "сенкс")):
        return mk("thanks")
    if len(toks) <= 3 and any(x in toks for x in ("привет", "здравствуй", "здравствуйте", "хай", "добрый", "доброе", "приветик", "салют")):
        return mk("greet")
    if _has(t, "какая неделя", "какая сейчас неделя", "чет неделя", "четная", "нечетная", "четность") and "недел" in t:
        return mk("parity")
    if any(x.startswith(("экзамен", "зачет", "сесси", "консультац")) for x in toks):
        return mk("exam")
    if any(x.startswith(("дз", "домашк", "домашн", "задан", "задал", "задач")) or x == "д/з" for x in toks):
        return mk("hw")
    if teacher_q and any(x in _TEACHER_TRIGGERS or x.startswith(("препод", "лектор")) for x in toks):
        return mk("find_teacher")
    if any(x.startswith("недел") for x in toks) and (has_par or "расписан" in t or "что" in toks or "какие" in toks
                                                        or week_shift is not None):
        return mk("week")
    starts = _before(toks, ("когда", "сколько", "скольки"), ("начин", "начал", "начнем", "начнутся", "начнется"))
    if (_has(t, "первая пара", "первой пар", "первую пар", "к скольки", "с какой пары", "начало пар",
             "когда первая", "первая завтра") or starts
            or (num == 1 and has_par and not _has(t, "где", "аудитор", "кабинет", "кто"))):
        return mk("first", num=1)
    ends = _before(toks, ("когда", "сколько", "скольки"), ("заканчив", "кончаем", "кончают", "кончатся", "закончим",
                                                         "закончатся", "домой", "свободн"))
    if (_has(t, "последняя пара", "последней пар", "последнюю пар", "до скольки", "конец пар", "когда домой") or ends):
        return mk("last")
    if _has(t, "следующая пара", "следующей пар", "следующую пар", "что дальше", "какая дальше", "что сейчас",
            "какая сейчас", "сейчас пара", "текущая пара", "какая щас", "что щас", "что потом", "какая пара сейчас",
            "что у нас сейчас", "что сейчас идет", "что идет") or (has_par and _has(t, "сейчас", "щас") and not explicit):
        return mk("next")
    if _has(t, "сколько пар", "много пар", "есть ли пары", "есть пары", "выходной", "пары будут", "будут ли пары",
            "пар нет", "без пар", "учимся", "учебный день", "занятия будут", "будут занятия", "пары есть") or (
            has_par and ("ли" in toks or ("есть" in toks and "что" not in toks and "какие" not in toks))):
        return mk("count")
    if "кто" in toks and (subject or has_par or any(x.startswith(("вед", "чита", "препод", "лектор")) for x in toks)):
        return mk("teacher")
    if any(x.startswith(("препод", "лектор")) for x in toks) and ("какой" in toks or "кто" in toks):
        return mk("teacher")
    if any(x.startswith(("аудитор", "кабинет")) or x in ("каб", "куда", "где") for x in toks) and (has_par or subject or num):
        return mk("room")
    if "когда" in toks and subject:
        return mk("when_subject")
    if subject and (explicit or any(x in toks for x in ("будет", "будут", "есть", "ли", "состоится", "состоятся", "отменили",
                                                       "отменена", "отменят", "перенесли", "перенесена", "идем", "идет", "нет"))):
        return mk("subject_day")
    if has_par or any(x.startswith(("расписан", "занят", "лекци", "семинар")) for x in toks):
        return mk("day")
    if explicit and any(x in toks for x in ("что", "какие", "какое")) and len(toks) <= 5:
        return mk("day")
    return None


# -------- быстрые задания одной фразой --------
_HW_PREFIX = re.compile(r"^\s*(?:дз|д/з|домашка|домашнее\s+задание|домашнее|задание|задали|задача)\s*[:,\-–—]?\s*(.*)$",
                        re.I | re.S)
_WD_FORMS = r"(?:понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*|пн|вт|ср|чт|пт|сб|вс)"
_DUE_RE = re.compile(
    rf"\b(?:до|к|на)\s+(?:сегодня|завтра|послезавтра|{_WD_FORMS}|\d{{1,2}}[./]\d{{1,2}}(?:[./]\d{{2,4}})?|\d{{1,2}}\s+{_MONTH_RE})",
    re.I)

DUE_RE = _DUE_RE


@dataclass
class HwPhrase:
    subject: str
    text: str
    due: date | None


def parse_hw_phrase(text: str, catalog: list[tuple[str, str]], today: date) -> HwPhrase | None:
    m = _HW_PREFIX.match(text or "")
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest:
        return None
    rest_n = rest.lower().replace("ё", "е")
    due: date | None = None
    dm = _DUE_RE.search(rest_n)
    body = rest
    if dm:
        due, _ = parse_when(dm.group(0), today)
        body = (rest[:dm.start()] + " " + rest[dm.end():]).strip()
    subject = find_subject(body, catalog)
    if not subject:
        return None
    # убираем из начала упоминание предмета
    alias_tokens: set[str] = set()
    for alias, subj in catalog:
        if subj == subject:
            alias_tokens.update(x for x in _tokens(norm(alias)) if x not in STOP)
    words = body.split()
    i = 0
    while i < len(words) and i < 4:
        w = norm(words[i])
        if w in STOP or any(_same_stem(a, w) for a in alias_tokens):
            i += 1
        else:
            break
    body2 = " ".join(words[i:]).strip(" :,-–—")
    if len(body2) >= 3:
        body = body2
    meaningful = [x for x in _tokens(norm(body)) if x not in STOP
                  and x not in ("какое", "задали", "есть", "ли", "ну", "завтра", "сегодня", "послезавтра")
                  and not any(_same_stem(a, x) for a in alias_tokens)]
    if len(meaningful) < 2 and "?" in text or len(meaningful) < 1:
        return None
    if "?" in text and len(meaningful) < 3:
        return None
    return HwPhrase(subject=subject, text=body.strip(), due=due)
