from app.bot.logic_hw import _normalize_assignment_text


def test_assignment_text_normalizes_punctuation_and_spacing():
    assert _normalize_assignment_text("Решить № 5, стр. 24!") == _normalize_assignment_text(
        "Решить №5 стр 24"
    )


def test_assignment_text_normalizes_yo_and_case():
    assert _normalize_assignment_text("Подготовить отчёт") == _normalize_assignment_text(
        "ПОДГОТОВИТЬ ОТЧЕТ"
    )
