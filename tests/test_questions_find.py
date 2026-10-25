import asyncio, unittest
from datetime import datetime, timedelta
from app import timeutil as tu
from app.bot import logic_find, router
from app.bot.core import Ctx
from app.config import Settings
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo
from app.models import LessonRec
from app.services.questions import QuestionService

CFG = Settings("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "u", 30, "/tmp", "INFO")
NOW = datetime(2026, 10, 14, 10, 30, tzinfo=tu.tz())  # среда 10:30

def L(g, day, num, subj, teacher, room, start, end, kind="лекция"): return LessonRec(g, day, num, start, end, subj, teacher, room, kind)

async def setup():
    db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); r = Repo(db); await r.load_settings()
    await r.apply_lessons([
        L("ИС-11", "2026-10-14", 1, "Маркшейдерско-геодезические приборы", "Крылов А. А.", "215", "10:15", "11:50", "практика"),
        L("ИС-11", "2026-10-15", 1, "Маркшейдерско-геодезические приборы", "Крылов А. А.", "215", "10:15", "11:50", "практика"),
        L("ИС-11", "2026-10-15", 2, "Физика", "Петров П. П.", "101", "12:00", "13:35"),
        L("ГД-21", "2026-10-14", 1, "Геодезия", "Крылов А. А.", "310", "14:00", "15:35"),
        L("ГД-21", "2026-10-16", 1, "Геодезия", "Крылов Б. Б.", "311", "08:30", "10:05"),
    ], manual=False)
    await r.replace_directory([{"name": "Крылов Андрей Андреевич", "unit": "Кафедра геодезии", "url": ""},
                               {"name": "Крылов Борис Борисович", "unit": "Кафедра физики", "url": ""},
                               {"name": "Иванова Анна Ивановна", "unit": "Кафедра геодезии", "url": ""}],
                              [{"name": "Кафедра геодезии", "room": "корпус 2, каб. 215", "url": ""}, {"name": "Кафедра физики", "room": "", "url": ""}])
    return db, r

class T(unittest.TestCase):
    def test_find_teacher(self):
        async def go():
            db, r = await setup()
            ctx = Ctx(r, CFG, {"id": 5, "group_id": None, "subgroup": None, "role": "student"}, now=NOW)
            t = (await logic_find.teacher_answer(ctx, "крылов аа")).text
            self.assertIn("Сейчас ведёт пару до 11:50", t); self.assertIn("215", t); self.assertIn("Кафедра геодезии", t); self.assertIn("корпус 2, каб. 215", t)
            self.assertNotIn("Борис", t)
            t = (await logic_find.teacher_answer(ctx, "крылов")).text
            self.assertIn("уточните инициалы", t); self.assertIn("Кафедра физики", t); self.assertIn("кабинет подразделения в справочнике не указан", t.lower())
            t = (await logic_find.teacher_answer(ctx, "иванова")).text
            self.assertIn("В ближайшие 14 дней пар в расписании нет", t); self.assertIn("корпус 2", t)
            t = (await logic_find.teacher_answer(ctx, "крылов бб")).text; self.assertIn("Ближайшая пара", t); self.assertIn("311", t)
            t = (await logic_find.teacher_answer(ctx, "петров")).text; self.assertIn("справочнике вуза этого преподавателя не нашёл", t)
            t = (await logic_find.teacher_answer(ctx, "сидоров")).text; self.assertIn("не нашёл", t)
            from datetime import date
            t = (await logic_find.teacher_answer(ctx, "крылов аа", date(2026, 10, 15))).text; self.assertIn("Завтра", t); self.assertIn("ИС-11", t)
            # через NLU в личке и в группе
            g = (await r.search_groups("ис11"))[0]["id"]
            u = await r.touch_user(5, None, None); await r.update_user(5, group_id=g); u = await r.get_user(5)
            out = await router.handle_text(Ctx(r, CFG, u, now=NOW), "где найти препода Крылова А.А.")
            self.assertIn("Кафедра геодезии", out.screen.text)
            out = await router.handle_text(Ctx(r, CFG, u, now=NOW), "а завтра будет мгп?")
            self.assertIn("пара состоится завтра в 10:15–11:50", out.screen.text); self.assertIn("215", out.screen.text); self.assertIn("Крылов А. А.", out.screen.text)
            out = await router.handle_text(Ctx(r, CFG, u, now=NOW), "в пятницу мгп будет?")
            self.assertIn("в расписании нет", out.screen.text)
            await db.close()
        asyncio.run(go())

    def test_waiting_questions(self):
        async def go():
            db, r = await setup(); qs = QuestionService(r, CFG)
            g = (await r.search_groups("ис11"))[0]["id"]
            chat = await r.upsert_chat(-9, "ИС-11", g, 1); await r.update_chat(-9, smart_mode="active", wait_min=60); chat = await r.get_chat(-9)
            t0 = 1_000_000
            self.assertFalse(await qs.consider(chat, 10, 1, "привет всем", t0, NOW))
            self.assertFalse(await qs.consider(chat, 10, 1, "я люблю котиков?", t0, NOW))
            self.assertTrue(await qs.consider(chat, 10, 100, "а завтра будет мгп?", t0, NOW))
            self.assertFalse(await qs.consider(chat, 11, 101, "завтра мгп будет?", t0, NOW))   # такой же вопрос уже ждёт
            self.assertFalse(await qs.consider(chat, 10, 102, "какие пары завтра?", t0, NOW))   # у человека уже есть ожидающий вопрос
            self.assertTrue(await qs.consider(chat, 12, 103, "какие пары завтра?", t0, NOW))
            # на второй вопрос ответили реплаем
            self.assertEqual(await qs.mark_answers(-9, 13, "да вроде все 2", 103), 1)
            # на первый «ответили» сообщением со словами про предмет
            self.assertEqual(await qs.mark_answers(-9, 10, "будет мгп", None), 0)       # автор вопроса не считается
            self.assertEqual(await qs.mark_answers(-9, 14, "лол", None), 0)
            self.assertEqual(await qs.mark_answers(-9, 14, "а физика будет?", None), 0)
            # никто не ответил за час: бот отвечает
            self.assertEqual(await qs.due_answers(t0 + 3599, NOW), [])
            res = await qs.due_answers(t0 + 3600 + 5, NOW)
            self.assertEqual(len(res), 1); p, scr = res[0]
            self.assertEqual(p["message_id"], 100); self.assertIn("Пока никто не ответил", scr.text); self.assertIn("215", scr.text); self.assertIn("Крылов А. А.", scr.text)
            self.assertEqual(await qs.due_answers(t0 + 9999, NOW), [])                          # повторно не отвечает
            # ответ человека снимает вопрос
            self.assertTrue(await qs.consider(chat, 20, 200, "где завтра первая пара?", t0, NOW))
            self.assertEqual(await qs.mark_answers(-9, 21, "в 215", None), 1)
            self.assertEqual(await qs.due_answers(t0 + 99999, NOW), [])
            # режим mention/keywords вопросы не копит
            await r.update_chat(-9, smart_mode="mention"); chat = await r.get_chat(-9)
            self.assertFalse(await qs.consider(chat, 30, 300, "какие пары завтра?", t0, NOW))
            # в активном режиме без обращения роутер молчит, с обращением отвечает сразу
            ctx = Ctx(r, CFG, {"id": 40, "group_id": None, "subgroup": None, "role": "student"}, now=NOW)
            self.assertIsNone(await router.group_text(ctx, g, "какие пары завтра?", "active", False))
            self.assertIsNotNone(await router.group_text(ctx, g, "какие пары завтра?", "active", True))
            self.assertIn("215", (await router.group_text(ctx, g, "где найти Крылова А.А.", "keywords", False)).text)
            await db.close()
        asyncio.run(go())
if __name__ == "__main__":
    unittest.main()


class T2(unittest.TestCase):
    def test_directory_sync_and_admin(self):
        from app.bot import runtime
        from app.services.directory import DirectorySync
        from app.providers.directory import parse_directory_rows
        async def go():
            db, r = await setup()
            state = {"fail": True}
            async def crawl():
                if state["fail"]: raise ConnectionError("Too many redirects")
                return ([{"name": "Орлов Олег Олегович", "unit": "Кафедра математики", "url": ""}], [{"name": "Кафедра математики", "room": "310", "url": ""}])
            alerts = []
            svc = DirectorySync(r, crawl)
            ok, msg = await svc.run_once(); self.assertFalse(ok); self.assertIn("redirects", msg)
            self.assertEqual((await r.directory_counts())[0], 3)                  # старый справочник сохранён
            state["fail"] = False
            ok, msg = await svc.run_once(); self.assertTrue(ok); self.assertEqual(await r.directory_counts(), (1, 1, 1))
            staff, units, errs = parse_directory_rows([["Крылов Андрей Андреевич", "Кафедра геодезии", "215"]])
            self.assertIn("Преподавателей: 1", await svc.apply_file(staff, units)); self.assertEqual(r.setting("dir_source"), "file")
            # админка
            services = {"directory": svc}
            async def do(uid, **kw): return await runtime.process(r, CFG, uid, "u", "U", services=services, now=NOW, **kw)
            await do(1, command="start")
            out = await do(1, callback="ad:dir"); self.assertIn("Справочник преподавателей", out.screen.text); self.assertIn("файл", out.screen.text)
            out = await do(1, callback="ad:dirsync"); self.assertIn("✅", out.screen.text)
            await do(1, callback="ad:dirimp")
            out = await do(1, document=("d.csv", "ФИО;Подразделение;Кабинет\nМусор;x;1\n".encode())); self.assertIn("Ничего не загружено", out.screen.text)
            out = await do(1, document=("d.csv", "ФИО;Подразделение;Кабинет\nВолков Виктор Викторович;Кафедра химии;101\n".encode())); self.assertIn("загружен", out.screen.text)
            self.assertEqual((await r.find_staff("волков"))[0]["unit"], "Кафедра химии")
            self.assertTrue((await do(300, callback="ad:dir")).toast)          # обычный пользователь не может
            # пользователь ищет преподавателя через меню
            g = (await r.search_groups("ис11"))[0]["id"]
            await do(100, command="start"); await r.update_user(100, group_id=g, fio="Смирнова Анна Сергеевна", fio_status="verified")
            out = await do(100, callback="me:findt"); self.assertEqual(out.state, "me:findt")
            out = await do(100, text="Волков"); self.assertIn("Кафедра химии", out.screen.text); self.assertIn("101", out.screen.text)
            out = await do(100, callback="me:findt"); out = await do(100, text="Крылов"); self.assertIn("Крылов", out.screen.text)
            await db.close()
        asyncio.run(go())
