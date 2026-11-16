import asyncio
import unittest

from app import timeutil as tu
from app.bot import logic_admin
from app.bot.core import Ctx
from app.config import Settings
from app.db.core import Database
from app.db.repo import Repo
from app.db.schema import migrate


CFG = Settings(
    "x", 1, "sqlite:///:memory:", "Asia/Novosibirsk",
    "https://sgugit.ru/raspisanie", 30, "/tmp/bk", "INFO",
)


class GroupAdderCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        await self.db.connect()
        await migrate(self.db)
        self.repo = Repo(self.db)
        await self.repo.load_settings()
        self.group = await self.repo.get_or_create_group("ИС-11")
        self.ctx = Ctx(
            self.repo, CFG,
            {"id": 1, "role": "super", "group_id": None, "fio": None},
        )

    async def asyncTearDown(self):
        await self.db.close()

    async def test_group_card_shows_saved_username_and_display_name(self):
        chat_id = -100123456
        await self.repo.touch_user(555, "group_adder", "Test User")
        await self.repo.upsert_chat(chat_id, "Тестовая группа", self.group["id"], 555)
        await self.db.execute(
            "INSERT INTO analytics_events (user_id, event, detail, created_at) "
            "VALUES (?, 'group_added', ?, ?)",
            555,
            "chat_id=-100123456;title=Тестовая группа;by=555;"
            "by_username=group_adder;by_name=Test User",
            tu.now_ts(),
        )

        out = await logic_admin._group_card(self.ctx, chat_id)

        self.assertIn(
            "Кто добавил бота: <b>@group_adder · Test User",
            out.screen.text,
        )

    async def test_group_card_falls_back_to_saved_user_when_event_is_missing(self):
        chat_id = -100123457
        await self.repo.touch_user(556, "saved_adder", "Saved User")
        await self.repo.upsert_chat(chat_id, "Другая группа", self.group["id"], 556)

        out = await logic_admin._group_card(self.ctx, chat_id)

        self.assertIn("Кто добавил бота: <b>@saved_adder", out.screen.text)


if __name__ == "__main__":
    unittest.main()
