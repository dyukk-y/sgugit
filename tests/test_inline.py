import unittest
from datetime import date

from app.bot.tg import _parse_inline_query


class InlineQueryParsingTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 13)  # Friday

    def test_group_without_modifier_offers_choices(self):
        self.assertEqual(_parse_inline_query("ИС-11", self.today),
                         ("ИС-11", "choices", self.today))

    def test_today_and_tomorrow(self):
        self.assertEqual(_parse_inline_query("ИС-11 сегодня", self.today),
                         ("ИС-11", "day", self.today))
        self.assertEqual(_parse_inline_query("ИС-11 завтра", self.today),
                         ("ИС-11", "day", date(2026, 11, 14)))

    def test_week(self):
        self.assertEqual(_parse_inline_query("ИС-11 неделя", self.today),
                         ("ИС-11", "week", self.today))

    def test_explicit_date(self):
        self.assertEqual(_parse_inline_query("ИС-11 25.11", self.today),
                         ("ИС-11", "day", date(2026, 11, 25)))
        self.assertEqual(_parse_inline_query("ИС-11 25.11.2027", self.today),
                         ("ИС-11", "day", date(2027, 11, 25)))

    def test_weekday_resolves_to_next_occurrence(self):
        self.assertEqual(_parse_inline_query("ИС-11 пн", self.today),
                         ("ИС-11", "day", date(2026, 11, 16)))
        self.assertEqual(_parse_inline_query("ИС-11 пт", self.today),
                         ("ИС-11", "day", self.today))

    def test_unknown_last_word_is_part_of_group_query(self):
        self.assertEqual(_parse_inline_query("ИС-11 корпус", self.today),
                         ("ИС-11 корпус", "choices", self.today))


if __name__ == "__main__":
    unittest.main()
