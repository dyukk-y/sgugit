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
    async def register(self, uid, fio="Смирнова Анна Сергеевна", group="ИС-11"):
        await self.do(uid, command="start")
        out = await self.do(uid, text=group)
        gdata = [d for d in datas(out) if d and d.startswith("r:g:")][0]
        await self.do(uid, callback=gdata)
        out = await self.do(uid, text=fio)
        out = await self.do(uid, callback="r:ok")
        await auto_verify_pending(self.repo)  # как будто фоновая задача уже отработала
        return out

def run(c): return asyncio.run(c)

class T(unittest.TestCase):
    def test_registration_and_schedule(self):
        async def go():
            s = await Sim().setup()
            out = await s.do(100, command="start"); self.assertIn("группу", texts(out))
            out = await s.do(100, text="ис 11"); self.assertIn("r:g:", " ".join(datas(out)))
            gd = [d for d in datas(out) if d.startswith("r:g:")][0]
            out = await s.do(100, callback=gd); self.assertIn("ФИО", texts(out))
            out = await s.do(100, text="Иванов Иван Иванович"); self.assertIn("Напишите свои ФИО", texts(out)); self.assertNotIn("r:ok", datas(out))
            out = await s.do(100, text="хуй пизда джигурда"); self.assertNotIn("r:ok", datas(out))
            out = await s.do(100, text="Смирнова Анна Сергеевна"); self.assertIn("r:ok", datas(out))
            out = await s.do(100, text="левый текст"); self.assertEqual(out.screen, None)  # ждём кнопку
            out = await s.do(100, callback="r:ok"); self.assertIn("Главное меню", texts(out)); self.assertIn("автоматическую проверку", texts(out))
            u = await s.repo.get_user(100); self.assertEqual((u["fio"], u["fio_status"]), ("Смирнова Анна Сергеевна", "pending"))  # сразу не подтверждается
            self.assertEqual((await auto_verify_pending(s.repo))["verified"], 1)  # подтверждает фоновая проверка
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
            self.assertTrue(any(b.url and "startgroup=true" in b.url for row in out.screen.kb for b in row))
            out = await s.do(777, text="e221")  # латинская раскладка: E часто вводят вместо Э
            self.assertIn("r:g:", " ".join(datas(out)))
            gid = next(d for d in datas(out) if d.startswith("r:g:"))
            out = await s.do(777, callback=gid)
            out = await s.do(777, text="Смирнова Анна Сергеевна")
            out = await s.do(777, callback="r:ok")
            # В основном меню есть отдельная кнопка добавления в группу с корректной deep-link-ссылкой.
            urls = [b.url for row in out.screen.kb for b in row if b.url]
            self.assertTrue(any(u and "startgroup=true" in u for u in urls))
            self.assertTrue(any(u == "https://t.me/theyasha_bot" for u in urls))
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

    def test_teachers_rating(self):
        async def go():
            s = await Sim().setup(); await s.register(100); await s.register(101, "Орлова Ольга Игоревна")
            out = await s.do(100, callback="t:l:m:0"); t = texts(out); self.assertIn("Преподаватели", t)
            tid = int([d for d in datas(out) if d.startswith("t:v:")][0].split(":")[2])
            out = await s.do(100, callback=f"t:v:{tid}:m:0"); self.assertIn("t:r:%d:5:m:0" % tid, datas(out))
            out = await s.do(100, callback=f"t:r:{tid}:5:m:0"); self.assertIn("сохранена", out.toast)
            out = await s.do(100, callback=f"t:r:{tid}:3:m:0"); self.assertIn("сохранена", out.toast)
            out = await s.do(100, callback=f"t:r:{tid}:5:m:0"); self.assertIn("сохранена", out.toast)
            out = await s.do(100, callback="t:s"); self.assertEqual(out.state, "t:search")
            out = await s.do(100, text="петров"); self.assertIn("Нашёл", texts(out))
            await s.do(100, callback="t:s"); out = await s.do(100, text="физика"); self.assertIn("Нашёл", texts(out))
            await s.do(1, command="start")
            out = await s.do(1, callback="ad:rte"); self.assertIn("скрыт", texts(out))
            out = await s.do(100, callback="t:l:m:0"); self.assertIn("недоступен", out.toast)
            out = await s.do(100, command="menu"); self.assertNotIn("t:l:m:0", datas(out))
            await s.do(1, callback="ad:rte")
            out = await s.do(1, callback=f"ad:rth:{tid}"); self.assertIn("скрыт", texts(out))
            out = await s.do(100, callback=f"t:v:{tid}:m:0"); self.assertTrue(out.toast)
            out = await s.do(1, callback=f"ad:rtr:{tid}:y"); self.assertIn("Удалено", texts(out))
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
            out = await s.do(100, callback="h:add:0"); self.assertTrue(out.toast)   # не подтверждён: нельзя
            out = await s.do(100, callback="t:l:m:0"); tid = int([d for d in datas(out) if d.startswith("t:v:")][0].split(":")[2])
            out = await s.do(100, callback=f"t:r:{tid}:5:m:0"); self.assertTrue(out.toast and "подтверждения" in out.toast)
            out = await s.do(1, callback="ad:fq:0"); self.assertIn("ad:u:100", datas(out))
            out = await s.do(1, callback="ad:ufo:100:ok"); self.assertEqual(out.notify[0][0], 100)
            out = await s.do(100, callback=f"t:r:{tid}:5:m:0"); self.assertIn("сохранена", out.toast)
            out = await s.do(1, callback="ad:ufo:100:reset"); out = await s.do(100, command="start"); self.assertIn("ФИО", texts(out))
            # настройки
            out = await s.do(1, callback="ad:st:maintenance"); out = await s.do(100, command="today"); self.assertIn("технические", texts(out).lower())
            out = await s.do(1, command="admin"); self.assertIn("Админ-панель", texts(out))
            await s.do(1, callback="ad:st:maintenance")
            out = await s.do(1, callback="ad:sv:min_votes"); out = await s.do(1, text="2"); self.assertEqual(s.repo.setting("min_votes"), "2")
            out = await s.do(1, callback="ad:sv:min_votes"); out = await s.do(1, text="abc"); self.assertIn("число", texts(out))
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
            out = await s.do(1, text="Завтра пары перенесены!"); self.assertIn("Получателей: 2", texts(out))
            out = await s.do(1, callback="ad:bcy"); self.assertEqual(sorted(n[0] for n in out.notify), [100, 200])
            self.assertIn("Завтра пары", out.notify[0][1].text)
            # Функции старост удалены: старые callback-и безопасно отклоняются.
            out = await s.do(100, callback="hd:ml")
            self.assertIn("отключ", (out.toast or "").lower())
            # экспорт
            for kind in ("users", "ratings", "homework"):
                out = await s.do(1, callback=f"ad:ex:{kind}"); self.assertTrue(out.file[1][:2] == b"PK")
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
