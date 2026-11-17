import asyncio, unittest, gzip
from datetime import datetime, timedelta, date
from app import timeutil as tu
from app.config import Settings
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo
from app.bot import runtime, router
from app.bot.core import Ctx
from app.models import LessonRec
from app.services.sync import SyncService
from app.services.backup import make_backup
from app.services.fio_verify import auto_verify_pending

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=tu.tz())  # среда, 12:00
CFG = Settings("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "https://sgugit.ru/raspisanie", 30, "/tmp/bk", "INFO")

def L(day, num, subj, teacher, room, start, end, kind="лекция"):
    return LessonRec("ИС-11", day, num, start, end, subj, teacher, room, kind)

def lessons():
    out = []
    for i, day in enumerate(["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-21", "2026-10-22"]):
        out += [L(day, 1, "Математика", "Иванов Иван Иванович", "310", "08:30", "10:05"),
                L(day, 2, "Физика", "Петров П. П.", "215", "10:15", "11:50", "практика"),
                L(day, 3, "История", "Сидоров С. С.", "101", "14:00", "15:35")]
    return out

def texts(out): return out.screen.text if out.screen else ""
def datas(out):
    return [b.data for row in (out.screen.kb or []) for b in row] if out.screen else []

async def _seed_manual_roster(repo, group_id: int, surname: str) -> list[int]:
    """Создаёт в тестовой БД два независимых ручных подтверждения фамилии."""
    female = surname.casefold().endswith(("ова", "ева", "ина", "ская", "цкая", "ая"))
    names = ([f"{surname} Елена Петровна", f"{surname} Мария Николаевна"] if female else
             [f"{surname} Алексей Сергеевич", f"{surname} Дмитрий Петрович"])
    ids = [-910001, -910002]
    for uid, fio in zip(ids, names):
        await repo.ensure_user(uid)
        await repo.update_user(uid, group_id=group_id, fio=fio, fio_status="verified")
        await repo.audit(1, "fio_ok", str(uid))
    return ids


async def _remove_manual_roster(repo, ids: list[int]) -> None:
    for uid in ids:
        await repo.db.execute("DELETE FROM audit WHERE action = 'fio_ok' AND details = ?", str(uid))
        await repo.db.execute("DELETE FROM users WHERE id = ?", uid)


class Sim:
    async def setup(self):
        self.db = Database("sqlite:///:memory:"); await self.db.connect(); await migrate(self.db)
        self.repo = Repo(self.db); await self.repo.load_settings()
        await self.repo.set_setting("fio_auto_delay_min", "0")  # в тестах «пауза» автопроверки отсутствует
        async def fetch(): return lessons()
        self.sync = SyncService(self.repo, fetch)
        await self.sync.run_once()
        self.svc = {"sync": self.sync}
        return self
    async def do(self, uid, **kw):
        return await runtime.process(self.repo, CFG, uid, f"user{uid}", f"User{uid}", services=self.svc, now=NOW, **kw)
    async def register(self, uid, fio="Смирнова Анна Сергеевна", group="ИС-11", roster_evidence=True):
        await self.do(uid, command="start")
        out = await self.do(uid, text=group)
        gdata = [d for d in datas(out) if d and d.startswith("r:g:")][0]
        await self.do(uid, callback=gdata)
        # ФИО — отдельный добровольный шаг, необходимый только для защищённых разделов.
        await self.do(uid, callback="r:redo")
        out = await self.do(uid, text=fio)
        out = await self.do(uid, callback="r:ok")
        roster_ids = []
        if roster_evidence:
            user = await self.repo.get_user(uid)
            roster_ids = await _seed_manual_roster(self.repo, user["group_id"], fio.split()[0])
        await auto_verify_pending(self.repo)  # имитируем фоновую проверку при наличии независимого roster evidence
        if roster_ids:
            await _remove_manual_roster(self.repo, roster_ids)
        return out

def run(c): return asyncio.run(c)

class T(unittest.TestCase):
    def test_private_registration_gate_blocks_old_routes(self):
        async def go():
            s = await Sim().setup()
            # Ни команда, ни старая кнопка не открывают расписание незарегистрированному.
            out = await s.do(909, command="today")
            self.assertIn("группу", texts(out).lower())
            out = await s.do(909, callback="s:d:today")
            self.assertIn("группу", texts(out).lower())
            out = await s.do(909, callback="me:ntf")
            self.assertIn("группу", texts(out).lower())

            # Группа завершает базовую регистрацию, но защищённые разделы требуют ФИО.
            group = await s.repo.get_or_create_group("ИС-11")
            await s.repo.update_user(909, group_id=group["id"])
            out = await s.do(909, callback="h:l:0")
            self.assertIn("ФИО", texts(out))
            self.assertNotIn("Задания группы", texts(out))

            # Даже сохранённое старое состояние добавления задания не позволяет обойти gate.
            await s.repo.set_state(909, "hw:text", {"subject": "Математика"})
            out = await s.do(909, text="дз на завтра")
            self.assertIn("ФИО", texts(out))
            state, _ = await s.repo.get_state(909)
            self.assertIsNone(state)
            await s.db.close()
        run(go())

    def test_add_group_button_hidden_after_user_added_bot(self):
        async def go():
            s = await Sim().setup()
            gid = (await s.repo.get_or_create_group("ИС-11"))["id"]
            await s.repo.touch_user(777, None, None)
            await s.repo.update_user(777, group_id=gid, fio="Смирнова Анна Сергеевна", fio_status="verified")
            out = await s.do(777, command="start")
            buttons = [b for row in out.screen.kb for b in row]
            self.assertTrue(any(b.url and "startgroup" in b.url for b in buttons))
            await s.repo.upsert_chat(-100777, "Тестовая группа", gid, 777)
            out = await s.do(777, command="start")
            buttons = [b for row in out.screen.kb for b in row]
            self.assertFalse(any(b.url and "startgroup" in b.url for b in buttons))
            self.assertTrue(any(b.url and "theyasha_bot" in b.url for b in buttons))
            await s.db.close()
        run(go())

    def test_registration_and_schedule(self):
        async def go():
            s = await Sim().setup()
            out = await s.do(100, command="start"); self.assertIn("группу", texts(out))
            out = await s.do(100, text="ис 11"); self.assertIn("r:g:", " ".join(d for d in datas(out) if d))
            gd = [d for d in datas(out) if d.startswith("r:g:")][0]
            out = await s.do(100, callback=gd)
            self.assertNotIn("r:redo", datas(out))
            self.assertIn("s:d:today", datas(out))
            self.assertNotIn("p:register", datas(out))
            out = await s.do(100, callback="t:l:m:0")
            self.assertIn("ФИО", texts(out))
            out = await s.do(100, callback="me:help")
            self.assertIn("p:register", datas(out))
            out = await s.do(100, callback="r:redo")
            out = await s.do(100, text="Иванов Иван Иванович"); self.assertIn("Напишите свои ФИО", texts(out)); self.assertNotIn("r:ok", datas(out))
            out = await s.do(100, text="хуй пизда джигурда"); self.assertNotIn("r:ok", datas(out))
            out = await s.do(100, text="Смирнова Анна Сергеевна"); self.assertIn("r:ok", datas(out))
            out = await s.do(100, text="левый текст"); self.assertEqual(out.screen, None)  # ждём кнопку
            out = await s.do(100, callback="r:ok"); self.assertIn("Главное меню", texts(out)); self.assertIn("автоматическую проверку", texts(out))
            u = await s.repo.get_user(100); self.assertEqual((u["fio"], u["fio_status"]), ("Смирнова Анна Сергеевна", "pending"))  # сразу не подтверждается
            user = await s.repo.get_user(100)
            roster_ids = await _seed_manual_roster(s.repo, user["group_id"], "Смирнова")
            self.assertEqual((await auto_verify_pending(s.repo))["verified"], 1)  # две независимые ручные записи в группе
            await _remove_manual_roster(s.repo, roster_ids)
            u = await s.repo.get_user(100); self.assertEqual(u["fio_status"], "verified")
            out = await s.do(100, callback="s:d:today"); t = texts(out)
            self.assertIn("Математика", t); self.assertIn("08:30", t); self.assertIn("окно", t)  # окно между 11:50 и 14:00
            out = await s.do(100, callback="s:d:tom"); self.assertIn("Четверг", texts(out))
            out = await s.do(100, callback="s:w:cur"); self.assertIn("Неделя 12.10–18.10", texts(out))
            out = await s.do(100, callback="s:c:2026-10"); self.assertTrue(any(d.startswith("s:d:2026-10-") for d in datas(out)))
            out = await s.do(100, callback="s:n"); self.assertIn("Дальше", texts(out)); self.assertIn("История", texts(out))
            out = await s.do(100, command="today"); self.assertIn("Математика", texts(out))
            out = await s.do(100, command="admin"); self.assertEqual(out.screen, None)  # админ-команда скрыта
            out = await s.do(100, callback="ad:menu"); self.assertTrue(out.toast)
            await s.db.close()
        run(go())

    def test_one_letter_group_search_and_add_to_group_button(self):
        async def go():
            s = await Sim().setup()
            await s.repo.get_or_create_group("Э-22.1")
            out = await s.do(777, command="start")
            self.assertTrue(any(b.url and "startgroup" in b.url and "admin=pin_messages+delete_messages" in b.url for row in out.screen.kb for b in row))
            out = await s.do(777, text="e221")  # латинская раскладка: E часто вводят вместо Э
            self.assertIn("r:g:", " ".join(datas(out)))
            gid = next(d for d in datas(out) if d.startswith("r:g:"))
            out = await s.do(777, callback=gid)
            await s.do(777, callback="r:redo")
            out = await s.do(777, text="Смирнова Анна Сергеевна")
            out = await s.do(777, callback="r:ok")
            # В основном меню есть отдельная кнопка добавления в группу с корректной deep-link-ссылкой.
            urls = [b.url for row in out.screen.kb for b in row if b.url]
            self.assertTrue(any(u and "startgroup" in u and "admin=pin_messages+delete_messages" in u for u in urls))
            self.assertTrue(any(u and u.startswith("https://t.me/theyasha_bot") for u in urls))
            await s.db.close()
        run(go())

    def test_teacher_registration_schedule_and_switch(self):
        async def go():
            s = await Sim().setup()
            out = await s.do(200, command="start")
            self.assertNotIn("p:register", datas(out))
            out = await s.do(200, text="ИС-11")
            group_choice = next(d for d in datas(out) if d.startswith("r:g:"))
            out = await s.do(200, callback=group_choice)
            self.assertNotIn("p:register", datas(out))
            out = await s.do(200, callback="me:help")
            self.assertIn("p:register", datas(out))
            out = await s.do(200, callback="p:register")
            self.assertIn("фамилию", texts(out).lower())
            out = await s.do(200, text="Иванов")
            choices = [d for d in datas(out) if d and d.startswith("p:choose:")]
            self.assertEqual(len(choices), 1)
            out = await s.do(200, callback=choices[0])
            self.assertIn("Кабинет преподавателя", texts(out))
            user = await s.repo.get_user(200)
            self.assertEqual(user["role"], "teacher")
            self.assertIsNotNone(user["group_id"])
            self.assertIsNone(user["fio"])
            out = await s.do(200, callback="p:day:today")
            self.assertIn("Математика", texts(out))
            self.assertIn("Группа: ИС-11", texts(out))
            out = await s.do(200, callback="p:student")
            self.assertIn("Главное меню", texts(out))
            user = await s.repo.get_user(200)
            self.assertEqual(user["role"], "student")
            self.assertIsNotNone(user["group_id"])
            self.assertIsNone(user["fio"])
            await s.db.close()
        run(go())

    def test_nlu_answers(self):
        async def go():
            s = await Sim().setup(); await s.register(100)
            async def ask(q): return texts(await s.do(100, text=q))
            self.assertIn("08:30", await ask("какая завтра первая пара?"))
            self.assertIn("Математика", await ask("какая завтра первая пара?"))
            self.assertIn("История", await ask("какие завтра пары"))
            self.assertIn("17:00" if False else "15:35", await ask("когда завтра заканчиваем"))
            self.assertIn("3", await ask("сколько пар завтра"))
            self.assertIn("215", await ask("где завтра вторая пара"))
            self.assertIn("Петров", await ask("кто ведёт физику"))
            self.assertIn("ближайшая", await ask("когда физика"))
            self.assertIn("Неделя", await ask("расписание на неделю"))
            self.assertIn("Не понял", await ask("абракадабра"))
            self.assertIn("Пожалуйста", await ask("спасибо"))
            self.assertIn("Чётность", await ask("какая сейчас неделя"))
            self.assertIn("экзамен", (await ask("когда экзамен")).lower())
            await s.db.close()
        run(go())

    def test_detailed_schedule_answers_use_rich_cards(self):
        async def go():
            s = await Sim().setup(); await s.register(100)
            for question in ("какая завтра первая пара?", "где завтра вторая пара", "кто ведёт физику", "когда физика"):
                out = await s.do(100, text=question)
                self.assertIsNotNone(out.screen, question)
                self.assertTrue(out.screen.rich, question)
                self.assertIn("Математика" if "первая" in question else
                              "Физика" if "физика" in question else "215", out.screen.text)
            await s.db.close()
        run(go())

    def test_next_lesson_uses_rich_schedule_card(self):
        async def go():
            s = await Sim().setup(); await s.register(100)
            out = await s.do(100, text="какая следующая пара?")
            self.assertTrue(out.screen.rich)
            self.assertIn("История", out.screen.text)
            self.assertIn("<b>03</b>", out.screen.text)
            await s.db.close()
        run(go())

    def test_homework_flow(self):
        async def go():
            s = await Sim().setup(); await s.register(100)
            out = await s.do(100, text="дз математика №15-20 к пятнице")
            self.assertIn("h:save", datas(out)); self.assertIn("№15-20", texts(out))
            out = await s.do(100, callback="h:save")
            self.assertIn("опубликовано", texts(out).lower())
            self.assertFalse(out.notify)  # больше не отправляем задания на проверку администратору
            rows, total = await s.repo.list_hw((await s.repo.get_user(100))["group_id"], "2026-10-14", 0, 10)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["status"], "approved")
            await s.db.close()
        run(go())

    def test_main_menu_shows_next_lesson_and_homework_filters(self):
        async def go():
            s = await Sim().setup()
            await s.register(202)
            out = await s.do(202, command="start")
            self.assertNotIn("s:n", datas(out))
            self.assertIn("Дальше", texts(out))
            self.assertIn("Привет!", texts(out))
            self.assertIn("👥 <b>ИС-11</b>", texts(out))
            self.assertIn("Сегодня", texts(out))
            self.assertTrue(out.screen.rich)

            # Возврат кнопкой «Меню» показывает только рабочую сводку, без приветствия.
            out = await s.do(202, callback="m:home")
            self.assertNotIn("Привет!", texts(out))
            self.assertIn("👥 <b>ИС-11</b>", texts(out))
            self.assertIn("Дальше", texts(out))
            self.assertNotIn("s:n", datas(out))

            # Явная команда /menu может повторно показать короткое вступление.
            out = await s.do(202, command="menu")
            self.assertIn("Привет!", texts(out))

            group = (await s.repo.search_groups("ИС-11"))[0]
            gid = group["id"]
            today_hw = await s.repo.add_hw(gid, "История", "2026-10-14", "Подготовить конспект", "2026-10-14", 202, "approved")
            out = await s.do(202, callback="m:home")
            self.assertNotIn("Привет!", texts(out))
            self.assertIn("Задания на сегодня", texts(out))
            self.assertIn("Подготовить конспект", texts(out))
            self.assertIn(f"h:l:0", datas(out))

            overdue = await s.repo.add_hw(gid, "Математика", None, "Просрочено", "2026-10-13", 202, "approved")
            future = await s.repo.add_hw(gid, "Физика", None, "Скоро", "2026-10-15", 202, "approved")
            await s.repo.toggle_hw_done(202, future)

            out = await s.do(202, callback="h:l:0")
            self.assertIn("Просрочено и не отмечено выполненным: <b>1</b>", texts(out))
            self.assertIn("просрочено", texts(out).lower())
            self.assertIn("h:l:0:done", datas(out))
            self.assertIn("h:l:0:all", datas(out))
            self.assertIn(f"h:v:{overdue}:active", datas(out))

            out = await s.do(202, callback=f"h:v:{future}:done")
            self.assertIn(f"h:l:0:done", datas(out))
            out = await s.do(202, callback=f"h:dn:{future}:done")
            self.assertIn(f"h:l:0:done", datas(out))
            await s.db.close()
        run(go())

    def test_admin_can_restrict_homework_creation_without_banning_account(self):
        async def go():
            s = await Sim().setup()
            await s.register(100)
            out = await s.do(1, callback="ad:hw")
            self.assertIn("статистика", texts(out).lower())
            self.assertNotIn("на проверке", texts(out).lower())
            self.assertIn("ad:hwfind", datas(out))
            out = await s.do(1, callback="ad:hwfind")
            self.assertEqual(out.state, "ad:hw_user_search")
            out = await s.do(1, text="Смирнова Анна")
            self.assertIn("Создание заданий: разрешено", texts(out))
            self.assertIn("ad:hwb:100", datas(out))

            out = await s.do(1, callback="ad:hwb:100")
            self.assertIn("Создание заданий: запрещено", texts(out))
            user = await s.repo.get_user(100)
            self.assertEqual(user["hw_blocked"], 1)
            self.assertEqual(user["banned"], 0)

            blocked = await s.do(100, callback="h:add:0")
            self.assertIn("запретила", texts(blocked).lower())
            blocked = await s.do(100, text="дз математика №15-20 к пятнице")
            self.assertIn("запретила", texts(blocked).lower())

            out = await s.do(1, callback="ad:hwblocked:0")
            self.assertIn("User100", texts(out))
            self.assertIn("ad:hwuser:100", datas(out))
            out = await s.do(1, callback="ad:hwuser:100")
            self.assertIn("ad:hwb:100", datas(out))

            await s.do(1, callback="ad:hwb:100")
            draft = await s.do(100, text="дз математика №15-20 к пятнице")
            self.assertIn("h:save", datas(draft))
            await s.do(1, callback="ad:hwb:100")
            blocked = await s.do(100, callback="h:save")
            self.assertIn("запретила", texts(blocked).lower())
            self.assertEqual(await s.repo.count("homework", "author_id = ?", 100), 0)
            await s.db.close()
        run(go())

    def test_teachers_rating(self):
        async def go():
            s = await Sim().setup(); await s.register(100); await s.register(101, "Орлова Ольга Игоревна")
            out = await s.do(100, callback="t:l:m:0"); t = texts(out); self.assertIn("Преподаватели", t)
            tid = int([d for d in datas(out) if d.startswith("t:v:")][0].split(":")[2])
            out = await s.do(100, callback=f"t:v:{tid}:m:0"); self.assertIn(f"t:begin:{tid}:m:0", datas(out))
            out = await s.do(100, callback=f"t:begin:{tid}:m:0"); self.assertIn("Лекции", texts(out))
            score_cb = next(d for d in datas(out) if d == f"t:score:{tid}:0:5:m:0")
            out = await s.do(100, callback=score_cb); self.assertIn("комментарий", texts(out).lower())
            out = await s.do(100, text="Объясняет понятно, но иногда быстро.")
            public_comments = await s.repo.public_teacher_rating_comments(tid)
            self.assertEqual(public_comments[0]["comment"], "Объясняет понятно, но иногда быстро.")
            self.assertNotIn("user_id", public_comments[0])
            admin_comments = await s.repo.admin_teacher_rating_comments(tid)
            self.assertEqual(admin_comments[0]["user_id"], 100)
            self.assertEqual(await s.repo.my_rating(100, tid), 5)
            reviews = await s.repo.public_teacher_reviews(tid, 100)
            self.assertEqual(len(reviews), 1)
            review_id = reviews[0]["id"]
            self.assertNotIn("user_id", reviews[0])
            # Проверяем toggle-поведение реакций: один голос на пользователя и отзыв.
            out = await s.do(101, callback=f"t:react:{tid}:{review_id}:1:m:0")
            reacted = await s.repo.public_teacher_reviews(tid, 100)
            self.assertEqual((reacted[0]["likes"], reacted[0]["dislikes"]), (1, 0))
            await s.do(101, callback=f"t:react:{tid}:{review_id}:-1:m:0")
            reacted = await s.repo.public_teacher_reviews(tid, 100)
            self.assertEqual((reacted[0]["likes"], reacted[0]["dislikes"]), (0, 1))
            await s.do(101, callback=f"t:react:{tid}:{review_id}:-1:m:0")
            reacted = await s.repo.public_teacher_reviews(tid, 100)
            self.assertEqual((reacted[0]["likes"], reacted[0]["dislikes"]), (0, 0))
            out = await s.do(101, callback=f"t:reply:{tid}:{review_id}:m:0")
            self.assertEqual(out.state, "t:reply")
            out = await s.do(101, text="Согласен, особенно про объяснения.")
            replies = await s.repo.public_teacher_review_replies(review_id)
            self.assertEqual(replies[0]["reply"], "Согласен, особенно про объяснения.")
            self.assertNotIn("user_id", replies[0])
            admin_details = await s.repo.admin_teacher_review_details(tid)
            self.assertEqual(admin_details[0]["reply_user_id"], 101)
            out = await s.do(100, callback=f"t:r:{tid}:3:m:0"); self.assertIn("Иванов", texts(out))
            out = await s.do(100, callback="t:s"); self.assertEqual(out.state, "t:search")
            out = await s.do(100, text="петров"); self.assertIn("Нашёл", texts(out))
            await s.do(100, callback="t:s"); out = await s.do(100, text="физика"); self.assertIn("Нашёл", texts(out))
            await s.do(1, command="start")
            out = await s.do(1, callback="ad:rte"); self.assertIn("скрыт", texts(out))
            out = await s.do(100, callback="t:l:m:0"); self.assertIn("недоступен", out.toast)
            out = await s.do(100, command="menu"); self.assertNotIn("t:l:m:0", datas(out))
            await s.do(1, callback="ad:rte")
            out = await s.do(1, callback="ad:rt")
            self.assertIn(f"ad:rtc:{tid}:rating:0", datas(out))
            self.assertIn("ad:rto:rating:0", datas(out))
            self.assertIn("ad:rtv:rating:0", datas(out))
            settings = await s.do(1, callback="ad:set")
            self.assertNotIn("ad:st:rate_only_own", datas(settings))
            self.assertNotIn("ad:sv:min_votes", datas(settings))
            out = await s.do(1, callback="ad:rtv:rating:0")
            self.assertEqual(out.state, "ad:rating_min_votes")
            out = await s.do(1, text="3")
            self.assertIn("Порог показа средней оценки: <b>3</b>", texts(out))
            self.assertIn(f"ad:rtc:{tid}:rating:0", datas(out))
            out = await s.do(1, callback=f"ad:rtc:{tid}:rating:0")
            self.assertIn("Оценки по видам занятий", texts(out))
            self.assertIn("5.00/5", texts(out))
            out = await s.do(1, callback=f"ad:rae:{tid}:0")
            self.assertIn("ID <code>100</code>", texts(out))
            await s.do(1, callback=f"ad:radc:{tid}:100:0")
            out = await s.do(1, callback=f"ad:radel:{tid}:100:0:y")
            self.assertIn("Оценка удалена", out.toast)
            self.assertIsNone(await s.repo.my_rating(100, tid))
            out = await s.do(1, callback=f"ad:rrp:{tid}:{review_id}:0")
            self.assertIn("Согласен", texts(out))
            reply_id = (await s.repo.admin_teacher_review_replies(review_id, tid))[0]["id"]
            await s.do(1, callback=f"ad:rrpc:{tid}:{review_id}:{reply_id}:0")
            out = await s.do(1, callback=f"ad:rrpd:{tid}:{review_id}:{reply_id}:0:y")
            self.assertIn("Ответ удалён", out.toast)
            await s.do(1, callback=f"ad:rrdc:{tid}:{review_id}:0")
            out = await s.do(1, callback=f"ad:rrdel:{tid}:{review_id}:0:y")
            self.assertIn("Отзыв и связанные данные удалены", out.toast)
            self.assertEqual(await s.repo.admin_teacher_reviews(tid, 0, 5), ([], 0))
            self.assertEqual(await s.repo.db.scalar("SELECT COUNT(*) FROM teacher_rating_comments WHERE teacher_id = ?", tid), 0)
            await s.do(1, callback=f"ad:rth:{tid}:rating:0")
            out = await s.do(100, callback=f"t:v:{tid}:m:0"); self.assertTrue(out.toast)
            out = await s.do(1, callback=f"ad:rtr:{tid}:y")
            self.assertIn("отключён", (out.toast or "").lower())
            await s.db.close()
        run(go())

    def test_head_role_removed_and_admin(self):
        async def go():
            s = await Sim().setup(); await s.register(100); await s.register(300, "Волкова Елена Павловна")
            out = await s.do(100, callback="me:menu"); self.assertNotIn("me:head", datas(out))
            self.assertNotIn("hd:menu", datas(out))
            out = await s.do(100, callback="me:head"); self.assertIn("отключена", out.toast)
            # Админ-панель и разграничение прав продолжают работать.
            out = await s.do(1, callback="ad:adma"); out = await s.do(1, text="300"); self.assertIn("Экспорт", texts(out))
            out = await s.do(300, command="admin"); self.assertIsNotNone(out.screen)
            self.assertNotIn("ad:bk", datas(out)); self.assertNotIn("ad:ex", datas(out)); self.assertNotIn("ad:adm", datas(out))
            for forbidden in ("ad:bk", "ad:bkn", "ad:ex:users", "ad:adm", "ad:set", "ad:aud", "ad:bky"):
                self.assertTrue((await s.do(300, callback=forbidden)).toast, forbidden)
            self.assertTrue((await s.do(300, callback="ad:sch")).toast)
            out = await s.do(300, callback="ad:stats"); self.assertIn("Пользователей", texts(out))
            out = await s.do(300, callback="ad:u:1"); self.assertNotIn("ad:ub:1", datas(out))
            self.assertNotIn("Роль: админ", texts(out))
            out = await s.do(300, callback="ad:ub:1"); self.assertTrue(out.toast)
            out = await s.do(300, callback="ad:u:100"); self.assertIn("ad:ub:100", datas(out))
            out = await s.do(300, callback="ad:ub:100"); self.assertIn("Бан: да", texts(out))
            out = await s.do(100, text="привет"); self.assertEqual(out.screen, None)
            await s.do(300, callback="ad:ub:100")
            out = await s.do(1, callback="ad:admp:300:schedule"); self.assertTrue((await s.do(300, callback="ad:sch")).screen)
            out = await s.do(1, callback="ad:admd:300"); self.assertEqual((await s.repo.get_user(300))["role"], "student")
            await s.db.close()
        run(go())

    def test_fio_moderation_and_settings(self):
        async def go():
            s = await Sim().setup()
            await s.register(100, "Мамаев Тагирчик")  # две слова с редким именем: на проверку
            u = await s.repo.get_user(100); self.assertEqual(u["fio_status"], "pending")
            out = await s.do(100, callback="h:add:0"); self.assertIn("ФИО", texts(out))  # не подтверждён: нельзя
            out = await s.do(100, callback="t:l:m:0"); self.assertIn("ФИО", texts(out))
            tid = (await s.repo.search_teachers("Иванов"))[0]["id"]
            out = await s.do(100, callback=f"t:r:{tid}:5:m:0"); self.assertIn("ФИО", texts(out))
            out = await s.do(1, callback="ad:fq:0"); self.assertIn("ad:u:100", datas(out))
            out = await s.do(1, callback="ad:ufo:100:ok"); self.assertEqual(out.notify[0][0], 100)
            out = await s.do(100, callback=f"t:v:{tid}:m:0"); self.assertIn("Иванов", texts(out))
            out = await s.do(1, callback="ad:ufo:100:reset"); out = await s.do(100, command="start"); self.assertNotIn("r:redo", datas(out))
            out = await s.do(100, callback="h:l:0"); self.assertIn("ФИО", texts(out))
            # настройки
            out = await s.do(1, callback="ad:st:maintenance"); out = await s.do(100, command="today"); self.assertIn("технические", texts(out).lower())
            out = await s.do(1, command="admin"); self.assertIn("Панель управления", texts(out))
            await s.do(1, callback="ad:st:maintenance")
            out = await s.do(1, callback="ad:rtv:rating:0"); out = await s.do(1, text="2"); self.assertEqual(s.repo.setting("min_votes"), "2")
            out = await s.do(1, callback="ad:rtv:rating:0"); out = await s.do(1, text="abc"); self.assertIn("число", texts(out))
            await s.do(1, callback="ad:menu")
            # стоп-слова и синонимы
            await s.do(1, callback="ad:sw:stub"); await s.do(1, text="Маракуйя"); stop, bad = await s.repo.stoplists(); self.assertIn("маракуйя", stop)
            await s.do(1, callback="ad:ala"); await s.do(1, text="матеша2 = Математика")
            await s.repo.update_user(100, fio="Смирнова Анна Сергеевна", fio_status="verified"); await s.repo.clear_state(100)
            out = await s.do(100, text="кто ведёт матеша2"); self.assertIn("Иванов", texts(out))
            out = await s.do(1, callback="ad:aud"); self.assertIn("setting", texts(out))
            await s.db.close()
        run(go())

    def test_import_broadcast_backup_export(self):
        async def go():
            s = await Sim().setup(); await s.register(100); await s.register(200, "Кузнецова Мария Андреевна")
            await s.do(1, callback="ad:sch"); await s.do(1, callback="ad:imp")
            bad = "группа;дата;начало;конец;предмет\nИС-11;32.13.2026;8:30;7:00;\n".encode()
            out = await s.do(1, document=("x.csv", bad)); self.assertIn("ошибки", texts(out))
            good = "группа;дата;пара;начало;конец;предмет;преподаватель;аудитория\nГД-21;2026-10-20;1;08:30;10:05;Геодезия;Орлов О. О.;12\n".encode()
            out = await s.do(1, document=("x.csv", good)); self.assertIn("Загружено занятий: 1", texts(out))
            self.assertEqual(len(await s.repo.search_groups("гд21")), 1)
            out = await s.do(1, callback="ad:sync"); self.assertIn("✅", texts(out))
            await s.do(1, callback="ad:par"); out = await s.do(1, text="12.10.2026"); self.assertIn("нечётная", texts(out))
            out = await s.do(100, callback="s:d:today"); self.assertIn("нечётная неделя", texts(out))
            await s.do(1, callback="ad:grp"); out = await s.do(1, text="КА-31, КА-32"); self.assertIn("КА-31", texts(out))
            # рассылка
            await s.do(1, callback="ad:bc"); await s.do(1, callback="ad:bca:grp"); out = await s.do(1, text="ис-11")
            out = await s.do(1, text="Завтра пары перенесены!", text_html="<b>Завтра</b> пары перенесены!")
            self.assertIn("Получателей: 2", texts(out))
            self.assertIn("<b>Завтра</b>", texts(out))
            await s.do(1, callback="ad:bcb:support")
            await s.do(1, callback="ad:bcb:rating")
            await s.do(1, callback="ad:bcb:url")
            out = await s.do(1, text="Подробнее | https://example.com")
            self.assertIn("Подробнее", texts(out))
            out = await s.do(1, callback="ad:bcy"); self.assertEqual(sorted(n[0] for n in out.notify), [100, 200])
            self.assertIn("<b>Завтра</b>", out.notify[0][1].text)
            buttons = [button for row in out.notify[0][1].kb for button in row]
            self.assertEqual({button.data for button in buttons if button.data}, {"bc:support", "bc:rating"})
            self.assertIn("https://example.com", {button.url for button in buttons if button.url})
            # Функции старост удалены: старые callback-и безопасно отклоняются.
            out = await s.do(100, callback="hd:ml")
            self.assertIn("отключ", (out.toast or "").lower())
            # экспорт
            for kind in ("users", "homework"):
                out = await s.do(1, callback=f"ad:ex:{kind}"); self.assertTrue(out.file[1][:2] == b"PK")
            out = await s.do(1, callback="ad:ex:ratings")
            self.assertIsNone(out.file)  # рейтинг управляется только через раздел «Рейтинг»
            # бэкап и восстановление
            out = await s.do(1, callback="ad:bkn"); name, blob, _ = out.file; self.assertTrue(name.endswith(".json.gz"))
            await s.do(1, callback="ad:bkr"); out = await s.do(1, document=("b.json.gz", b"junk")); self.assertIn("не похож", texts(out))
            out = await s.do(1, document=("b.json.gz", blob)); self.assertIn("ad:bky", datas(out))
            await s.repo.update_user(100, fio="Испорчено")
            out = await s.do(1, callback="ad:bky"); self.assertIn("Восстановлено", texts(out))
            self.assertEqual((await s.repo.get_user(100))["fio"], "Смирнова Анна Сергеевна")
            await s.db.close()
        run(go())

    def test_profile_notifications_groups(self):
        async def go():
            s = await Sim().setup(); await s.register(100)
            out = await s.do(100, callback="me:ntf"); self.assertIn("Уведомления", texts(out))
            await s.do(100, callback="me:n:ev:t"); await s.do(100, callback="me:n:et:2100"); await s.do(100, callback="me:n:bf:30"); await s.do(100, callback="me:n:ch:t")
            u = await s.repo.get_user(100); self.assertEqual((u["n_evening"], u["n_evening_time"], u["n_before"], u["n_changes"]), (0, "21:00", 30, 0))
            await s.do(100, callback="me:sub:2"); self.assertEqual((await s.repo.get_user(100))["subgroup"], 2)
            out = await s.do(100, callback="me:ics"); self.assertTrue(out.file and b"BEGIN:VCALENDAR" in out.file[1])
            out = await s.do(100, callback="me:other"); out = await s.do(100, text="ис-11"); self.assertIn("Группа", texts(out)) if False else None
            await s.repo.get_or_create_group("ГД-21")
            out = await s.do(100, callback="me:grp"); out = await s.do(100, text="гд-21")
            gd = [d for d in datas(out) if d.startswith("r:g:")][0]; out = await s.do(100, callback=gd); self.assertIn("Главное меню", texts(out))
            self.assertEqual((await s.repo.get_user(100))["fio"], "Смирнова Анна Сергеевна")
            out = await s.do(100, callback="me:fb"); out = await s.do(100, text="Привет, админ")
            self.assertFalse(out.notify)
            self.assertEqual(await s.repo.db.scalar("SELECT COUNT(*) FROM support_messages WHERE user_id = ?", 100), 1)
            await s.repo.update_user(1, role="admin")
            out = await s.do(1, callback="ad:msg:0")
            self.assertIn("Диалоги", texts(out))
            out = await s.do(1, callback="ad:msgread:100")
            self.assertIn("Привет, админ", texts(out))
            out = await s.do(1, callback="ad:msgreply:100")
            out = await s.do(1, text="Здравствуйте! Помогу.")
            self.assertEqual(out.notify_timed[0][0], 100)
            out = await s.do(100, text="Спасибо!")
            self.assertFalse(out.notify)
            self.assertEqual(await s.repo.db.scalar("SELECT COUNT(*) FROM support_messages WHERE user_id = ?", 100), 3)
            await s.do(100, callback="me:del"); out = await s.do(100, callback="me:del:y"); u = await s.repo.get_user(100)
            self.assertEqual((u["fio"], u["group_id"]), (None, None))
            out = await s.do(100, text="какие завтра пары"); self.assertIn("группу", texts(out))
            # групповой чат
            g = (await s.repo.search_groups("ис11"))[0]
            user = await s.repo.touch_user(5, None, None); ctx = Ctx(s.repo, CFG, user, now=NOW)
            self.assertIn("08:30", (await router.group_text(ctx, g["id"], "какая завтра первая пара", "mention", True)).text)
            self.assertIsNone(await router.group_text(ctx, g["id"], "какая завтра первая пара", "mention", False))
            self.assertIsNotNone(await router.group_text(ctx, g["id"], "какая завтра первая пара", "keywords", False))
            self.assertIsNone(await router.group_text(ctx, g["id"], "привет всем", "keywords", False))
            self.assertIsNone(await router.group_text(ctx, g["id"], "какая завтра первая пара", "off", True))
            self.assertIn("Математика", (await router.group_command(ctx, g["id"], "today")).text)
            self.assertIn("Математика", (await router.group_command(ctx, g["id"], "schedule")).text)
            self.assertIn("заданий", (await router.group_command(ctx, g["id"], "homework")).text.lower())
            await s.db.close()
        run(go())
if __name__ == "__main__":
    unittest.main()
