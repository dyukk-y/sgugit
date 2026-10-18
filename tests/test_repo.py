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

    def test_users_groups(self):
        async def go():
            db, r = await mk()
            u = await r.touch_user(5, "@Ann", "Anna"); self.assertEqual(u["username"], "Ann")
            await r.update_user(5, fio="Петрова Анна Сергеевна", fio_status="verified")
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
            self.assertEqual((await r.rate_teacher(1, tid, 3, 7))[0], "cooldown")
            await r.rate_teacher(2, tid, 3, 7)
            t = await r.get_teacher(tid); self.assertEqual(t["cnt"], 2); self.assertAlmostEqual(t["avg"], 4.0)
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
if __name__ == "__main__":
    unittest.main()
