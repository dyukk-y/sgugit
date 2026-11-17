"""Delivery/retry tests for scheduled group-chat answers with real aiogram types."""
import asyncio
import unittest
from types import SimpleNamespace

from aiogram.exceptions import TelegramAPIError

from app.bot import tg
from app.services.questions import QuestionService
from tests.test_questions_find import CFG, NOW, setup


class FlakyBot:
    def __init__(self):
        self.fail = True
        self.sent = 0

    async def send_message(self, chat_id, text, reply_parameters=None):
        if self.fail:
            raise TelegramAPIError("temporary Telegram failure")
        self.sent += 1
        return SimpleNamespace(message_id=500)


class GroupQuestionDeliveryTests(unittest.TestCase):
    def test_failed_delivery_is_retried_and_success_is_final(self):
        async def go():
            db, repo = await setup()
            group = (await repo.search_groups("ис11"))[0]
            chat = await repo.upsert_chat(-900, "ИС-11", group["id"], 1)
            await repo.update_chat(-900, smart_mode="active", wait_min=1, autodelete_min=0)
            chat = await repo.get_chat(-900)
            questions = QuestionService(repo, CFG)
            self.assertTrue(await questions.consider(
                chat, 10, 100, "а завтра будет мгп?", now_ts=1_000_000, now_dt=NOW
            ))
            await repo.db.execute("UPDATE pending_questions SET due_at = 1 WHERE message_id = 100")

            bot = FlakyBot()
            app = tg.App(
                bot=bot, repo=repo, cfg=CFG, sender=tg.Sender(bot, repo),
                services={}, username="sgugit_bot", questions=questions,
            )
            self.assertEqual(await tg.answer_due_questions(app), 0)
            pending = await repo.db.fetchone("SELECT * FROM pending_questions WHERE message_id = 100")
            self.assertEqual(pending["status"], "wait")
            self.assertGreater(pending["due_at"], 1_000_000)

            bot.fail = False
            await repo.db.execute("UPDATE pending_questions SET due_at = 1 WHERE message_id = 100")
            self.assertEqual(await tg.answer_due_questions(app), 1)
            self.assertEqual(bot.sent, 1)
            pending = await repo.db.fetchone("SELECT * FROM pending_questions WHERE message_id = 100")
            self.assertEqual(pending["status"], "sent")
            await db.close()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
