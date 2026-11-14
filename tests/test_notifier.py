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
            rich_flags = []
            async def send(cid, screen):
                sent.append((cid, screen.text))
                rich_flags.append(screen.rich)
            n = Notifier(r, send)
            await n.tick(at(19, 59)); self.assertEqual(sent, [])
            await n.tick(at(20, 0))
            self.assertEqual(sorted(c for c, _ in sent), [-5, 1]); self.assertIn("Химия", sent[0][1]); self.assertIn("завтра", sent[0][1].lower())
            self.assertEqual(rich_flags, [True, True])  # обе вечерние сводки используют Rich Messages
            sent.clear(); await n.tick(at(20, 1)); self.assertEqual(sent, [])  # без дублей
            await n.tick(at(23, 30)); self.assertEqual(sent, [])               # не догоняем слишком поздно
            # напоминания: у пользователя 2 за 30 минут
            await n.tick(at(7, 59)); self.assertEqual(sent, [])                 # ещё рано: до пары 31 минута
            await n.tick(at(8, 5)); self.assertEqual([c for c, _ in sent], [2]); self.assertIn("Математика", sent[0][1]); self.assertTrue(rich_flags[-1])
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
            sent.clear()
            duplicate_cnt = await n.notify_changes(res)
            self.assertEqual(duplicate_cnt, 0)
            self.assertEqual(sent, [])  # повторная обработка того же изменения не дублирует рассылку

            # Если Telegram временно недоступен, ключ доставки не должен фиксироваться заранее.
            failed_once = False
            retry_sent = []
            async def flaky_send(cid, screen):
                nonlocal failed_once
                if not failed_once:
                    failed_once = True
                    raise RuntimeError("temporary Telegram failure")
                retry_sent.append((cid, screen.text))

            retry_notifier = Notifier(r, flaky_send)
            await r.apply_lessons([L(fut, 1, "Химия", "09:30", "11:05")], manual=False)
            retry_result = await r.apply_lessons([L(fut, 1, "Химия", "10:00", "11:35")], manual=False)
            with self.assertRaises(RuntimeError):
                await retry_notifier.notify_changes(retry_result)
            retry_count = await retry_notifier.notify_changes(retry_result)
            self.assertEqual(retry_count, 3)
            self.assertEqual(len(retry_sent), 3)
            await db.close()
        asyncio.run(go())
class StudentReminderReliability(unittest.TestCase):
    def test_cancelled_lesson_does_not_trigger_reminder(self):
        async def go():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()
            group = await repo.get_or_create_group("ИС-11")
            await repo.ensure_user(90)
            await repo.update_user(90, group_id=group["id"], n_enabled=1, n_before=30)
            async def cancelled_lessons(gid, day):
                return [{
                    "id": 900, "day": day, "num": 1, "start_t": "08:30", "end_t": "10:05",
                    "subgroup": None, "cancelled": True, "subject": "Математика",
                }]
            repo.lessons_day = cancelled_lessons
            sent = []
            async def send(uid, screen):
                sent.append((uid, screen))
            await Notifier(repo, send)._before_lesson(at(8, 0))
            self.assertEqual(sent, [])
            await db.close()
        asyncio.run(go())

    def test_failed_delivery_is_not_marked_and_is_retried(self):
        async def go():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()
            await repo.apply_lessons([L("2026-10-14", 1, "Математика", "08:30", "10:05")], manual=False)
            group = (await repo.search_groups("ис11"))[0]["id"]
            await repo.ensure_user(91)
            await repo.update_user(91, group_id=group, n_enabled=1, n_before=30)
            attempts = 0
            sent = []
            async def send(uid, screen):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return False
                sent.append((uid, screen))
                return True
            notifier = Notifier(repo, send)
            await notifier._before_lesson(at(8, 5))
            key = "bl:91:1"
            self.assertIsNone(await repo.db.fetchone("SELECT 1 FROM notif_log WHERE k = ?", key))
            await notifier._before_lesson(at(8, 5))
            self.assertEqual(attempts, 2)
            self.assertEqual(len(sent), 1)
            self.assertIsNotNone(await repo.db.fetchone("SELECT 1 FROM notif_log WHERE k = ?", key))
            self.assertTrue(sent[0][1].rich)
            await db.close()
        asyncio.run(go())


class TeacherNotifications(unittest.TestCase):
    def test_teacher_evening_and_before_lesson_notifications(self):
        async def go():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()
            await repo.apply_lessons([
                L("2026-10-14", 1, "Математика", "08:30", "10:05"),
                L("2026-10-15", 1, "Физика", "09:00", "10:35"),
            ], manual=False)
            teacher_id = (await repo.search_teachers("Иванов", limit=10))[0]["id"]
            await repo.ensure_user(77)
            await repo.set_teacher_account(77, teacher_id)
            await repo.update_user(77, n_enabled=1, n_evening=1, n_evening_time="20:00", n_before=30, n_changes=1)
            sent = []
            async def send(uid, screen):
                sent.append((uid, screen))
            notifier = Notifier(repo, send)

            await notifier.tick(at(8, 0))
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0], 77)
            self.assertIn("До вашей пары", sent[0][1].text)
            self.assertIn("Математика", sent[0][1].text)
            self.assertTrue(sent[0][1].rich)
            self.assertEqual(sent[0][1].kb[0][0].data, "p:day:2026-10-14")

            sent.clear()
            await notifier.tick(at(20, 0))
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0], 77)
            self.assertIn("Ваше расписание на завтра", sent[0][1].text)
            self.assertIn("Физика", sent[0][1].text)
            self.assertTrue(sent[0][1].rich)
            self.assertEqual(sent[0][1].kb[0][0].data, "p:day:tom")

            sent.clear()
            await notifier.tick(at(20, 1))
            self.assertEqual(sent, [])
            await db.close()
        asyncio.run(go())

    def test_teacher_receives_relevant_schedule_change_alert(self):
        async def go():
            db = Database("sqlite:///:memory:")
            await db.connect()
            await migrate(db)
            repo = Repo(db)
            await repo.load_settings()
            day = tu.iso(tu.today() + timedelta(days=3))
            await repo.apply_lessons([L(day, 1, "Математика", "08:30", "10:05")], manual=False)
            teacher_id = (await repo.search_teachers("Иванов", limit=10))[0]["id"]
            await repo.ensure_user(78)
            await repo.set_teacher_account(78, teacher_id)
            await repo.update_user(78, n_enabled=1, n_changes=1)
            await repo.apply_lessons([L(day, 1, "Математика", "09:00", "10:35")], manual=False)
            result = await repo.apply_lessons([L(day, 1, "Математика", "09:30", "11:05")], manual=False)
            sent = []
            async def send(uid, screen):
                sent.append((uid, screen))
            count = await Notifier(repo, send).notify_changes(result)
            self.assertEqual(count, 1)
            self.assertEqual(sent[0][0], 78)
            self.assertIn("ваших занятий", sent[0][1].text)
            self.assertTrue(sent[0][1].rich)
            await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
