import asyncio, unittest
from datetime import datetime, timedelta
from app import timeutil as tu
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo
from app.models import LessonRec
from app.services.notifier import Notifier

def at(h, m, day=14): return datetime(2026, 10, day, h, m, tzinfo=tu.tz())
def L(day, num, subj, start, end): return LessonRec("ИС-11", day, num, start, end, subj, "Иванов И. И.", "310", "лекция")

class T(unittest.TestCase):
    def test_all(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); r = Repo(db); await r.load_settings()
            await r.apply_lessons([L("2026-10-14", 1, "Математика", "08:30", "10:05"), L("2026-10-14", 2, "Физика", "10:15", "11:50"),
                                   L("2026-10-14", 3, "История", "14:00", "15:35"), L("2026-10-15", 1, "Химия", "08:30", "10:05")], manual=False)
            g = (await r.search_groups("ис11"))[0]["id"]
            for uid in (1, 2, 3):
                await r.ensure_user(uid); await r.update_user(uid, group_id=g)
            await r.update_user(2, n_evening=0, n_before=30)
            await r.update_user(3, bot_blocked=1)
            await r.upsert_chat(-5, "чат", g, 1); await r.update_chat(-5, evening_on=1)
            sent = []
            async def send(cid, screen): sent.append((cid, screen.text))
            n = Notifier(r, send)
            await n.tick(at(19, 59)); self.assertEqual(sent, [])
            await n.tick(at(20, 0))
            self.assertEqual(sorted(c for c, _ in sent), [-5, 1]); self.assertIn("Химия", sent[0][1]); self.assertIn("завтра", sent[0][1].lower())
            sent.clear(); await n.tick(at(20, 1)); self.assertEqual(sent, [])  # без дублей
            await n.tick(at(23, 30)); self.assertEqual(sent, [])               # не догоняем слишком поздно
            # напоминания: у пользователя 2 за 30 минут
            await n.tick(at(7, 59)); self.assertEqual(sent, [])                 # ещё рано: до пары 31 минута
            await n.tick(at(8, 5)); self.assertEqual([c for c, _ in sent], [2]); self.assertIn("Математика", sent[0][1])
            sent.clear(); await n.tick(at(8, 6)); self.assertEqual(sent, [])
            await n.tick(at(9, 50)); self.assertEqual(sent, [])                # Физика сразу после Математики: без напоминания
            await n.tick(at(13, 40)); self.assertEqual([c for c, _ in sent], [2]); self.assertIn("История", sent[0][1])
            # изменения
            sent.clear()
            fut = tu.iso(tu.today() + timedelta(days=3))
            await r.apply_lessons([L(fut, 1, "Химия", "08:30", "10:05")], manual=False)
            res = await r.apply_lessons([L(fut, 1, "Химия", "09:00", "10:35")], manual=False)
            cnt = await n.notify_changes(res); self.assertEqual(cnt, 3); self.assertTrue(any("Изменения" in t for _, t in sent))
            self.assertNotIn(3, [c for c, _ in sent]); self.assertIn(-5, [c for c, _ in sent])
            await db.close()
        asyncio.run(go())
if __name__ == "__main__":
    unittest.main()
