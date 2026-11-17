"""Tests for rich admin broadcast keyboard construction."""
import unittest

from app.bot.logic_admin import _broadcast_markup


class BroadcastMarkupTests(unittest.TestCase):
    def test_support_rating_and_url_buttons_keep_their_actions(self):
        markup = _broadcast_markup({
            "buttons": [
                {"text": "Поддержка", "action": "support"},
                {"text": "Рейтинг", "action": "rating"},
                {"text": "Сайт", "url": "https://example.com"},
            ]
        })
        self.assertEqual(len(markup), 3)
        self.assertEqual(markup[0][0].data, "bc:support")
        self.assertEqual(markup[1][0].data, "bc:rating")
        self.assertEqual(markup[2][0].url, "https://example.com")

    def test_only_eight_buttons_are_rendered(self):
        markup = _broadcast_markup({
            "buttons": [{"text": str(i), "url": f"https://example.com/{i}"} for i in range(12)]
        })
        self.assertEqual(len(markup), 8)

    def test_empty_keyboard_is_none(self):
        self.assertIsNone(_broadcast_markup({"buttons": []}))


if __name__ == "__main__":
    unittest.main()
