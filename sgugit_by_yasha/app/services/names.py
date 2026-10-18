"""Работа с фамилиями и инициалами преподавателей."""
from __future__ import annotations


def name_parts(name: str) -> tuple[str, str]:
    """('иванов', 'ии') из «Иванов Иван Иванович», «Иванов И. И.», «Иванов И.И.» и «Иванов ИИ»."""
    orig = (name or "").replace(".", " ").split()
    if not orig:
        return "", ""
    toks = [t.lower().replace("ё", "е") for t in orig]
    surname, rest = toks[0], toks[1:]
    if len(orig) == 2 and orig[1].isupper() and 2 <= len(orig[1]) <= 3:
        initials = rest[0]
    elif rest and all(len(t) == 1 for t in rest):
        initials = "".join(rest)
    else:
        initials = "".join(t[0] for t in rest)
    return surname, initials


def same_person(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Фамилии совпадают, инициалы не противоречат (пустые инициалы подходят к любым)."""
    if not a[0] or a[0] != b[0]:
        return False
    ia, ib = a[1], b[1]
    return not ia or not ib or ia.startswith(ib) or ib.startswith(ia)


def surname_close(s: str, t: str) -> bool:
    """Совпадение фамилии с учётом падежа: Крылов / Крылова / Крылову."""
    if s == t:
        return True
    n = min(len(s), len(t))
    if n < 4 or abs(len(s) - len(t)) > 3:
        return False
    cp = 0
    for x, y in zip(s, t):
        if x != y:
            break
        cp += 1
    return cp >= max(4, n - 1)
