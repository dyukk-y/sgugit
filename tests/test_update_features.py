"""Проверки новых возможностей: закреп сводки, отключение уведомлений об изменениях, бэкап в одном сообщении,
кнопки для телефона, антиспам и очередь админа."""
import asyncio, os, sys, unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

try:
    import aiogram  # noqa
    REAL = not hasattr(aiogram, "_Magic")
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))
    REAL = False

from app import timeutil as tu
from app.bot import logic_chat as lc, logic_user
from app.bot.core import Btn, Ctx, Screen
from app.config import Settings
from app.db.core import Database
from app.db.repo import Repo, ApplyResult
from app.db.schema import migrate
from app.models import LessonRec
from app.services.notifier import Notifier

CFG = Settings("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "u", 30, "/tmp/bk_test", "INFO")


def at(h, m, day=14): return datetime(2026, 10, day, h, m, tzinfo=tu.tz())
def L(day, num, subj, start, end): return LessonRec("ИС-11", day, num, start, end, subj, "Иванов И. И.", "310", "лекция")


async def make_repo():
    db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db)
    r = Repo(db); await r.load_settings()
    return db, r


class Notif(unittest.TestCase):
    def test_pin_until_last_lesson_and_toggles(self):
        async def go():
            db, r = await make_repo()
            await r.apply_lessons([L("2026-10-15", 1, "Химия", "09:00", "10:35"), L("2026-10-15", 2, "Физика", "10:45", "12:20")], manual=False)
            g = (await r.search_groups("ис11"))[0]["id"]
            await r.upsert_chat(-5, "чат", g, 1); await r.update_chat(-5, evening_on=1)
            sent, pinned = [], []
            async def send(cid, scr): sent.append(cid)
            async def pin(cid, scr, unpin_at): pinned.append((cid, scr.text, unpin_at)); return True
            n = Notifier(r, send, pin=pin)
            await n.tick(at(20, 0))
            self.assertEqual(sent, []); self.assertEqual(len(pinned), 1)
            cid, text, unpin_at = pinned[0]
            self.assertEqual(cid, -5); self.assertIn("Закреплено до окончания последней пары (12:20)", text)
            self.assertEqual(unpin_at, int(datetime(2026, 10, 15, 12, 20, tzinfo=tu.tz()).timestamp()))
            # закреп выключен в настройках чата: обычная отправка
            await r.update_chat(-5, pin_on=0)
            await n.tick(at(20, 0, day=14))  # дубль в тот же день не шлём
            self.assertEqual(len(pinned), 1)
            await db.execute("DELETE FROM notif_log")
            await n.tick(at(20, 0)); self.assertEqual(sent, [-5]); self.assertEqual(len(pinned), 1)
            # если pin не удался (False) — запасная обычная отправка
            await r.update_chat(-5, pin_on=1); await db.execute("DELETE FROM notif_log"); sent.clear()
            async def bad_pin(cid, scr, unpin_at): return False
            await Notifier(r, send, pin=bad_pin).tick(at(20, 0)); self.assertEqual(sent, [-5])
            await db.close()
        asyncio.run(go())

    def test_changes_can_be_disabled(self):
        async def go():
            db, r = await make_repo()
            fut = tu.iso(tu.today() + timedelta(days=3))  # изменения фиксируются только для будущих дней
            await r.apply_lessons([L(fut, 1, "Химия", "08:30", "10:05")], manual=False)
            g = (await r.search_groups("ис11"))[0]["id"]
            for uid in (1, 2):
                await r.ensure_user(uid); await r.update_user(uid, group_id=g)
            await r.update_user(2, n_changes=0)
            await r.upsert_chat(-5, "чат", g, 1); await r.upsert_chat(-6, "чат2", g, 1); await r.update_chat(-6, changes_on=0)
            sent = []
            async def send(cid, scr): sent.append(cid)
            n = Notifier(r, send)
            res = await r.apply_lessons([L(fut, 1, "Химия", "09:00", "10:35")], manual=False)
            self.assertEqual(await n.notify_changes(res), 2); self.assertEqual(sorted(sent), [-5, 1])
            # главный выключатель
            await r.set_setting("notify_changes", "0"); sent.clear()
            res = await r.apply_lessons([L(fut, 1, "Химия", "10:00", "11:35")], manual=False)
            self.assertEqual(await n.notify_changes(res), 0); self.assertEqual(sent, [])
            await db.close()
        asyncio.run(go())


class Screens(unittest.TestCase):
    def test_chat_settings_toggles_and_layout(self):
        async def go():
            db, r = await make_repo()
            g = await r.get_or_create_group("ИС-11")
            chat = await r.upsert_chat(-7, "Чат", g["id"], 5); u5 = await r.ensure_user(5)
            for act, col in (("ch", "changes_on"), ("pn", "pin_on")):
                self.assertEqual(chat[col], 1)
                self.assertIsNone(await lc.apply(r, chat, u5, act)); chat = await r.get_chat(-7); self.assertEqual(chat[col], 0)
                await lc.apply(r, chat, u5, act); chat = await r.get_chat(-7); self.assertEqual(chat[col], 1)
            scr = await lc.screen(r, chat)
            self.assertIn("Настройки чата", scr.text)
            self.assertTrue(all(len(row) == 1 for row in scr.kb))  # одна настройка = одна кнопка на всю ширину
            labels = " ".join(b.text for row in scr.kb for b in row)
            self.assertIn("Изменения расписания", labels); self.assertIn("Закреп", labels)
            await db.close()
        asyncio.run(go())

    def test_user_notification_screen_is_phone_friendly(self):
        async def go():
            db, r = await make_repo()
            await r.ensure_user(10); u = await r.get_user(10)
            ctx = Ctx(r, CFG, u)
            scr = await logic_user.notif_screen(ctx)
            for row in scr.kb:
                self.assertLessEqual(len(row), 2, [b.text for b in row])
            self.assertTrue(any("Изменения в расписании: ВКЛ" in b.text for row in scr.kb for b in row))
            out = await logic_user.on_cb_me(ctx, ["n", "ch", "t"])
            self.assertTrue(any("Изменения в расписании: ВЫКЛ" in b.text for row in out.screen.kb for b in row))
            await db.close()
        asyncio.run(go())


@unittest.skipIf(REAL, "тест рассчитан на заглушку aiogram")
class TgLayer(unittest.TestCase):
    def test_mobile_rows(self):
        from app.bot import tg
        kb = [[Btn("◀", "a"), Btn("2/5", "noop"), Btn("▶", "b")],
              [Btn("🏠 Меню", "m"), Btn("◀ Назад", "x")],
              [Btn("🤖 Открыть личный бот", "u"), Btn("➕ Добавить в другой чат", "v"), Btn("⚙️ Настройки чата", "w")]]
        rows = tg._mobile_rows(kb)
        self.assertEqual([len(r) for r in rows], [3, 2, 1, 1, 1])

    def test_antispam_admin_exempt_and_decay(self):
        from app.bot import tg
        async def go():
            calls = []
            async def handler(event, data): calls.append(1); return "ok"
            mw = tg.AntiSpamMiddleware({1})
            ev = NS(chat=NS(type="private"), text="/start")
            for _ in range(30):
                await mw(handler, ev, {"event_from_user": NS(id=1)})
            self.assertEqual(len(calls), 30)  # главный админ не ограничивается
            # обычный пользователь: мьют есть, но страйки обнуляются через 30 минут
            mw2 = tg.AntiSpamMiddleware(set())
            async def ack(*a, **k): return None
            mw2._ack = ack
            u = NS(id=5)
            for i in range(10):
                await mw2(handler, NS(chat=NS(type="private"), text=f"t{i}"), {"event_from_user": u})
            key = (5, "private"); self.assertEqual(mw2.strikes[key], 1)
            mw2.strike_at[key] -= 3600; mw2.muted_until[key] = 0.0; mw2.events[key].clear()
            for i in range(10):
                await mw2(handler, NS(chat=NS(type="private"), text=f"z{i}"), {"event_from_user": u})
            self.assertEqual(mw2.strikes[key], 1)  # снова первое нарушение, а не вечные 10 минут тишины
        asyncio.run(go())

    def test_stuck_action_does_not_silence_user(self):
        from app.bot import tg
        async def go():
            db, r = await make_repo()
            app = tg.App(bot=NS(), repo=r, cfg=CFG, sender=None, services={}, username="b")
            tg.LOCK_WAIT_SEC = 0.2
            await app.locks[1].acquire()  # «зависшее» предыдущее действие
            out = await tg.run_process(app, NS(id=1, username="a", full_name="A"), command="start")
            self.assertIn("ещё выполняется", out.screen.text)
            app.locks[1].release()
            out = await tg.run_process(app, NS(id=1, username="a", full_name="A"), command="admin")
            self.assertIn("Админ-панель", out.screen.text)
            await db.close()
        asyncio.run(go())

    def test_backup_single_message_and_pin(self):
        from app.bot import background, tg
        from aiogram.exceptions import TelegramBadRequest
        class Bot:
            id = 9
            def __init__(self): self.docs, self.edits, self.pins, self.fail_edit, self.n = [], [], [], False, 100
            async def send_document(self, chat_id, doc, caption=None): self.n += 1; self.docs.append(caption); return NS(message_id=self.n)
            async def edit_message_media(self, chat_id, message_id, media):
                if self.fail_edit: raise TelegramBadRequest("message to edit not found")
                self.edits.append((message_id, media.caption))
            async def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"): self.n += 1; return NS(message_id=self.n)
            async def pin_chat_message(self, chat_id, message_id, disable_notification=False): self.pins.append((chat_id, message_id, disable_notification))
            async def unpin_chat_message(self, chat_id, message_id=None): self.pins.append(("unpin", chat_id, message_id))
        async def go():
            db, r = await make_repo(); bot = Bot()
            cfg = Settings("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "u", 30, "/tmp/bk_test_upd", "INFO")
            app = tg.App(bot=bot, repo=r, cfg=cfg, sender=tg.Sender(bot, r), services={}, username="b")
            await background.push_backup(app, "первый запуск")
            self.assertEqual((len(bot.docs), len(bot.edits)), (1, 0)); mid = int(r.setting("backup_msg_id")); self.assertTrue(mid)
            for i in range(3): await background.push_backup(app, "после изменений")
            self.assertEqual((len(bot.docs), len(bot.edits)), (1, 3))  # ни одного нового сообщения: только правки
            self.assertTrue(all(m == mid for m, _ in bot.edits)); self.assertIn("первый запуск", bot.edits[-1][1]); self.assertIn("после изменений", bot.edits[-1][1])
            bot.fail_edit = True; await background.push_backup(app, "ежедневная")  # сообщение удалили: шлём новое и правим его дальше
            self.assertEqual(len(bot.docs), 2); self.assertNotEqual(int(r.setting("backup_msg_id")), mid)
            # закреп: отправка + запись в очередь открепления
            ok = await app.sender.send_pinned(-5, Screen("сводка"), tu.now_ts() + 3600)
            self.assertTrue(ok); self.assertEqual(bot.pins[-1][2], True)
            self.assertEqual(len(await r.due_pins(tu.now_ts())), 0); self.assertEqual(len(await r.due_pins(tu.now_ts() + 7200)), 1)
            await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
