"""Проверка ФИО при регистрации.

Задача: отсеять мусор, заглушки, шаблоны и оскорбления и пропустить правдоподобные ФИО.
Бот НЕ может доказать, что человек носит именно эти ФИО (списков групп нет),
поэтому проверяется правдоподобие, а не подлинность.

Вердикты: ``ok`` - принять, ``review`` - принять, но отправить на проверку админу,
``reject`` - попросить ввести заново.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

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
BAD_CONTAINS = ("хуй", "хуе", "хуя", "пизд", "залуп", "блят", "бляд", "мудак", "мудил", "гандон", "говн",
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

COMMON_NAMES = set("""
александр алексей анатолий андрей антон аркадий арсений артем артур борис вадим валентин валерий василий виктор
виталий владимир владислав вячеслав геннадий георгий глеб григорий данил даниил денис дмитрий евгений егор
захар иван игорь илья кирилл константин лев леонид максим марат матвей михаил никита николай олег павел
петр роман ростислав руслан семен сергей станислав степан тимофей тимур федор филипп эдуард юрий ян ярослав
айдар азамат алан алишер амир арслан бахтияр бекзод динар дамир ильдар ильнур камиль марсель радик рамиль
рустам салават санжар тагир фарид эльдар эмиль расул ренат рафаэль сулейман ибрагим мухаммад магомед
абдулла абдул али ахмед исмаил умар ислам джамшед фаррух шерзод жасур нурлан ерлан асет данияр аян
александра алена алина алиса алла анастасия ангелина анна антонина арина валентина валерия варвара вера
вероника виктория галина дарья диана евгения екатерина елена елизавета жанна зоя инна ирина карина кира
кристина ксения лариса лидия лилия любовь людмила маргарита марина мария милена надежда наталья нина оксана
олеся ольга полина раиса регина светлана снежана софия софья таисия тамара татьяна ульяна юлия яна ярослава
айгуль алсу альбина амина аида асель аэлита гульназ гульнара гузель динара диляра зарина земфира зульфия
ильмира камилла лейла лиана малика мадина назира регина рузиль румия сабина самира сания фатима хадижа
чулпан эльвира эльмира элина юлдуз язгуль залина мариям марьям айлин айше асия венера лилиана ляйсан
вениамин герман давид демид дан эрик марк тихон макар платон мирон назар ефим савелий прохор лука гордей
всеволод святослав мстислав богдан радомир тарас остап назарий кузьма трофим клим добрыня емельян мефодий
""".split())

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


def _fold(s: str) -> str:
    return s.lower().replace("ё", "е")


def is_patronymic(word: str) -> bool:
    w = _fold(word)
    return any(w.endswith(sfx) for sfx in PATR_SUFFIXES)


def _capitalize(piece: str) -> str:
    if piece in PARTICLES:
        return piece
    return re.sub(r"[а-яё]+", lambda m: m.group(0).capitalize(), piece.lower())


def _bad_word(seg: str, extra_bad: frozenset[str]) -> bool:
    if seg in SAFE_SURNAMES:
        return False
    if seg in BAD_WHOLE:
        return True
    for stem in BAD_CONTAINS:
        if stem in seg:
            return True
    for stem in BAD_PREFIX_STEMS:
        for p in BAD_PREFIXES:
            if seg.startswith(p + stem):
                return True
    return any(b and b in seg for b in extra_bad)


def _reject(code: str, message: str) -> FioResult:
    return FioResult("reject", "", code, message)


def validate_fio(raw: str, extra_stop: frozenset[str] = frozenset(), extra_bad: frozenset[str] = frozenset(),
                 strict: bool = True) -> FioResult:
    """strict=True: сомнительные случаи уходят на проверку (review); strict=False: принимаются сразу."""
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
    for piece in pieces:
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
            if _REPEAT_RE.search(seg):
                return _reject("junk", "Похоже на случайный набор букв. Введите настоящие ФИО.")
            if not (set(seg) & VOWELS):
                return _reject("junk", "Похоже на случайный набор букв. Введите настоящие ФИО.")
            if seg[0] in "ьъы":
                return _reject("junk", "Слово не может начинаться с этой буквы. Проверьте ФИО.")
            if any(bg in seg for bg in KB_BAD_BIGRAMS):
                return _reject("junk", "Похоже на случайный набор букв. Введите настоящие ФИО.")
            if any(k in seg for k in KEYBOARD_JUNK):
                return _reject("junk", "Похоже на случайный набор букв. Введите настоящие ФИО.")
            if seg in STUB_WORDS or seg in extra_stop:
                return _reject("stub", "Это похоже на заглушку. Напишите свои ФИО.")
            if _bad_word(seg, extra_bad):
                return _reject("bad", "Пожалуйста, укажите настоящие ФИО без шуток.")
            if any(bg in seg for bg in REVIEW_BIGRAMS):
                flags.append("bigram")
            run = 0
            for ch in seg:
                run = run + 1 if ch in CONS_NO_SIGN else 0
                if run >= 5:
                    flags.append("consonants")
                    break
    if len(set(folded_words)) < len(folded_words):
        return _reject("junk", "Слова в ФИО повторяются. Проверьте и введите заново.")
    phrase = " ".join(folded_words)
    if phrase in STUB_PHRASES:
        return _reject("stub", "Это похоже на пример из подсказки. Напишите свои ФИО.")

    # порядок слов: «Иван Иванович Иванов» (имя-отчество-фамилия) -> просим переставить
    if len(pieces) == 3:
        w0, w1, w2 = pieces
        if is_patronymic(w1) and not is_patronymic(w2) and not is_patronymic(w0):
            return _reject("order", "Проверьте порядок: Фамилия Имя Отчество.")
        if not is_patronymic(w2):
            flags.append("patronymic")
    else:
        if folded_words[1] not in COMMON_NAMES:
            flags.append("name")
        if is_patronymic(pieces[1]) and not is_patronymic(pieces[0]):
            return _reject("order", "Похоже, вы написали Имя и Отчество. Нужно: Фамилия Имя Отчество.")

    fio = " ".join(_capitalize(p) if " " not in p else
                   " ".join(_capitalize(x) for x in p.split(" ")) for p in pieces)
    if flags and strict:
        return FioResult("review", fio, ",".join(sorted(set(flags))), "")
    return FioResult("ok", fio, "", "")


def short_name(fio: str | None) -> str:
    """Иванов Иван Иванович -> Иванов И. И."""
    if not fio:
        return "аноним"
    parts = fio.split()
    if len(parts) == 1:
        return parts[0]
    ini = " ".join(p[0].upper() + "." for p in parts[1:] if p and p.lower() not in PARTICLES)
    return f"{parts[0]} {ini}".strip()
