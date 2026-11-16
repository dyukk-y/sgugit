import unittest

from aiogram.exceptions import TelegramAPIError

from app.bot import background
from app.db.core import Database
from app.db.repo import Repo
from app.db.schema import migrate


class TemporaryTelegramError(TelegramAPIError):
    def __init__(self):
        Exception.__init__(self, "temporary Telegram failure")


class FakeBot:
    def __init__(self):
        self.fail_delete = True
        self.fail_unpin = True

    async def delete_message(self, chat_id, message_id):
        if self.fail_delete:
            raise TemporaryTelegramError()

    async def unpin_chat_message(self, chat_id, message_id):
        if self.fail_unpin:
            raise TemporaryTelegramError()


class FakeApp:
    def __init__(self, repo, bot):
        self.repo = repo
        self.bot = bot


class BackgroundCleanupRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        await self.db.connect()
        await migrate(self.db)
        self.repo = Repo(self.db)
        self.bot = FakeBot()
        self.app = FakeApp(self.repo, self.bot)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_scheduled_deletion_retries_temporary_api_error(self):
        await self.db.execute(
            "INSERT INTO scheduled_deletions (chat_id, message_id, delete_at) "
            "VALUES (?, ?, ?)",
            -100123, 77, 900,
        )

        await background.process_scheduled_deletions(self.app, now=1000)

        row = await self.db.fetchone(
            "SELECT delete_at FROM scheduled_deletions WHERE chat_id = ? AND message_id = ?",
            -100123, 77,
        )
        self.assertEqual(row["delete_at"], 1000 + background.CLEANUP_RETRY_SEC)

        self.bot.fail_delete = False
        await background.process_scheduled_deletions(
            self.app, now=1000 + background.CLEANUP_RETRY_SEC
        )
        self.assertIsNone(await self.db.fetchone(
            "SELECT id FROM scheduled_deletions WHERE chat_id = ? AND message_id = ?",
            -100123, 77,
        ))

    async def test_unpin_retries_temporary_api_error(self):
        await self.repo.add_pin(-100124, 78, 900)

        await background.process_due_pins(self.app, now=1000)

        row = await self.db.fetchone(
            "SELECT unpin_at FROM pinned_messages WHERE chat_id = ? AND message_id = ?",
            -100124, 78,
        )
        self.assertEqual(row["unpin_at"], 1000 + background.CLEANUP_RETRY_SEC)

        self.bot.fail_unpin = False
        await background.process_due_pins(
            self.app, now=1000 + background.CLEANUP_RETRY_SEC
        )
        self.assertIsNone(await self.db.fetchone(
            "SELECT id FROM pinned_messages WHERE chat_id = ? AND message_id = ?",
            -100124, 78,
        ))


if __name__ == "__main__":
    unittest.main()
