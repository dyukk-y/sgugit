"""Тесты структурированного HTML расписания для Telegram Rich Messages."""
import unittest

from app.services.rich_schedule import schedule_rich_html


class RichScheduleTests(unittest.TestCase):
    def test_day_schedule_uses_expandable_lesson_cards(self):
        source = (
            "<b>Понедельник, 16 ноября</b>\n"
            "Группа ИС-11\n"
            "▶️ Сейчас идёт: <b>Математика</b> · до 10:00\n"
            "<b>01</b> · 08:30–10:00\n"
            "📘 <b>Математика</b>\n"
            "🎓 лекция · 👨‍🏫 Иванов · 📍 301"
        )
        result = schedule_rich_html(source)
        self.assertIn("<h1>Понедельник, 16 ноября</h1>", result)
        self.assertIn("<blockquote>▶️ Сейчас идёт:", result)
        self.assertIn("<details open><summary><b>01</b>", result)
        self.assertIn("📍 301", result)

    def test_week_days_are_independent_collapsible_sections(self):
        source = (
            "<b>Неделя 16.11–22.11</b>\n"
            "📅 <b>Понедельник, 16.11</b>\n"
            "<b>01</b> · 08:30–10:00\n"
            "📘 <b>Математика</b>\n"
            "🎓 лекция · 📍 301\n"
            "📅 <b>Вторник, 17.11</b> — занятий нет 🎉"
        )
        result = schedule_rich_html(source)
        self.assertIn("<h1>Неделя 16.11–22.11</h1>", result)
        self.assertIn("<details open><summary>Понедельник, 16.11</summary>", result)
        self.assertIn("<details><summary>Вторник, 17.11 — занятий нет 🎉</summary>", result)
        self.assertIn("<details open><summary><b>01</b>", result)

    def test_cancelled_and_manual_notes_are_kept(self):
        source = (
            "<b>Сегодня</b>\n"
            "<s><b>02</b> · 10:10–11:40</s>\n"
            "<s>📘 <b>Физика</b></s>\n"
            "🧪 лабораторная · 📍 204\n"
            "❌ <b>Занятие отменено</b> · по информации от студента"
        )
        result = schedule_rich_html(source)
        self.assertIn("<s><b>02</b>", result)
        self.assertIn("Занятие отменено", result)

    def test_empty_lines_are_not_emitted(self):
        self.assertEqual(schedule_rich_html("\n\n"), "")


if __name__ == "__main__":
    unittest.main()
