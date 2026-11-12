"""Тесты HTML-блоков rich-расписания."""
import unittest

from app.services.rich_schedule import schedule_rich_html


class RichScheduleTests(unittest.TestCase):
    def test_title_and_day_headings_become_rich_blocks(self):
        result = schedule_rich_html("<b>Расписание на неделю</b>\n\n📅 <b>Понедельник, 16.11</b>\n1️⃣ 08:30–10:00\n📚 <b>Математика</b>")
        self.assertIn("<h1>Расписание на неделю</h1>", result)
        self.assertIn("<h2>Понедельник, 16.11</h2>", result)
        self.assertIn("<p>1️⃣ 08:30–10:00</p>", result)
        self.assertIn("<p>📚 <b>Математика</b></p>", result)

    def test_empty_lines_are_not_emitted(self):
        self.assertEqual(schedule_rich_html("\n\n<b>Сегодня</b>\n\n"), "<h1>Сегодня</h1>")


if __name__ == "__main__":
    unittest.main()
