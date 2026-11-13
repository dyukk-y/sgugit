import asyncio
import unittest

from app.db.core import Database
from app.db.repo import Repo
from app.db.schema import migrate
from app.models import LessonRec
from app.services.sync import SyncService


class SyncNotificationRetryTests(unittest.TestCase):
    def test_failed_change_notification_is_retried_on_next_sync(self):
        async def run():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()

            old = LessonRec("ИС-11", "2026-11-16", 1, "08:30", "10:05", "Математика")
            new = LessonRec("ИС-11", "2026-11-16", 1, "09:00", "10:35", "Математика")
            await repo.apply_lessons([old], manual=False)

            attempts = 0
            delivered = []

            async def fetcher():
                return [new]

            async def on_changes(result):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary Telegram failure")
                delivered.append(result.event_id)

            service = SyncService(repo, fetcher, on_changes=on_changes)
            first = await service.run_once()
            self.assertTrue(first.ok)
            self.assertEqual(attempts, 1)
            self.assertEqual(delivered, [])

            second = await service.run_once()
            self.assertTrue(second.ok)
            self.assertEqual(attempts, 2)
            self.assertEqual(len(delivered), 1)

            await db.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
