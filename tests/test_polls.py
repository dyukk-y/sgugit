"""Тесты формата учительских опросов."""
import unittest

from app.bot.polls import parse_poll_spec


class PollParserTests(unittest.TestCase):
    def test_valid_poll(self):
        self.assertEqual(parse_poll_spec("Куда идём? | В корпус | Онлайн"),
                         ("Куда идём?", ["В корпус", "Онлайн"]))

    def test_requires_two_to_ten_options(self):
        self.assertIsNone(parse_poll_spec("Вопрос | один"))
        self.assertIsNone(parse_poll_spec("Вопрос | " + " | ".join(str(i) for i in range(11))))

    def test_rejects_empty_and_long_fields(self):
        self.assertIsNone(parse_poll_spec(" | один | два"))
        self.assertIsNone(parse_poll_spec("Вопрос | один | "))
        self.assertIsNone(parse_poll_spec("В" * 301 + " | один | два"))
        self.assertIsNone(parse_poll_spec("Вопрос | " + "а" * 101 + " | два"))


if __name__ == "__main__":
    unittest.main()
