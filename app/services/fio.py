"""Проверка ФИО при регистрации.

Задача: отсеять мусор, заглушки, шаблоны и оскорбления и пропустить правдоподобные ФИО.
Бот НЕ может доказать, что человек носит именно эти ФИО (списков групп нет),
поэтому проверяется правдоподобие, а не подлинность.

Вердикты: ``ok`` - принять, ``review`` - принять, но отправить на проверку админу,
``reject`` - попросить ввести заново.

Кроме формы проверяются: профанация (в т.ч. с растяжкой букв), известные люди и персонажи, шуточные и бытовые
слова, согласование рода фамилии/имени/отчества, правдоподобие букв, реальность фамилии (словарь + справочник
преподавателей + уже подтверждённые студенты) и совпадение с преподавателем. Поле ``confident`` у результата
означает «можно подтверждать автоматически»: для этого нужно известное имя, отчество от известного мужского
имени, фамилия из словарей или правдоподобная по форме и отсутствие любых флагов.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.fio_data import (CELEBRITY_PAIRS, CELEBRITY_SURNAMES, COMMON_SURNAMES, FAKE_SURNAMES, FEMALE_NAMES,
                                   GIVEN_NAMES, MALE_NAMES, NAME_AND_SURNAME, NON_NAME_WORDS, SHORT_FOREIGN,
                                   SURNAME_COMMON_WORDS_OK, SURNAME_SUFFIXES)

PARTICLES = {"оглы", "кызы", "угли", "улы", "кизи", "уулу", "кыз"}
PATR_SUFFIXES = ("ович", "евич", "ьич", "ич", "овна", "евна", "ьевна", "ична", "инична",
                 "кызы", "оглы", "угли", "улы", "кизи", "уулу", "кыз")

STUB_WORDS = {
    "фамилия", "имя", "отчество", "фио", "ф.и.о", "тест", "test", "студент", "студентка", "админ",
    "admin", "аноним", "аноним", "анонимус", "неизвестно", "неизвестный", "никто", "нет", "нету",
    "пользователь", "юзер", "user", "бот", "bot", "человек", "ученик", "староста", "преподаватель",
    "фамилияимяотчество", "имяфамилия", "хз", "незнаю", "неважно", "секрет", "скрыто", "секретно",
    "абвгд", "абв", "авыа", "пароль", "логин", "никнейм", "ник",
}
STUB_PHRASES = {
    "иванов иван иванович", "петров петр петрович", "петров пётр петрович", "сидоров сидор сидорович",
    "иванов иван", "петров петр", "иванова иванна ивановна", "иванов иван иванов",
    "фамилия имя", "имя фамилия", "фамилия имя отчество", "тест тестов тестович", "тестов тест тестович",
    "студент студентов студентович", "пупкин василий", "пупкин василий иванович",
}
KEYBOARD_JUNK = ("йцук", "цукен", "фывап", "ывапр", "ячсми", "пролдж", "олджэ", "кенгш", "ёйцу",
                 "qwer", "asdf", "zxcv", "абвгд", "ячс", "ппп", "ыыы", "ыва", "выа", "фыв")
BAD_CONTAINS = ("курв", "хуй", "хуе", "хуя", "пизд", "залуп", "блят", "бляд", "мудак", "мудил", "гандон", "говн",
                "дерьм", "шлюх", "сучар", "педик", "пидор", "пидар", "пидр", "хер", "хрен", "жопа", "жопу",
                "срак", "сран", "дроч", "минет", "член", "нацист", "гитлер")
BAD_PREFIX_STEMS = ("ебан", "ебат", "ебал", "ебуч", "еблан", "ебне", "ебну", "ебло", "ебуч", "ебат")
BAD_PREFIXES = ("", "на", "по", "за", "раз", "вы", "у", "до", "от", "об", "в", "с", "при", "под", "из", "съ")
BAD_WHOLE = {
    "сука", "суки", "сучка", "сучок", "дурак", "дура", "дурочка", "идиот", "идиотка", "тупой", "тупая",
    "лох", "лошара", "чмо", "даун", "урод", "уродка", "дебил", "дебилка", "придурок", "кретин", "мразь",
    "тварь", "падла", "гнида", "гомик", "нахуй", "нахер", "похуй", "пох", "жопа", "хуй", "срать", "гавно",
    "говно", "хер", "хрен", "ссыкло", "лузер", "бомж", "мудак", "козел", "козёл", "скотина", "свинья",
    "шалава", "проститутка", "шлюха", "сволочь", "ублюдок", "выродок", "тупица", "олень", "баран", "чурка",
}
# Слова, которые выглядят подозрительно, но являются настоящими фамилиями (для запретных подстрок)
SAFE_SURNAMES = {"херувимов", "хренов", "хренников", "хрен", "членов", "хервиль"}

COMMON_NAMES = GIVEN_NAMES  # совместимость: используется в providers/directory.py

KB_BAD_BIGRAMS = ("ыы", "ьь", "ъъ", "йй", "ьъ", "ъь", "ьы", "ъы", "ыъ", "ыь", "ъй", "ьй", "аъ", "оъ", "еъ")
REVIEW_BIGRAMS = ("жы", "шы", "чы", "щы", "чя", "щя", "чю", "щю", "ьа", "ьо", "ьу")
VOWELS = set("аеёиоуыэюя")
CONS_NO_SIGN = set("бвгджзйклмнпрстфхцчшщ")

_LETTERS_RE = re.compile(r"^[а-яё]+(?:[-'’][а-яё]+)*$")
_REPEAT_RE = re.compile(r"(.)\1\1")
_INITIALS_RE = re.compile(r"(?<![а-яёa-z])[а-яёА-ЯЁ]\.")


@dataclass
class FioResult:
    verdict: str  # ok | review | reject
    fio: str
    code: str
    message: str
    reasons: tuple[str, ...] = ()  # причины отправки на проверку (коды из REASON_TEXT)
    confident: bool = False  # True: ФИО можно подтверждать автоматически


@dataclass(frozen=True)
class FioContext:
    """Данные из БД: реальные фамилии (справочник, расписание, уже подтверждённые студенты) и преподаватели."""
    known_surnames: frozenset[str] = frozenset()
    staff_pairs: frozenset[tuple[str, str]] = frozenset()  # (фамилия, инициалы) преподавателей
    require_known_surname: bool = False  # True: автоподтверждение только для фамилий из словарей


REASON_TEXT = {
    "name_unknown": "имя не найдено в словаре имён",
    "no_patronymic": "не указано отчество",
    "patronymic": "третье слово не похоже на отчество",
    "patr_unknown": "отчество не образовано от известного мужского имени",
    "surname_unknown": "фамилия не найдена в словарях/справочнике и не похожа на фамилию по форме",
    "surname_pattern": "фамилия правдоподобна по форме, но не найдена в словарях, справочнике и среди подтверждённых",
    "celebrity_namesake": "совпадает с именем известного человека (возможно, тёзка)",
    "celebrity_surname": "фамилия известной личности",
    "staff_match": "совпадает с преподавателем из справочника",
    "bigram": "необычные сочетания букв",
    "consonants": "длинная цепочка согласных",
}


def describe_reasons(codes: str | tuple[str, ...] | list[str]) -> str:
    items = codes.split(",") if isinstance(codes, str) else list(codes)
    return "; ".join(REASON_TEXT.get(c, c) for c in items if c)


def _fold(s: str) -> str:
    return s.lower().replace("ё", "е")


def is_patronymic(word: str) -> bool:
    w = _fold(word)
    return any(w.endswith(sfx) for sfx in PATR_SUFFIXES)


def _capitalize(piece: str) -> str:
    if piece in PARTICLES:
        return piece
    return re.sub(r"[а-яё]+", lambda m: m.group(0).capitalize(), piece.lower())


# ---------------------------------------------------------------- вспомогательные функции словарей
_FEM_SURNAME_END = (("ская", "ский"), ("цкая", "цкий"), ("ова", "ов"), ("ева", "ев"), ("ина", "ин"), ("ына", "ын"))
_STRONG_STEMS = ("хуй", "пизд", "залуп", "бляд", "блят", "мудак", "ебан", "ебат", "еблан", "гандон", "дроч")


def _collapse(seg: str) -> str:
    """«хууууй» -> «хуй»: растянутые буквы часто маскируют ругательства."""
    return re.sub(r"(.)\1+", r"\1", seg)


def surname_keys(word: str) -> set[str]:
    """Словарные формы фамилии: Иванова -> иванов, Крылова -> крылов, Белая -> белый/белой/белий."""
    w = _fold(word)
    keys = {w}
    for fem, masc in _FEM_SURNAME_END:
        if w.endswith(fem):
            keys.add(w[: -len(fem)] + masc)
    if w.endswith("ая") and not w.endswith(("ская", "цкая")):
        keys.update({w[:-2] + "ый", w[:-2] + "ой", w[:-2] + "ий"})
    return keys


def _male_patronymics(name: str) -> set[str]:
    n = _fold(name)
    special = {"павел": "павлович", "лев": "львович", "михаил": "михайлович", "яков": "яковлевич"}
    if n in special:
        return {special[n]}
    if n.endswith(("ей", "ай")):
        return {n[:-1] + "евич"}
    if n.endswith("ий"):
        return {n[:-1] + "евич", n[:-2] + "ьевич"}
    if n.endswith("ь"):
        return {n[:-1] + "евич"}
    if n.endswith("я"):
        return {n[:-1] + "ич"}  # илья -> ильич
    if n.endswith("а"):
        return {n[:-1] + "ич", n[:-1] + "ович"}
    return {n + "ович"}


def _female_patronymics(male: str) -> set[str]:
    if male.endswith("ьич"):
        return {male[:-2] + "инична"}
    if male.endswith(("ович", "евич")):
        return {male[:-2] + "на"}
    return {male[:-2] + "ична", male[:-2] + "инична"}


def _build_patronymics() -> frozenset[str]:
    forms: set[str] = set()
    for name in MALE_NAMES:
        for m in _male_patronymics(name):
            forms.add(m)
            forms.update(_female_patronymics(m))
    return frozenset(forms)


PATRONYMIC_FORMS = _build_patronymics()


def patronymic_known(piece: str) -> bool:
    """Отчество образовано от известного мужского имени (Сергеевич, Ильинична, «Рашид оглы»)."""
    parts = _fold(piece).split(" ")
    if len(parts) > 1 and parts[-1] in {_fold(x) for x in PARTICLES}:
        return parts[0] in MALE_NAMES
    return parts[0] in PATRONYMIC_FORMS


def _surname_gender(piece: str) -> str | None:
    w = _fold(piece).split(" ")[0].split("-")[-1]
    if w.endswith(("ская", "цкая", "ова", "ева")) or (len(w) >= 5 and w.endswith(("ина", "ына", "ая"))):
        return "f"
    if w.endswith(("ов", "ев", "ский", "цкий", "ской")):
        return "m"
    return None


def _name_gender(word: str) -> str | None:
    w = _fold(word)
    if w in MALE_NAMES and w not in FEMALE_NAMES:
        return "m"
    if w in FEMALE_NAMES and w not in MALE_NAMES:
        return "f"
    return None


def _patr_gender(piece: str) -> str | None:
    parts = _fold(piece).split(" ")
    if len(parts) > 1:
        if parts[-1] in ("оглы", "улы", "угли", "уулу"):
            return "m"
        if parts[-1] in ("кызы", "кизи", "кыз"):
            return "f"
    w = parts[0]
    if w.endswith(("овна", "евна", "ьевна", "ична", "инична")):
        return "f"
    if w.endswith("ич"):
        return "m"
    return None


_RARE_LETTERS = set("ъыэщфцчшжх")


def _vowel_ratio(seg: str) -> float:
    letters = [c for c in seg if c.isalpha()]
    return sum(c in VOWELS for c in letters) / len(letters) if letters else 0.0


def _max_cons_run(seg: str) -> int:
    best = run = 0
    for ch in seg:
        run = run + 1 if ch in CONS_NO_SIGN else 0
        best = max(best, run)
    return best


def _junk_code(seg: str) -> str | None:
    """Грубые признаки случайного набора букв (для слов, которых нет в словарях)."""
    n = len(seg)
    if n >= 5 and not 0.17 <= _vowel_ratio(seg) <= 0.72:
        return "junk"
    if re.search(r"(.{2,4})\1\1", seg):
        return "junk"
    if n >= 4 and sum(c in _RARE_LETTERS for c in seg) / n > 0.5:
        return "junk"
    if re.search(r"ъ(?![еюя])", seg):
        return "junk"
    return None


def _phono_ok(seg: str) -> bool:
    """Слово произносимо и не содержит подозрительных сочетаний: можно считать его фамилией по форме."""
    if _junk_code(seg):
        return False
    n = len(seg)
    if n >= 4:
        if not 0.2 <= _vowel_ratio(seg) <= 0.7:
            return False
        if sum(c in _RARE_LETTERS for c in seg) / n > 0.4:
            return False
    return (_max_cons_run(seg) < 4 and not any(bg in seg for bg in REVIEW_BIGRAMS)
            and not re.search(r"[аеиоуыэюя]ь", seg))


def _within1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _celeb_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for entry in CELEBRITY_PAIRS:
        sn, nm = entry.split(" ", 1)
        idx.setdefault(nm, []).append(sn)
    return idx


CELEB_BY_NAME = _celeb_index()


def _celebrity_hit(words: list[str]) -> bool:
    """Есть пара «фамилия + имя» известного человека/персонажа в любом порядке, с допуском на одну опечатку."""
    keysets = [surname_keys(w) for w in words]
    for i, name in enumerate(words):
        for sn in CELEB_BY_NAME.get(name, ()):
            for j, keys in enumerate(keysets):
                if j != i and any(k == sn or (len(sn) >= 5 and _within1(k, sn)) for k in keys):
                    return True
    return False


def _known_surname_seg(seg: str, ctx: FioContext | None) -> bool:
    known = ctx.known_surnames if ctx else frozenset()
    return any(k in COMMON_SURNAMES or k in known for k in surname_keys(seg))


def surname_evidence(piece: str, ctx: FioContext | None = None) -> str:
    """known - фамилия есть в словарях/справочнике; pattern - не найдена, но похожа по форме; unknown - не похожа."""
    parts = [p for p in re.split(r"[-'’]", _fold(piece.split(" ")[0])) if p]
    if any(_known_surname_seg(p, ctx) for p in parts):
        return "known"
    for p in parts:
        if p in GIVEN_NAMES and p not in NAME_AND_SURNAME:
            return "unknown"
        if len(p) < 3 and p not in SHORT_FOREIGN:
            return "unknown"
        has_suffix = p in SHORT_FOREIGN or any(k.endswith(SURNAME_SUFFIXES) for k in surname_keys(p))
        if not (has_suffix and _phono_ok(p)):
            return "unknown"
    return "pattern" if parts else "unknown"


def _initials_of(words: list[str]) -> str:
    return "".join(w[0] for w in words[1:] if w)


def fio_key(fio: str) -> str:
    """Ключ для поиска дубликатов: фамилия (без рода) + имя + первая буква отчества, без регистра и «ё»."""
    words = _fold(fio or "").split()
    if not words:
        return ""
    sn = sorted(surname_keys(words[0]), key=len)[0] if len(words[0]) > 4 else words[0]
    return " ".join([sn] + words[1:2] + [w[0] for w in words[2:3]])


def _staff_match(words: list[str], ctx: FioContext | None) -> bool:
    if not ctx or not ctx.staff_pairs:
        return False
    keys = surname_keys(words[0])
    ini = _initials_of(words)
    return any(sn in keys and (not si or not ini or si.startswith(ini) or ini.startswith(si))
               for sn, si in ctx.staff_pairs)


def _bad_word(seg: str, extra_bad: frozenset[str]) -> bool:
    if surname_keys(seg) & SAFE_SURNAMES:
        return False
    if seg in PATRONYMIC_FORMS or seg in GIVEN_NAMES:
        return False  # настоящие отчества и имена: «Олеговна» содержит «говн», но это не ругательство
    for variant in {seg, _collapse(seg)}:
        if variant in BAD_WHOLE:
            return True
        if any(stem in variant for stem in BAD_CONTAINS):
            return True
        for stem in BAD_PREFIX_STEMS:
            for p in BAD_PREFIXES:
                if variant.startswith(p + stem):
                    return True
        if any(b and b in variant for b in extra_bad):
            return True
    return False


def _reject(code: str, message: str) -> FioResult:
    return FioResult("reject", "", code, message)


_JUNK_MSG = "Похоже на случайный набор букв. Введите настоящие ФИО."


def validate_fio(raw: str, extra_stop: frozenset[str] = frozenset(), extra_bad: frozenset[str] = frozenset(),
                 strict: bool = True, ctx: FioContext | None = None) -> FioResult:
    """strict=True: сомнительные случаи уходят на проверку (review); strict=False: принимаются сразу.

    ``ctx`` (необязательно) добавляет данные БД: реальные фамилии и преподавателей. Без него работают только словари.
    """
    text = " ".join((raw or "").split())
    if not text:
        return _reject("empty", "Напишите ФИО: Фамилия Имя Отчество.")
    if len(text) > 80:
        return _reject("length", "Слишком длинно. Нужны Фамилия Имя Отчество.")
    if _INITIALS_RE.search(text):
        return _reject("initials", "Напишите полностью, без инициалов: Фамилия Имя Отчество.")
    has_lat = bool(re.search(r"[A-Za-z]", text))
    has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
    if has_lat and has_cyr:
        return _reject("mixed", "В ФИО смешаны русские и латинские буквы. Пишите только кириллицей.")
    if has_lat:
        return _reject("latin", "Пожалуйста, напишите ФИО кириллицей: Фамилия Имя Отчество.")
    if not re.fullmatch(r"[А-Яа-яЁё\-'’ ]+", text):
        return _reject("chars", "В ФИО должны быть только русские буквы (допускаются дефис и пробелы).")

    # склеиваем частицы «оглы», «кызы» с отчеством
    pieces: list[str] = []
    for w in text.split(" "):
        if _fold(w) in PARTICLES and pieces:
            pieces[-1] = pieces[-1] + " " + w.lower()
        else:
            pieces.append(w)
    if len(pieces) < 2:
        return _reject("format", "Нужно минимум два слова: Фамилия и Имя (лучше и Отчество).")
    if len(pieces) > 3:
        return _reject("format", "Слишком много слов. Напишите: Фамилия Имя Отчество.")

    flags: list[str] = []
    folded_words: list[str] = []
    for idx, piece in enumerate(pieces):
        base = piece.split(" ")[0]
        fw = _fold(base)
        folded_words.append(fw)
        if not _LETTERS_RE.match(fw):
            return _reject("chars", "Проверьте написание: только буквы, дефис между частями фамилии.")
        for seg in re.split(r"[-'’]", fw):
            if len(seg) < 2:
                return _reject("short", "Слова слишком короткие. Напишите ФИО полностью.")
            if len(seg) > 25:
                return _reject("length", "Слишком длинное слово. Проверьте ФИО.")
            # слова из словарей (реальные фамилии и имена) не проверяем на «случайность»
            trusted = (idx == 0 and _known_surname_seg(seg, ctx)) or (idx == 1 and seg in GIVEN_NAMES)
            if _REPEAT_RE.search(seg):
                return _reject("junk", _JUNK_MSG)
            if not (set(seg) & VOWELS):
                return _reject("junk", _JUNK_MSG)
            if seg[0] in "ьъы":
                return _reject("junk", "Слово не может начинаться с этой буквы. Проверьте ФИО.")
            if any(bg in seg for bg in KB_BAD_BIGRAMS):
                return _reject("junk", _JUNK_MSG)
            if any(k in seg for k in KEYBOARD_JUNK) and not trusted:
                return _reject("junk", _JUNK_MSG)
            if seg in STUB_WORDS or seg in extra_stop or seg in FAKE_SURNAMES:
                return _reject("stub", "Это похоже на заглушку. Напишите свои ФИО.")
            if _bad_word(seg, extra_bad):
                return _reject("bad", "Пожалуйста, укажите настоящие ФИО без шуток.")
            if seg in NON_NAME_WORDS and seg not in SURNAME_COMMON_WORDS_OK:
                return _reject("nonname", "Это обычное слово, а не фамилия или имя. Введите настоящие ФИО.")
            if not trusted and _junk_code(seg):
                return _reject("junk", _JUNK_MSG)
            if trusted:
                continue
            if any(bg in seg for bg in REVIEW_BIGRAMS):
                flags.append("bigram")
            if _max_cons_run(seg) >= 5:
                flags.append("consonants")
    if len(set(folded_words)) < len(folded_words):
        return _reject("junk", "Слова в ФИО повторяются. Проверьте и введите заново.")
    # ругательство, разбитое пробелом («Ху Йов»): склеиваем только соседние слова, из которых одно короче 4 букв
    for a, b in zip(folded_words, folded_words[1:]):
        if min(len(a), len(b)) <= 3 and any(stem in _collapse(a + b) or stem in a + b for stem in _STRONG_STEMS):
            return _reject("bad", "Пожалуйста, укажите настоящие ФИО без шуток.")
    phrase = " ".join(folded_words)
    if phrase in STUB_PHRASES:
        return _reject("stub", "Это похоже на пример из подсказки. Напишите свои ФИО.")

    # известные люди и вымышленные персонажи (в любом порядке слов, с допуском на опечатку)
    if _celebrity_hit(folded_words):
        common = any(k in COMMON_SURNAMES for k in surname_keys(folded_words[0]))
        if common and len(pieces) == 3:
            flags.append("celebrity_namesake")  # Медведев Дмитрий Сергеевич: возможно, настоящий тёзка
        else:
            return _reject("celebrity", "Нельзя использовать ФИО известных людей и персонажей. Введите свои ФИО.")
    if any(k in CELEBRITY_SURNAMES for w in folded_words[:1] for k in surname_keys(w)):
        flags.append("celebrity_surname")

    # порядок слов: «Иван Иванович Иванов» (имя-отчество-фамилия) -> просим переставить
    w0 = folded_words[0]
    if (w0 in GIVEN_NAMES and w0 not in NAME_AND_SURNAME and not _known_surname_seg(w0, ctx)
            and (folded_words[1] in GIVEN_NAMES or (len(pieces) == 3 and is_patronymic(pieces[2])))):
        return _reject("order", "Проверьте порядок слов: сначала Фамилия, потом Имя и Отчество.")
    if len(pieces) == 3:
        w0p, w1p, w2p = pieces
        if is_patronymic(w1p) and not is_patronymic(w2p) and not is_patronymic(w0p):
            return _reject("order", "Проверьте порядок: Фамилия Имя Отчество.")
        if not is_patronymic(w2p):
            flags.append("patronymic")
    else:
        flags.append("no_patronymic")
        if is_patronymic(pieces[1]) and not is_patronymic(pieces[0]):
            return _reject("order", "Похоже, вы написали Имя и Отчество. Нужно: Фамилия Имя Отчество.")

    # род фамилии, имени и отчества должен согласоваться
    genders = {g for g in (_surname_gender(pieces[0]), _name_gender(pieces[1]),
                           _patr_gender(pieces[2]) if len(pieces) == 3 else None) if g}
    if len(genders) > 1:
        return _reject("gender", "Окончания фамилии, имени и отчества не согласуются "
                                 "(например, мужское имя и женское отчество). Проверьте ФИО.")

    name_known = folded_words[1] in GIVEN_NAMES
    if not name_known:
        flags.append("name_unknown")
    patr_known = False
    if len(pieces) == 3 and is_patronymic(pieces[2]):
        patr_known = patronymic_known(pieces[2])
        if not patr_known:
            flags.append("patr_unknown")
    evidence = surname_evidence(pieces[0], ctx)
    if evidence == "unknown":
        flags.append("surname_unknown")
    elif evidence == "pattern" and ctx and ctx.require_known_surname:
        flags.append("surname_pattern")
    if _staff_match(folded_words, ctx):
        flags.append("staff_match")

    fio = " ".join(_capitalize(p) if " " not in p else
                   " ".join(_capitalize(x) for x in p.split(" ")) for p in pieces)
    reasons = tuple(sorted(set(flags)))
    surname_ok = evidence == "known" or (evidence == "pattern" and not (ctx and ctx.require_known_surname))
    confident = not flags and name_known and patr_known and len(pieces) == 3 and surname_ok
    if flags and strict:
        return FioResult("review", fio, ",".join(reasons), "", reasons, False)
    return FioResult("ok", fio, "", "", reasons, confident)


def short_name(fio: str | None) -> str:
    """Иванов Иван Иванович -> Иванов И. И."""
    if not fio:
        return "аноним"
    parts = fio.split()
    if len(parts) == 1:
        return parts[0]
    ini = " ".join(p[0].upper() + "." for p in parts[1:] if p and p.lower() not in PARTICLES)
    return f"{parts[0]} {ini}".strip()
