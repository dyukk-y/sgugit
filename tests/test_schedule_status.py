"""Тесты выделения текущей и следующей пары."""
import unittest
from datetime import datetime

from app.bot.logic_schedule import _schedule_status_line


class ScheduleStatusTests(unittest.TestCase):
    def test_current_lesson_is_highlighted(self):
        lesson = {"subject": "Математика", "start_t": "08:00", "end_t": "09:30"}
        result = _schedule_status_line([lesson], datetime(2026, 11, 13, 8, 45))
        self.assertIn("Сейчас идёт", result)
        self.assertIn("Математика", result)

    def test_upcoming_lesson_is_highlighted(self):
        lesson = {"subject": "Физика", "start_t": "10:00", "end_t": "11:30"}
        result = _schedule_status_line([lesson], datetime(2026, 11, 13, 9, 0))
        self.assertIn("Следующая", result)
        self.assertIn("10:00", result)

    def test_no_future_lesson_has_no_status(self):
        lesson = {"subject": "История", "start_t": "08:00", "end_t": "09:00"}
        self.assertIsNone(_schedule_status_line([lesson], datetime(2026, 11, 13, 10, 0)))


if __name__ == "__main__":
    unittest.main()
