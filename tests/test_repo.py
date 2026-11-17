import asyncio, unittest, json
from datetime import date, timedelta
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo, canonical_group_name, norm_group, teacher_key
from app.models import LessonRec
from app.timeutil import today, iso

def run(c): return asyncio.run(c)

def L(g, day, num, subj, teacher="Иванов И. И.", room="310", start="08:30", end="10:05", kind="лекция", sub=None):
    return LessonRec(g, day, num, start, end, subj, teacher, room, kind, sub)

async def mk():
    db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db)
    r = Repo(db); await r.load_settings(); return db, r

class T(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm_group("ИС-11"), norm_group("ис 11"))
        self.assertEqual(norm_group("IS-11"), norm_group("ИС11"))
        self.assertEqual(teacher_key("Иванов И.И."), teacher_key("Иванов И. И."))

    def test_canonical_group_names_are_strict(self):
        variants = ["МД-22.1", "мд22.1", "мд221", "мд-221"]
        self.assertEqual([canonical_group_name(x) for x in variants], ["МД-22.1"] * 4)
        self.assertEqual(canonical_group_name("ИС11"), "ИС-11")
        self.assertEqual([canonical_group_name(x) for x in ("Э-22.1", "э22.1", "э221", "Э 22 1", "э-221")],
                         ["Э-22.1"] * 5)
        self.assertEqual(canonical_group_name("IS-11"), "ИС-11")
        for invalid in ("МД-22.12", "МД-2", "МД-2222", "МД-22.1 пара", "МД"):
            self.assertIsNone(canonical_group_name(invalid), invalid)

    def test_group_schedule_change_can_be_decided_by_another_admin(self):
        async def go():
            db, r = await mk()
            group = await r.get_or_create_group("ИС-11")
            change_id = await r.create_group_schedule_change(
                gid=group["id"], chat_id=-100, day=iso(today() + timedelta(days=1)),
                num=1, action="cancel", subject="Математика", author_id=10,
                author_label="@student", message_id=55)
            self.assertTrue(await r.decide_group_schedule_change(change_id, 20, True))
            row = await r.get_group_schedule_change(change_id)
            self.assertEqual(row["status"], "applied")
            self.assertFalse(await r.decide_group_schedule_change(change_id, 30, False))
            await db.close()
        run(go())

    def test_users_groups(self):
        async def go():
            db, r = await mk()
            u = await r.touch_user(5, "@Ann", "Anna"); self.assertEqual(u["username"], "Ann")
            self.assertEqual(u["hw_blocked"], 0)
            await r.update_user(5, fio="Петрова Анна Сергеевна", fio_status="verified")
            await r.update_user(5, hw_blocked=1)
            self.assertTrue(await r.hw_creation_blocked(5))
            self.assertEqual((await r.find_user("@ann"))["id"], 5)
            self.assertEqual((await r.find_user("5555")), None)
            self.assertEqual(len(await r.search_users_by_fio("петрова")), 1)
            g = await r.get_or_create_group("ис-11"); g2 = await r.get_or_create_group("ИС 11")
            self.assertEqual(g["id"], g2["id"])
            await r.get_or_create_group("ГД-21")
            self.assertEqual([x["name"] for x in await r.search_groups("ис11")], ["ИС-11"])
            self.assertEqual([x["name"] for x in await r.search_groups("гд 2")], ["ГД-21"])
            self.assertEqual(len(await r.search_groups("ис-12")), 1)
            with self.assertRaises(ValueError): await r.update_user(5, evil="x")
            await db.close()
        run(go())

    def test_lessons_diff_guard(self):
        async def go():
            db, r = await mk()
            d0 = today() + timedelta(days=1); d1 = iso(d0); d2 = iso(d0 + timedelta(days=1))
            recs = [L("ИС-11", d1, 1, "Математика"), L("ИС-11", d1, 2, "Физика", "Петров П. П."), L("ИС-11", d2, 1, "История", "Сидоров С. С.; Кузнецов К. К.")]
            res = await r.apply_lessons(recs, manual=False)
            self.assertEqual(res.total, 3); self.assertEqual(res.changes, {})
            gid = (await r.search_groups("ис11"))[0]["id"]
            self.assertEqual(len(await r.lessons_day(gid, d1)), 2)
            self.assertEqual(await r.count("teachers"), 4)
            # изменение
            recs2 = [L("ИС-11", d1, 1, "Математика", room="415"), L("ИС-11", d1, 2, "Физика", "Петров П. П."), L("ИС-11", d2, 1, "История", "Сидоров С. С.; Кузнецов К. К.")]
            res = await r.apply_lessons(recs2, manual=False)
            self.assertIn(gid, res.changes); self.assertEqual(res.changes[gid][0]["day"], d1)
            self.assertEqual(len(await r.lessons_day(gid, d1)), 2)
            # повтор без изменений
            res = await r.apply_lessons(recs2, manual=False); self.assertEqual(res.changes, {})
            # ручные пары не затираются синхронизацией
            await r.add_manual_lesson(gid, L("ИС-11", d1, 3, "Консультация", "Иванов И. И."))
            await r.apply_lessons(recs2, manual=False)
            self.assertEqual(len(await r.lessons_day(gid, d1)), 3)
            # подгруппы
            await r.apply_lessons([L("ИС-11", d1, 1, "Математика", sub=1), L("ИС-11", d1, 1, "Математика", sub=2, room="1")], manual=False)
            self.assertEqual(len([x for x in await r.lessons_day(gid, d1, 1) if x["manual"] == 0]), 1)
            # защита от пустого/урезанного парсинга
            many = [L("КА-31", iso(d0 + timedelta(days=i)), 1, "Предмет") for i in range(15)]
            await r.apply_lessons(many, manual=False)
            res = await r.apply_lessons([many[0], many[14]], manual=False)
            self.assertEqual(res.skipped, ["КА-31"])
            cat = await r.subject_catalog(); self.assertTrue(any(s == "История" for _, s in cat))
            await db.close()
        run(go())

    def test_ratings_hw_requests(self):
        async def go():
            db, r = await mk()
            d1 = iso(today() + timedelta(days=1))
            await r.apply_lessons([L("ИС-11", d1, 1, "Математика", "Иванов Иван Иванович"), L("ИС-11", d1, 2, "Физика", "Петров П. П.")], manual=False)
            gid = (await r.search_groups("ис11"))[0]["id"]
            ids = await r.teacher_ids_for_group(gid); self.assertEqual(len(ids), 2)
            rows, total = await r.list_teachers(0, 6, ids); self.assertEqual(total, 2); self.assertIsNone(rows[0]["avg"])
            tid = rows[0]["id"]
            await r.ensure_user(1); await r.ensure_user(2)
            self.assertEqual(await r.rate_teacher(1, tid, 5, 7), ("ok", 0))
            self.assertEqual(await r.rate_teacher(1, tid, 5, 7), ("same", 0))
            self.assertEqual((await r.rate_teacher(1, tid, 3, 7))[0], "ok")
            await r.rate_teacher(2, tid, 3, 7)
            t = await r.get_teacher(tid); self.assertEqual(t["cnt"], 2); self.assertAlmostEqual(t["avg"], 3.0)
            self.assertEqual(len(await r.search_teachers("петров")), 1); self.assertEqual(len(await r.search_teachers("петрав")), 1)
            self.assertEqual((await r.teachers_by_subject("Физика"))[0]["name"], "Петров П. П.")
            await r.set_teacher_hidden(tid, True); rows, total = await r.list_teachers(0, 6, ids); self.assertEqual(total, 1)
            self.assertEqual(await r.reset_ratings(tid), 2)
            h = await r.add_hw(gid, "Математика", d1, "№15", None, 1, "pending")
            self.assertEqual((await r.pending_hw(gid))[1], 1)
            await r.set_hw_status(h, "approved", 9)
            rows, total = await r.list_hw(gid, iso(today()), 0, 5); self.assertEqual(total, 1)
            self.assertEqual(await r.hw_counts_for_day(gid, d1), {"Математика": 1})
            self.assertTrue(await r.toggle_hw_done(1, h)); self.assertEqual(await r.hw_done_set(1, [h]), {h})
            self.assertFalse(await r.toggle_hw_done(1, h))
            rid = await r.create_request(1, gid); self.assertTrue(await r.decide_request(rid, "rejected", 9))
            self.assertFalse(await r.decide_request(rid, "approved", 9))
            self.assertTrue(await r.first_time("k")); self.assertFalse(await r.first_time("k"))
            await db.close()
        run(go())

    def test_homework_filters_keep_overdue_until_completed(self):
        async def go():
            db, r = await mk()
            group = await r.get_or_create_group("ИС-11")
            await r.ensure_user(101)
            today_iso = iso(today())
            overdue_day = iso(today() - timedelta(days=2))
            future_day = iso(today() + timedelta(days=2))
            old = await r.add_hw(group["id"], "Математика", None, "Просроченное задание", overdue_day, 101, "approved")
            future = await r.add_hw(group["id"], "Физика", None, "Будущее задание", future_day, 101, "approved")
            self.assertTrue(await r.toggle_hw_done(101, future))

            counts = await r.hw_list_counts(group["id"], 101, today_iso)
            self.assertEqual(counts, {"total": 2, "done": 1, "active": 1, "overdue": 1})

            active, active_total = await r.list_hw(group["id"], today_iso, 0, 5, 101, "active")
            self.assertEqual(active_total, 1)
            self.assertEqual([x["id"] for x in active], [old])

            done, done_total = await r.list_hw(group["id"], today_iso, 0, 5, 101, "done")
            self.assertEqual(done_total, 1)
            self.assertEqual([x["id"] for x in done], [future])

            all_rows, all_total = await r.list_hw(group["id"], today_iso, 0, 5, 101, "all")
            self.assertEqual(all_total, 2)
            self.assertEqual({x["id"] for x in all_rows}, {old, future})
            await db.close()
        run(go())

    def test_admin_homework_stats_and_blocked_students(self):
        async def go():
            db, r = await mk()
            group = await r.get_or_create_group("ИС-11")
            await r.ensure_user(10001)
            await r.update_user(10001, group_id=group["id"], fio="Смирнова Анна Сергеевна", hw_blocked=1)
            await r.add_hw(group["id"], "Математика", None, "№15-20", None, 10001, "approved")
            await r.add_hw(group["id"], "Физика", None, "Задачи 1-3", None, 10001, "pending")
            stats = await r.admin_homework_stats()
            self.assertEqual(stats["published"], 1)
            self.assertEqual(stats["last_day"], 1)
            self.assertEqual(stats["last_week"], 1)
            self.assertEqual(stats["authors_week"], 1)
            self.assertEqual(stats["blocked_students"], 1)
            self.assertEqual(stats["legacy_pending"], 1)
            rows, total = await r.blocked_hw_users(10, 0)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["id"], 10001)
            self.assertEqual(rows[0]["group_name"], "ИС-11")
            await db.close()
        run(go())

    def test_chat_snapshot_dump(self):
        async def go():
            db, r = await mk()
            c = await r.upsert_chat(-100, "Чат", None, 5); self.assertIsNone(c["group_id"])
            g = await r.get_or_create_group("ИС-11")
            c = await r.upsert_chat(-100, "Чат2", g["id"], 5); self.assertEqual(c["group_id"], g["id"])
            await r.update_chat(-100, evening_on=1); self.assertEqual(len(await r.evening_chats()), 1)
            d1 = iso(today())
            recs = [L("ИС-11", d1, 1, "Математика")]
            self.assertTrue(await r.save_snapshot("site", recs)); self.assertFalse(await r.save_snapshot("site", recs))
            sid = (await r.list_snapshots())[0]["id"]; self.assertEqual(await r.load_snapshot(sid), recs)
            await r.apply_lessons(recs, manual=False); await r.set_setting("rating_enabled", "0")
            dump = json.loads(json.dumps(await r.dump()))
            db2, r2 = await mk()
            counts = await r2.restore(dump); self.assertEqual(counts["lessons"], 1)
            self.assertFalse(r2.flag("rating_enabled")); self.assertEqual(len(await r2.search_groups("ис11")), 1)
            self.assertFalse(await r2.is_empty())
            await db.close(); await db2.close()
        run(go())
    def test_admin_teacher_rating_management(self):
        async def go():
            db, r = await mk()
            d1 = iso(today() + timedelta(days=1))
            await r.apply_lessons([
                L("ИС-11", d1, 1, "Математика", "Иванов Иван Иванович", kind="лекция"),
                L("ИС-11", d1, 2, "Математика", "Иванов Иван Иванович", kind="практика"),
                L("ИС-11", d1, 3, "Физика", "Петров Петр Петрович", kind="лекция"),
            ], manual=False)
            teachers, total = await r.admin_teacher_list(0, 10)
            self.assertEqual(total, 2)
            ivan = next(x for x in teachers if x["name"] == "Иванов Иван Иванович")
            tid = ivan["id"]
            await r.ensure_user(101)
            await r.ensure_user(102)
            criteria = await r.teacher_rating_criteria((await r.get_teacher(tid))["norm"])
            self.assertGreaterEqual(len(criteria), 2)
            await r.save_teacher_rating_score(101, tid, criteria[0]["key"], 5)
            await r.save_teacher_rating_score(101, tid, criteria[1]["key"], 4)
            await r.rate_teacher(101, tid, 5, 0)
            await r.save_teacher_rating_score(102, tid, criteria[0]["key"], 3)
            entries, entry_total = await r.admin_teacher_rating_entries(tid, 0, 10)
            self.assertEqual(entry_total, 2)
            self.assertEqual({x["user_id"] for x in entries}, {101, 102})
            summary = await r.teacher_rating_score_summary(tid)
            self.assertEqual(sum(x["cnt"] for x in summary), 3)
            await r.save_teacher_rating_comment(101, tid, "Хорошо объясняет")
            review_rows, review_total = await r.admin_teacher_reviews(tid, 0, 5)
            self.assertEqual(review_total, 1)
            review_id = review_rows[0]["id"]
            await r.add_teacher_review_reply(review_id, 102, "Согласен")
            replies = await r.admin_teacher_review_replies(review_id, tid)
            self.assertEqual(len(replies), 1)
            self.assertTrue(await r.delete_teacher_review_reply(replies[0]["id"], review_id, tid))
            self.assertFalse(await r.delete_teacher_review_reply(replies[0]["id"], review_id, tid))
            self.assertTrue(await r.delete_teacher_review(review_id, tid))
            self.assertEqual(await db.scalar(
                "SELECT COUNT(*) FROM teacher_rating_comments WHERE teacher_id = ?", tid), 0)
            self.assertEqual(await db.scalar(
                "SELECT COUNT(*) FROM teacher_review_replies WHERE review_id = ?", review_id), 0)
            self.assertTrue(await r.delete_teacher_rating(101, tid))
            self.assertFalse(await r.delete_teacher_rating(101, tid))
            entries, entry_total = await r.admin_teacher_rating_entries(tid, 0, 10)
            self.assertEqual(entry_total, 1)
            self.assertEqual(entries[0]["user_id"], 102)
            await r.set_teacher_hidden(tid, True)
            all_rows, all_total = await r.admin_teacher_list(0, 10)
            self.assertEqual(all_total, 2)
            self.assertTrue(next(x for x in all_rows if x["id"] == tid)["hidden"])
            found, found_total = await r.admin_teacher_list(0, 10, "Иванов")
            self.assertEqual(found_total, 1)
            self.assertEqual(found[0]["id"], tid)
            await db.close()
        run(go())

if __name__ == "__main__":
    unittest.main()
