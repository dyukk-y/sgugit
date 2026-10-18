"""Проверка склейки с Telegram на заглушке aiogram: логика отрисовки, очередей, групп, а не API aiogram."""
import asyncio, os, sys, unittest
from datetime import timedelta
from types import SimpleNamespace as NS

try:
    import aiogram  # noqa
    REAL = not hasattr(aiogram, "_Magic")
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))
    REAL = False

if not REAL:
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
    from app import timeutil as tu
    from app.bot import tg
    from app.config import Settings
    from app.db.core import Database
    from app.db.repo import Repo
    from app.db.schema import migrate
    from app.models import LessonRec
    from app.services.questions import QuestionService
    from app.services.sync import SyncService

CFG_ARGS = ("x", 1, "sqlite:///:memory:", "Asia/Novosibirsk", "u", 30, "/tmp/bk", "INFO")

class FakeBot:
    id = 999
    def __init__(self): self.calls, self.n, self.fail = [], 1000, {}
    def _rec(self, kind, **k): self.calls.append((kind, k))
    def of(self, kind): return [k for kd, k in self.calls if kd == kind]
    async def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML", reply_parameters=None):
        if self.fail.get(chat_id): raise self.fail[chat_id]
        self.n += 1; self._rec("send", chat_id=chat_id, text=text, markup=reply_markup, reply=reply_parameters)
        return Message(message_id=self.n, chat=NS(id=chat_id))
    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, parse_mode="HTML"):
        if self.fail.get("edit"): raise TelegramBadRequest(self.fail["edit"])
        self._rec("edit", chat_id=chat_id, message_id=message_id, text=text, markup=reply_markup)
    async def delete_message(self, chat_id, message_id): self._rec("delete", chat_id=chat_id, message_id=message_id)
    async def send_document(self, chat_id, doc, caption=None): self._rec("doc", chat_id=chat_id, name=doc.filename, caption=caption)
    async def download(self, doc, destination): destination.write(doc.content)
    async def get_chat_member(self, chat_id, uid): return NS(status="administrator" if uid == 77 else "member")

def user(uid): return NS(id=uid, username=f"u{uid}", full_name=f"User {uid}", is_bot=False)

def msg(bot, uid, text=None, chat_id=None, ctype="private", mid=1, document=None, reply_to=None, title="Чат"):
    m = Message(message_id=mid, from_user=user(uid), chat=NS(id=chat_id or uid, type=ctype, title=title), text=text,
                document=document, reply_to_message=reply_to)
    async def delete(): bot._rec("udelete", mid=mid)
    async def answer(t, reply_markup=None): bot._rec("answer", text=t)
    async def reply(t, parse_mode="HTML"): bot._rec("reply", text=t, to=mid); return Message(message_id=bot.n + 1, chat=m.chat)
    async def edit_text(t, reply_markup=None): bot._rec("medit", text=t)
    m.delete, m.answer, m.reply, m.edit_text = delete, answer, reply, edit_text
    return m

def handler(router, kind, name): return next(f for f, _ in router.handlers[kind] if f.__name__ == name)

@unittest.skipIf(REAL, "тест рассчитан на заглушку aiogram")
class T(unittest.TestCase):
    def test_private_and_callbacks(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); repo = Repo(db); await repo.load_settings()
            d1 = tu.iso(tu.today() + timedelta(days=1))
            async def fetch(): return [LessonRec("ИС-11", d1, 1, "08:30", "10:05", "Математика", "Иванов И. И.", "310", "лекция")]
            sync = SyncService(repo, fetch); await sync.run_once()
            bot = FakeBot(); cfg = Settings(*CFG_ARGS)
            app = tg.App(bot=bot, repo=repo, cfg=cfg, sender=tg.Sender(bot, repo, rate=1000), services={"sync": sync}, username="sgugit_bot", questions=QuestionService(repo, cfg))
            r = tg.build_router(app)
            cmd, text, doc, other = (handler(r, "message", n) for n in ("private_command", "private_text", "private_document", "private_other"))
            cb = handler(r, "callback_query", "on_callback")
            async def ans(text=None, show_alert=False): answered.append((text, show_alert))
            answered = []
            await cmd(msg(bot, 100, "/start", mid=1))
            self.assertEqual(len(bot.of("send")), 1); self.assertIn("группу", bot.of("send")[0]["text"]); self.assertEqual(bot.of("udelete")[0]["mid"], 1)
            await text(msg(bot, 100, "ис-11", mid=2))      # группы ещё нет в БД: ответ правкой экрана, без нового сообщения
            self.assertEqual(len(bot.of("send")), 1); self.assertEqual(len(bot.of("edit")), 1)
            await text(msg(bot, 100, "ис-11", mid=3))
            g = (await repo.search_groups("ис11"))[0]
            await text(msg(bot, 100, "ис-11", mid=4)); self.assertIn("r:g:", str([b.callback_data for row in bot.of("edit")[-1]["markup"].inline_keyboard for b in row]))
            await cb(CallbackQuery(id="1", data=f"r:g:{g['id']}", from_user=user(100), message=msg(bot, 100, mid=1001), answer=ans))
            answered.clear()
            await text(msg(bot, 100, "Смирнова Анна Сергеевна", mid=5))
            await cb(CallbackQuery(id="2", data="r:ok", from_user=user(100), message=msg(bot, 100, mid=1001), answer=ans))
            self.assertIn("Главное меню", bot.of("edit")[-1]["text"]); self.assertEqual(answered, [(None, False)])
            await cb(CallbackQuery(id="3", data="s:d:tom", from_user=user(100), message=msg(bot, 100, mid=1001), answer=ans))
            self.assertIn("Математика", bot.of("edit")[-1]["text"])
            await text(msg(bot, 100, "какая завтра первая пара?", mid=6)); self.assertIn("310", bot.of("edit")[-1]["text"])
            # правка не удалась (сообщение удалено): бот присылает новое и удаляет устаревшее
            bot.fail["edit"] = "message to edit not found"; n_send = len(bot.of("send"))
            await text(msg(bot, 100, "какие завтра пары", mid=7)); self.assertEqual(len(bot.of("send")), n_send + 1)
            bot.fail["edit"] = "Bad Request: message is not modified"; n_send = len(bot.of("send"))
            await text(msg(bot, 100, "какие завтра пары", mid=8)); self.assertEqual(len(bot.of("send")), n_send)   # «не изменено» не плодит сообщений
            bot.fail.pop("edit")
            # скрытая админ-команда у студента ведёт себя как обычный текст
            n = len(bot.calls); await cmd(msg(bot, 100, "/admin", mid=9)); self.assertNotIn("Админ-панель", str(bot.calls[n:]))
            # стикер и прочее удаляются
            await other(msg(bot, 100, None, mid=10)); self.assertEqual(bot.of("udelete")[-1]["mid"], 10)
            # админ: бэкап файлом, уведомления через очередь
            await cmd(msg(bot, 1, "/start", mid=20)); await cmd(msg(bot, 1, "/admin", mid=21)); self.assertIn("Админ-панель", bot.of("edit")[-1]["text"] if bot.of("edit") else "")
            await cb(CallbackQuery(id="4", data="ad:bkn", from_user=user(1), message=msg(bot, 1, mid=1002), answer=ans)); self.assertTrue(bot.of("doc")[-1]["name"].endswith(".json.gz"))
            await cb(CallbackQuery(id="5", data="ad:bc", from_user=user(1), message=msg(bot, 1, mid=1002), answer=ans))
            await cb(CallbackQuery(id="6", data="ad:bca:all", from_user=user(1), message=msg(bot, 1, mid=1002), answer=ans))
            await text(msg(bot, 1, "Всем привет", mid=22)); await cb(CallbackQuery(id="7", data="ad:bcy", from_user=user(1), message=msg(bot, 1, mid=1002), answer=ans))
            app.sender.start(); await asyncio.wait_for(app.sender.q.join() if False else asyncio.sleep(0.2), 1)
            sent_to = {c["chat_id"] for c in bot.of("send") if "Всем привет" in c["text"]}; self.assertEqual(sent_to, {100, 1})
            # заблокировавший бота помечается
            bot.fail[100] = TelegramForbiddenError("blocked"); await app.sender.enqueue(100, tg.Screen("x")); await asyncio.sleep(0.1)
            self.assertEqual((await repo.get_user(100))["bot_blocked"], 1)
            await text(msg(bot, 100, "привет", mid=30)) if False else None
            await app.sender.stop(); await db.close()
        asyncio.run(go())

    def test_import_file_and_throttle(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); repo = Repo(db); await repo.load_settings()
            async def fetch(): return []
            sync = SyncService(repo, fetch); bot = FakeBot(); cfg = Settings(*CFG_ARGS)
            app = tg.App(bot=bot, repo=repo, cfg=cfg, sender=tg.Sender(bot, repo), services={"sync": sync}, username="b")
            r = tg.build_router(app); doc = handler(r, "message", "private_document"); text = handler(r, "message", "private_text")
            cmd = handler(r, "message", "private_command"); cb = handler(r, "callback_query", "on_callback")
            async def ans(text=None, show_alert=False): pass
            await cmd(msg(bot, 1, "/admin", mid=1))
            await cb(CallbackQuery(id="1", data="ad:sch", from_user=user(1), message=msg(bot, 1, mid=50), answer=ans))
            await cb(CallbackQuery(id="2", data="ad:imp", from_user=user(1), message=msg(bot, 1, mid=50), answer=ans))
            csv = "группа;дата;пара;начало;конец;предмет\nИС-11;2026-10-20;1;08:30;10:05;Математика\n".encode()
            await doc(msg(bot, 1, None, mid=2, document=NS(file_size=len(csv), file_name="r.csv", content=csv)))
            self.assertEqual(await repo.count("lessons"), 1); self.assertIn("Загружено занятий: 1", bot.of("edit")[-1]["text"])
            big = NS(file_size=10 * 1024 * 1024, file_name="big.csv", content=b"")
            await doc(msg(bot, 1, None, mid=3, document=big)); self.assertIn("слишком большой", bot.of("edit")[-1]["text"])
            # троттлинг
            mw = r.message.middlewares[0]; hits = []
            async def h(event, data): hits.append(1)
            for _ in range(12): await mw(h, object(), {"event_from_user": user(5)})
            self.assertEqual(len(hits), 8)
            await db.close()
        asyncio.run(go())

    def test_groups(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); repo = Repo(db); await repo.load_settings()
            d1 = tu.iso(tu.today() + timedelta(days=1))
            await repo.apply_lessons([LessonRec("ИС-11", d1, 1, "10:15", "11:50", "Маркшейдерско-геодезические приборы", "Крылов А. А.", "215", "практика")], manual=False)
            await repo.replace_directory([{"name": "Крылов Андрей Андреевич", "unit": "Кафедра геодезии", "url": ""}], [{"name": "Кафедра геодезии", "room": "каб. 215", "url": ""}])
            g = (await repo.search_groups("ис11"))[0]
            await repo.ensure_user(50); await repo.update_user(50, group_id=g["id"])
            bot = FakeBot(); cfg = Settings(*CFG_ARGS); qs = QuestionService(repo, cfg)
            app = tg.App(bot=bot, repo=repo, cfg=cfg, sender=tg.Sender(bot, repo), services={}, username="sgugit_bot", questions=qs)
            r = tg.build_router(app); member = handler(r, "my_chat_member", "bot_membership"); gcmd = handler(r, "message", "group_command")
            gtext = handler(r, "message", "group_text"); chat_cb = handler(r, "callback_query", "chat_settings_cb")
            ev = lambda frm, old, new, cid=-100: ChatMemberUpdated(chat=NS(id=cid, type="supergroup", title="ИС-11"), from_user=user(frm),
                                                                    old_chat_member=NS(status=old), new_chat_member=NS(status=new))
            await member(ev(50, "left", "member"))
            chat = await repo.get_chat(-100); self.assertEqual(chat["group_id"], g["id"]); self.assertIn("привязан к группе", bot.of("send")[-1]["text"])
            await member(ev(60, "left", "member", -200)); self.assertIsNone((await repo.get_chat(-200))["group_id"]); self.assertIn("зарегистрироваться", bot.of("send")[-1]["text"])
            # Если добавивший зарегистрировался уже после добавления бота, /settings привязывает его группу.
            await repo.ensure_user(60); await repo.update_user(60, group_id=g["id"])
            await gcmd(msg(bot, 60, "/settings", chat_id=-200, ctype="supergroup", mid=4))
            self.assertEqual((await repo.get_chat(-200))["group_id"], g["id"])
            # Команды помощи и короткие псевдонимы доступны прямо в группе.
            await gcmd(msg(bot, 51, "/help", chat_id=-100, ctype="supergroup", mid=4))
            self.assertIn("/tomorrow", bot.of("reply")[-1]["text"])
            await gcmd(msg(bot, 51, "/schedule", chat_id=-100, ctype="supergroup", mid=4))
            self.assertIn("Воскресенье", bot.of("reply")[-1]["text"])
            await gcmd(msg(bot, 51, "/homework", chat_id=-100, ctype="supergroup", mid=4))
            self.assertIn("заданий", bot.of("reply")[-1]["text"].lower())
            await repo.update_chat(-100, autodelete_min=0)
            await gcmd(msg(bot, 51, "/today", chat_id=-100, ctype="supergroup", mid=5)); self.assertTrue(bot.of("reply")); 
            await gcmd(msg(bot, 51, "/tomorrow@sgugit_bot", chat_id=-100, ctype="supergroup", mid=6)); self.assertIn("Маркшейдерско", bot.of("reply")[-1]["text"])
            n = len(bot.of("reply")); await gcmd(msg(bot, 51, "/tomorrow@other_bot", chat_id=-100, ctype="supergroup", mid=7)); self.assertEqual(len(bot.of("reply")), n)
            # режим «по упоминанию» (по умолчанию): без обращения молчит, с обращением отвечает
            n = len(bot.of("reply")); await gtext(msg(bot, 51, "какие завтра пары?", chat_id=-100, ctype="supergroup", mid=8)); self.assertEqual(len(bot.of("reply")), n)
            await gtext(msg(bot, 51, "@sgugit_bot где найти препода Крылова", chat_id=-100, ctype="supergroup", mid=9)); self.assertIn("Кафедра геодезии", bot.of("reply")[-1]["text"])
            # настройки чата: чужой запрещено, tg-админ можно
            async def ans(text=None, show_alert=False): bot._rec("answer", text=text)
            await gcmd(msg(bot, 52, "/settings", chat_id=-100, ctype="supergroup", mid=10)); self.assertIn("доступны добавившему", bot.of("reply")[-1]["text"])
            await gcmd(msg(bot, 77, "/settings", chat_id=-100, ctype="supergroup", mid=11)); self.assertIn("Настройки чата", bot.of("answer")[-1]["text"])
            await chat_cb(CallbackQuery(id="1", data="cs:-100:sm", from_user=user(52), message=msg(bot, 52, chat_id=-100, ctype="supergroup"), answer=ans))
            self.assertEqual((await repo.get_chat(-100))["smart_mode"], "mention")
            for _ in range(2): await chat_cb(CallbackQuery(id="2", data="cs:-100:sm", from_user=user(77), message=msg(bot, 77, chat_id=-100, ctype="supergroup"), answer=ans))
            self.assertEqual((await repo.get_chat(-100))["smart_mode"], "active")
            # активный режим: вопрос без обращения ставится в ожидание, ответ человека его снимает, иначе бот отвечает реплаем
            n = len(bot.of("reply")); await gtext(msg(bot, 51, "а завтра будет мгп?", chat_id=-100, ctype="supergroup", mid=20))
            self.assertEqual(len(bot.of("reply")), n); self.assertEqual(len(await repo.pending_for_chat(-100)), 1)
            await gtext(msg(bot, 53, "какие пары завтра?", chat_id=-100, ctype="supergroup", mid=21))
            await gtext(msg(bot, 54, "да, в 10:15", chat_id=-100, ctype="supergroup", mid=22, reply_to=NS(message_id=21, from_user=user(53))))
            self.assertEqual(len(await repo.pending_for_chat(-100)), 1)
            self.assertEqual(await tg.answer_due_questions(app), 0)
            await repo.db.execute("UPDATE pending_questions SET due_at = 1")
            self.assertEqual(await tg.answer_due_questions(app), 1)
            last = bot.of("send")[-1]; self.assertEqual(last["chat_id"], -100); self.assertEqual(last["reply"].message_id, 20)
            self.assertIn("Пока никто не ответил", last["text"]); self.assertIn("10:15–11:50", last["text"]); self.assertIn("215", last["text"])
            # бот удалён из чата
            await member(ev(50, "member", "kicked")); self.assertEqual((await repo.get_chat(-100))["active"], 0)
            await db.close()
        asyncio.run(go())

if __name__ == "__main__":
    unittest.main()
