import unittest

from app.main import ALLOWED_UPDATES


class UpdateDeliveryTests(unittest.TestCase):
    def test_inline_queries_are_subscribed(self):
        self.assertIn("inline_query", ALLOWED_UPDATES)

    def test_all_router_update_types_are_subscribed(self):
        self.assertTrue({"message", "callback_query", "my_chat_member", "inline_query"}.issubset(ALLOWED_UPDATES))


if __name__ == "__main__":
    unittest.main()
