import asyncio, unittest
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo
from app.bot import logic_chat as lc

class T(unittest.TestCase):
    def test_all(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); r = Repo(db); await r.load_settings()
            g = await r.get_or_create_group("ИС-11")
            chat = await r.upsert_chat(-7, "Чат", None, 5)
            u5 = await r.ensure_user(5); u6 = await r.ensure_user(6)
            self.assertTrue(lc.can_manage(u5, chat, 1)); self.assertFalse(lc.can_manage(u6, chat, 1)); self.assertTrue(lc.can_manage(u6, chat, 1, tg_admin=True))
            self.assertIn("не привязана", (await lc.screen(r, chat)).text)
            self.assertIn("зарегистрируйтесь", await lc.apply(r, chat, u5, "grp"))
            await r.update_user(5, group_id=g["id"]); u5 = await r.get_user(5)
            self.assertIsNone(await lc.apply(r, chat, u5, "grp")); chat = await r.get_chat(-7); self.assertEqual(chat["group_id"], g["id"])
            self.assertIn("ИС-11", (await lc.screen(r, chat)).text)
            for act, field, seq in (("sm", "smart_mode", ["keywords", "active", "off", "mention"]), ("wt", "wait_min", [120, 15, 30, 60]), ("ad", "autodelete_min", [15, 60, 0, 1, 5]), ("et", "evening_time", ["21:00", "22:00", "19:00", "20:00"])):
                for want in seq:
                    await lc.apply(r, chat, u5, act); chat = await r.get_chat(-7); self.assertEqual(chat[field], want)
            await lc.apply(r, chat, u5, "ev"); chat = await r.get_chat(-7); self.assertEqual(chat["evening_on"], 1)
            u7 = await r.ensure_user(7); await r.update_user(7, role="head", group_id=g["id"]); u7 = await r.get_user(7)
            self.assertTrue(lc.can_manage(u7, chat, 1))
            await db.close()
        asyncio.run(go())
if __name__ == "__main__":
    unittest.main()
