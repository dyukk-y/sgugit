"""Tests for confirmed delivery through the Telegram sender queue."""
import asyncio
import unittest

from app.bot.core import Screen
from app.bot.tg import Sender


class FakeRepo:
    def __init__(self):
        self.unreachable = []

    async def update_user(self, uid, **values):
        self.unreachable.append((uid, values))

    async def update_chat(self, chat_id, **values):
        self.unreachable.append((chat_id, values))


class FakeBot:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def send_message(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("temporary Telegram failure")
        self.calls.append((args, kwargs))


class SenderDeliveryTests(unittest.TestCase):
    def test_confirmed_send_reports_actual_delivery_result(self):
        async def go():
            bot = FakeBot()
            repo = FakeRepo()
            sender = Sender(bot, repo, rate=1000)
            sender.start()
            self.assertTrue(await sender.send_confirmed(100, Screen("delivered")))
            bot.fail = True
            self.assertFalse(await sender.send_confirmed(100, Screen("not delivered")))
            self.assertEqual(len(bot.calls), 1)
            await sender.stop()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
