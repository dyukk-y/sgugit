import asyncio
import unittest
from datetime import datetime

from app import timeutil as tu
from app.bot.core import Ctx
from app.bot.logic_schedule import day_screen
from app.config import Settings
from app.db.core import Database
from app.db.repo import Repo
from app.db.schema import migrate
from app.models import LessonRec
from app.services.sync import SyncService


class LazyScheduleTests(unittest.TestCase):
    def test_empty_group_cache_triggers_fetch_and_displays_lessons(self):
        async def go():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()
            group = await repo.get_or_create_group("ИС-11")
            user = await repo.touch_user(12345, "test_user", "Test User")
            await repo.update_user(12345, group_id=group["id"])
            user["group_id"] = group["id"]
            cfg = Settings("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "https://sgugit.ru/raspisanie", 30, "/tmp/bk", "INFO")
            day = "2026-10-19"
            async def fetch():
                return [LessonRec("ИС-11", day, 1, "08:30", "10:00", "Геодезия", "Иванов И. И.", "227", "лекция")]
            sync = SyncService(repo, fetch)
            ctx = Ctx(repo, cfg, user, now=datetime(2026, 10, 19, 7, 0, tzinfo=tu.tz()))
            ctx.services["sync"] = sync
            screen = await day_screen(ctx, "today")
            assert "Геодезия" in screen.text
            assert await repo.count("lessons", "group_id = ?", group["id"]) == 1
            await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
