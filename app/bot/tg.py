"""Слой Telegram (aiogram 3): отправка, отрисовка экранов, обработчики. Вся логика живёт в router/logic_*."""
from __future__ import annotations

from app import timeutil as tu

import asyncio
import io
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyParameters)

from app.bot import logic_chat, router as logic_router, runtime
from app.bot.core import Ctx, Kb, Out, Screen
from app.config import Settings
from app.db.repo import Repo
from app.services import format as fm

log = logging.getLogger(__name__)
MAX_TEXT = 4096
MAX_UPLOAD = 5 * 1024 * 1024
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_tags(text: str) -> str:
    import html

    return html.unescape(_TAG_RE.sub("", text))


def to_markup(kb: Kb | None) -> InlineKeyboardMarkup | None:
    if not kb:
        return None
    rows = []
    for row in kb:
        btns = []
        for b in row:
            if b.url:
                btns.append(InlineKeyboardButton(text=b.text, url=b.url))
            else:
                data = b.data or "noop"
                if len(data.encode("utf-8")) > 64:
                    log.error("callback_data длиннее 64 байт: %s", data)
                    data = "noop"
                btns.append(InlineKeyboardButton(text=b.text, callback_data=data))
        if btns:
            rows.append(btns)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _is(e: Exception, *needles: str) -> bool:
    s = str(e).lower()
    return any(n in s for n in needles)


class Sender:
    """Очередь исходящих сообщений с ограничением скорости (лимиты Telegram ~30 сообщений/сек)."""

    def __init__(self, bot: Bot, repo: Repo, rate: float = 20.0):
        self.bot, self.repo, self.rate = bot, repo, rate
        self.q: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run(), name="sender")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, chat_id: int, screen: Screen) -> None:
        self.q.put_nowait((chat_id, screen, 0))

    async def _run(self) -> None:
        while True:
            chat_id, screen, attempt = await self.q.get()
            try:
                await self._send(chat_id, screen)
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 1)
                if attempt < 3:
                    self.q.put_nowait((chat_id, screen, attempt + 1))
            except TelegramForbiddenError:
                await self._mark_unreachable(chat_id)
            except TelegramBadRequest as e:
                if _is(e, "chat not found", "user is deactivated", "bot was blocked", "peer_id_invalid"):
                    await self._mark_unreachable(chat_id)
                else:
                    log.warning("Не отправлено %s: %s", chat_id, e)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - рассылка не должна падать из-за одного получателя
                log.exception("Ошибка отправки %s", chat_id)
            await asyncio.sleep(1.0 / self.rate)

    async def _send(self, chat_id: int, screen: Screen) -> None:
        text = screen.text[:MAX_TEXT]
        markup = to_markup(screen.kb) if chat_id > 0 else None
        try:
            await self.bot.send_message(chat_id, text, reply_markup=markup)
        except TelegramBadRequest as e:
            if _is(e, "can't parse entities"):
                await self.bot.send_message(chat_id, strip_tags(text)[:MAX_TEXT], reply_markup=markup, parse_mode=None)
            else:
                raise

    async def _mark_unreachable(self, chat_id: int) -> None:
        try:
            if chat_id > 0:
                await self.repo.update_user(chat_id, bot_blocked=1)
            else:
                await self.repo.update_chat(chat_id, active=0)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось пометить получателя недоступным")


@dataclass
class App:
    bot: Bot
    repo: Repo
    cfg: Settings
    sender: Sender
    services: dict[str, Any]
    username: str
    questions: Any = None
    anchors: dict[int, int] = field(default_factory=dict)
    locks: dict[int, asyncio.Lock] = field(default_factory=lambda: defaultdict(asyncio.Lock))
    last_group_answer: dict[tuple[int, str], float] = field(default_factory=dict)
    tasks: set = field(default_factory=set)
    processed_private_messages: set[tuple[int, int]] = field(default_factory=set)

    def spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)


async def safe_delete(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except TelegramAPIError:
        pass


async def _edit(app: App, chat_id: int, message_id: int, scr: Screen) -> bool:
    text = scr.text[:MAX_TEXT]
    markup = to_markup(scr.kb)
    try:
        await app.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        return True
    except TelegramBadRequest as e:
        if _is(e, "message is not modified"):
            return True
        if _is(e, "can't parse entities"):
            try:
                await app.bot.edit_message_text(strip_tags(text), chat_id=chat_id, message_id=message_id,
                                                reply_markup=markup, parse_mode=None)
                return True
            except TelegramBadRequest:
                return False
        return False


async def render(app: App, chat_id: int, out: Out, source: Message | None = None) -> None:
    """Показывает экран: правит существующее сообщение бота, а не засоряет чат новыми."""
    scr = out.screen
    if scr is None:
        return
    target = None
    if not out.new_message:
        target = source.message_id if source is not None else app.anchors.get(chat_id)
    if target is not None and await _edit(app, chat_id, target, scr):
        app.anchors[chat_id] = target
        return
    old = app.anchors.get(chat_id)
    try:
        msg = await app.bot.send_message(chat_id, scr.text[:MAX_TEXT], reply_markup=to_markup(scr.kb))
    except TelegramBadRequest as e:
        if _is(e, "can't parse entities"):
            msg = await app.bot.send_message(chat_id, strip_tags(scr.text)[:MAX_TEXT], reply_markup=to_markup(scr.kb),
                                             parse_mode=None)
        else:
            raise
    app.anchors[chat_id] = msg.message_id
    for stale in {old, source.message_id if source is not None else None} - {None, msg.message_id}:
        try:
            await app.bot.delete_message(chat_id, stale)
        except TelegramAPIError:
            pass


async def deliver_side_effects(app: App, chat_id: int, out: Out) -> None:
    for uid, scr in out.notify:
        await app.sender.enqueue(uid, scr)
    for uid, scr, delay in out.notify_timed:
        try:
            msg = await app.bot.send_message(uid, scr.text[:MAX_TEXT], reply_markup=to_markup(scr.kb), parse_mode="HTML")
        except TelegramBadRequest as e:
            if _is(e, "can't parse entities"):
                msg = await app.bot.send_message(uid, strip_tags(scr.text)[:MAX_TEXT], reply_markup=to_markup(scr.kb), parse_mode=None)
            else:
                raise
        await app.repo.db.execute(
            "INSERT INTO scheduled_deletions (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
            uid, msg.message_id, tu.now_ts() + max(60, int(delay)))
    for uid, file_id, kind, caption in out.notify_media:
        try:
            if kind == "photo":
                await app.bot.send_photo(uid, file_id, caption=(caption or None), parse_mode="HTML")
            else:
                await app.bot.send_document(uid, file_id, caption=(caption or None), parse_mode="HTML")
        except TelegramAPIError:
            log.info("Не удалось доставить медиа-рассылку пользователю %s", uid)
        await asyncio.sleep(0.05)  # ограничиваем скорость массовой отправки медиа
    if out.media:
        file_id, kind, caption = out.media
        try:
            if kind == "photo":
                await app.bot.send_photo(chat_id, file_id, caption=(caption or None))
            else:
                await app.bot.send_document(chat_id, file_id, caption=(caption or None))
        except TelegramAPIError:
            log.exception("Не удалось отправить вложение задания")
    if out.file:
        name, blob, caption = out.file
        try:
            await app.bot.send_document(chat_id, BufferedInputFile(blob, filename=name), caption=caption)
        except TelegramAPIError:
            log.exception("Не удалось отправить файл")


async def run_process(app: App, user, **kw) -> Out:
    async with app.locks[user.id]:
        return await runtime.process(app.repo, app.cfg, user.id, user.username, user.full_name,
                                     services=app.services, bot_username=app.username, **kw)


def _claim_private_message(app: App, message: Message) -> bool:
    """Защита от повторной обработки одного и того же апдейта двумя обработчиками."""
    key = (message.chat.id, message.message_id)
    if key in app.processed_private_messages:
        return False
    app.processed_private_messages.add(key)
    if len(app.processed_private_messages) > 5000:
        # Достаточно сохранить недавние ID; старые апдейты Telegram повторно не присылает бесконечно.
        app.processed_private_messages.clear()
        app.processed_private_messages.add(key)
    return True


class AntiSpamMiddleware(BaseMiddleware):
    """Многоуровневая защита от флудa: лимиты, повторы и временное охлаждение.

    Счётчики живут в памяти процесса; это защита от пользовательского флуда,
    а не замена Telegram rate limits. Обычные нажатия кнопок имеют отдельный лимит.
    """

    def __init__(self):
        self.events: dict[tuple[int, str], deque] = defaultdict(deque)
        self.repeats: dict[tuple[int, str], deque] = defaultdict(deque)
        self.muted_until: dict[tuple[int, str], float] = {}
        self.strikes: dict[tuple[int, str], int] = defaultdict(int)
        self.warned_at: dict[tuple[int, str], float] = {}
        self.last_signature: dict[tuple[int, str], str] = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        chat = getattr(event, "chat", None)
        if chat is None:
            msg = getattr(event, "message", None)
            chat = getattr(msg, "chat", None)
        chat_type = getattr(chat, "type", "private")
        scope = "callback" if isinstance(event, CallbackQuery) else (
            "group" if chat_type in ("group", "supergroup") else "private")
        key = (user.id, scope)
        now = time.monotonic()

        # Пропускаем события во время временного ограничения.
        muted = self.muted_until.get(key, 0.0)
        if now < muted:
            await self._ack(event, key, now, muted - now)
            return None
        if muted:
            self.muted_until.pop(key, None)

        q = self.events[key]
        while q and now - q[0] > 10.0:
            q.popleft()

        # Кнопки лимитируются отдельно, чтобы не мешать обычной навигации.
        if scope == "callback":
            limit, window = 18, 5.0
        elif scope == "group":
            limit, window = 7, 5.0
        else:
            limit, window = 8, 5.0
        recent = sum(1 for stamp in q if now - stamp <= window)

        signature = ""
        if scope != "callback":
            text = getattr(event, "text", None) or getattr(event, "caption", None) or ""
            if text:
                signature = " ".join(text.casefold().split())[:300]
            elif getattr(event, "photo", None):
                signature = "[photo]"
            elif getattr(event, "document", None):
                signature = "[document]:" + str(getattr(event.document, "file_name", ""))
            if signature:
                rq = self.repeats[key]
                while rq and now - rq[0][0] > 20.0:
                    rq.popleft()
                same = sum(1 for _, sig in rq if sig == signature)
                rq.append((now, signature))
                repeat_spam = same >= 2
            else:
                repeat_spam = False
        else:
            repeat_spam = False

        if recent >= limit or repeat_spam:
            self.strikes[key] += 1
            cooldown = (10.0 if self.strikes[key] == 1 else
                        60.0 if self.strikes[key] == 2 else 600.0)
            self.muted_until[key] = now + cooldown
            await self._ack(event, key, now, cooldown, warn=True)
            log.info("Антиспам: user=%s scope=%s cooldown=%ss reason=%s",
                     user.id, scope, int(cooldown), "repeat" if repeat_spam else "rate")
            return None

        q.append(now)
        if len(self.events) > 20000:
            # Очистка ограничивает расход памяти на очень больших ботах.
            self.events.clear()
            self.repeats.clear()
            self.warned_at.clear()
        return await handler(event, data)

    async def _ack(self, event, key, now: float, remaining: float, warn: bool = False) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer("Слишком часто. Подождите немного.", show_alert=False)
            except TelegramAPIError:
                pass
            return
        # Не засоряем групповой чат предупреждениями; личному пользователю
        # показываем предупреждение не чаще раза в 15 секунд.
        chat = getattr(event, "chat", None)
        if not warn or getattr(chat, "type", "private") != "private":
            return
        if now - self.warned_at.get(key, 0.0) < 15.0:
            return
        self.warned_at[key] = now
        try:
            await event.answer(
                f"🛡️ Сработала защита от спама. Подождите {max(1, int(remaining))} сек. "
                "и продолжайте пользоваться ботом спокойным темпом."
            )
        except (TelegramAPIError, AttributeError):
            pass


def _cmd_parts(text: str) -> tuple[str, str]:
    head, _, args = text.partition(" ")
    name = head[1:].split("@")[0].lower()
    return name, args.strip()


def build_router(app: App) -> Router:
    r = Router(name="main")
    r.message.outer_middleware(AntiSpamMiddleware())
    r.callback_query.outer_middleware(AntiSpamMiddleware())
    private = F.chat.type == "private"
    group = F.chat.type.in_({"group", "supergroup"})

    # ---------------- личные сообщения ----------------
    @r.message(private, F.text.startswith("/"))
    async def private_command(message: Message) -> None:
        if message.from_user is None or not _claim_private_message(app, message):
            return
        name, args = _cmd_parts(message.text or "")
        out = await run_process(app, message.from_user, command=name, args=args)
        if out.screen is None and not out.file and not out.notify and not out.notify_timed and not out.toast:
            # неизвестная или скрытая команда (например, /admin у обычного студента): как обычный текст
            out = await run_process(app, message.from_user, text=message.text or "")
        # Сначала гарантированно показываем ответ, и только потом удаляем /start или другую команду.
        await render(app, message.chat.id, out)
        await deliver_side_effects(app, message.chat.id, out)
        await safe_delete(message)

    @r.message(private, F.text)
    async def private_text(message: Message) -> None:
        if message.from_user is None or not _claim_private_message(app, message):
            return
        out = await run_process(app, message.from_user, text=message.text or "")
        await render(app, message.chat.id, out)
        await deliver_side_effects(app, message.chat.id, out)
        await safe_delete(message)

    @r.message(private, F.photo)
    async def private_photo(message: Message) -> None:
        if message.from_user is None or not message.photo:
            return
        out = await run_process(app, message.from_user, attachment_file_id=message.photo[-1].file_id,
                                attachment_kind="photo", attachment_caption=message.caption or "")
        await render(app, message.chat.id, out)
        await deliver_side_effects(app, message.chat.id, out)
        await safe_delete(message)

    @r.message(private, F.document)
    async def private_document(message: Message) -> None:
        if message.from_user is None or message.document is None:
            return
        doc = message.document
        if (doc.file_size or 0) > MAX_UPLOAD:
            out = Out(screen=Screen("Файл слишком большой (максимум 5 МБ)."))
        else:
            buf = io.BytesIO()
            try:
                await app.bot.download(doc, destination=buf)
                out = await run_process(app, message.from_user, document=(doc.file_name or "file", buf.getvalue()), attachment_file_id=getattr(doc, "file_id", None))
            except TelegramAPIError:
                out = Out(screen=Screen("Не удалось скачать файл, попробуйте ещё раз."))
        await render(app, message.chat.id, out)
        await deliver_side_effects(app, message.chat.id, out)
        await safe_delete(message)

    @r.message(private)
    async def private_other(message: Message) -> None:
        await safe_delete(message)  # стикеры, фото и прочее: держим чат чистым

    # ---------------- кнопки ----------------
    @r.callback_query(F.data.startswith("cs:"))
    async def chat_settings_cb(cb: CallbackQuery) -> None:
        try:
            await _chat_settings_action(app, cb)
        finally:
            try:
                await cb.answer()
            except TelegramAPIError:
                pass

    @r.callback_query()
    async def on_callback(cb: CallbackQuery) -> None:
        msg = cb.message
        if cb.data is None or not isinstance(msg, Message) or msg.chat.type != "private":
            await _safe_answer(cb)
            return
        try:
            out = await run_process(app, cb.from_user, callback=cb.data)
        except Exception:
            await _safe_answer(cb, "Что-то пошло не так, попробуйте ещё раз", True)
            raise
        await render(app, msg.chat.id, out, source=msg)
        await deliver_side_effects(app, msg.chat.id, out)
        await _safe_answer(cb, out.toast, out.alert)

    # ---------------- группы ----------------
    @r.my_chat_member()
    async def bot_membership(event: ChatMemberUpdated) -> None:
        if event.chat.type not in ("group", "supergroup"):
            return
        new = getattr(event.new_chat_member.status, "value", event.new_chat_member.status)
        old = getattr(event.old_chat_member.status, "value", event.old_chat_member.status)
        if new in ("left", "kicked"):
            chat = await app.repo.get_chat(event.chat.id)
            if chat:
                await app.repo.update_chat(event.chat.id, active=0)
            return
        if old in ("left", "kicked") and new in ("member", "administrator"):
            adder = await app.repo.get_user(event.from_user.id) if event.from_user else None
            gid = adder.get("group_id") if adder else None
            chat = await app.repo.upsert_chat(event.chat.id, event.chat.title, gid, event.from_user.id if event.from_user else None)
            group = await app.repo.get_group(chat.get("group_id"))
            if group:
                text = (f"👋 <b>Бот расписания СГУГиТ подключён!</b>\n"
                        f"Чат привязан к группе <b>{fm.esc(group['name'])}</b>\n\n"
                        "📅 <b>Что умею</b>\n"
                        "• Расписание на сегодня, завтра и всю неделю (с типом занятия: лекция, практика, лабораторная).\n"
                        "• Следующая пара и время до неё.\n"
                        "• Задания группы.\n"
                        "• Поиск преподавателя и подсказки по расписанию.\n\n"
                        "💬 Ответьте на сообщение бота или упомяните его и задайте вопрос обычными словами: "
                        "«какие завтра пары?», «что у нас на неделе?», «какая следующая пара?».\n\n"
                        "⚙️ Настройки и привязка группы доступны в личном боте. "
                        "Команды /today, /tomorrow, /week, /next и /hw оставлены как запасной способ.\n\n"
                        "ℹ️ В стандартном режиме Telegram бот видит команды, упоминания и ответы на его сообщения. "
                        "Чтобы понимать любые сообщения чата, отключите Group Privacy в @BotFather или выдайте боту права администратора.")
            else:
                text = ("👋 <b>Бот расписания СГУГиТ добавлен!</b>\n\n"
                        "Чтобы включить расписание, привяжите к чату учебную группу. "
                        "Откройте личный бот кнопкой ниже, чтобы зарегистрироваться, затем вернитесь в чат. "
                        "Если добавивший уже выбрал группу, привязка выполнится автоматически.\n\n"
                        "После настройки бот покажет расписание на день и неделю, тип занятия, следующую пару "
                        "и задания. Можно задавать вопросы обычными словами, отвечая на сообщение бота.\n\n"
                        "Команды /settings, /today, /tomorrow, /week, /next и /hw остаются запасным вариантом.")
            try:
                welcome_kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🤖 Открыть личный бот", url=f"https://t.me/{app.username}?start=from_group"),
                    InlineKeyboardButton(text="➕ Добавить в другой чат", url=f"https://t.me/{app.username}?startgroup=true"),
                    InlineKeyboardButton(text="⚙️ Настройки чата", callback_data=f"cs:{event.chat.id}:open")
                ]])
                await app.bot.send_message(event.chat.id, text, reply_markup=welcome_kb)
            except TelegramAPIError:
                log.warning("Не удалось отправить приветствие в чат %s", event.chat.id)

    @r.message(group, F.text.startswith("/"))
    async def group_command(message: Message) -> None:
        if message.from_user is None or message.from_user.is_bot:
            return
        name, _ = _cmd_parts(message.text or "")
        # команда адресована другому боту?
        head = (message.text or "").split(" ")[0]
        if "@" in head and head.split("@")[1].lower() != app.username.lower():
            return
        chat = await app.repo.get_chat(message.chat.id)
        if name not in {"start", "help"} and app.repo.flag("group_require_start"):
            user_row = await app.repo.get_user(message.from_user.id)
            if not user_row or not user_row.get("private_started"):
                link = f"https://t.me/{app.username}?start=group_access"
                await _reply_group(app, message,
                    "Чтобы пользоваться ботом в группе, сначала откройте его в личных сообщениях и нажмите /start.\n"
                    f"👉 <a href=\"{link}\">Запустить бота</a>", chat)
                return
        if name == "settings":
            await _send_chat_settings(app, message, chat)
            return
        if name in {"start", "help"}:
            chat = await _bind_adder_group_if_ready(app, chat, message.from_user.id)
            if chat and chat.get("group_id"):
                g = await app.repo.get_group(chat["group_id"])
                group_name = fm.esc(g["name"]) if g else "неизвестная группа"
                text = (f"🤖 <b>Бот расписания СГУГиТ</b>\nГруппа чата: <b>{group_name}</b>\n\n"
                        "📅 /today — сегодня\n🌅 /tomorrow — завтра\n🗓 /week — неделя\n"
                        "⏭ /next — следующая пара\n📝 /hw — задания\n⚙️ /settings — настройки\n\n"
                        f"Можно написать @{app.username} и задать вопрос обычным языком.")
            else:
                text = ("🤖 <b>Бот расписания СГУГиТ</b>\nЧат пока не привязан к учебной группе.\n"
                        "Откройте /settings и нажмите «Привязать к моей группе».\n"
                        "Если вы добавили бота, но ещё не зарегистрированы, сначала откройте бота в личных сообщениях "
                        "и пройдите регистрацию.")
            await _reply_group(app, message, text, chat)
            return
        if name == "group":
            chat = await _bind_adder_group_if_ready(app, chat, message.from_user.id)
            g = await app.repo.get_group(chat.get("group_id")) if chat and chat.get("group_id") else None
            if g:
                text = f"👥 Группа этого чата: <b>{fm.esc(g['name'])}</b>\nНастройки: /settings"
            else:
                text = "Группа чата пока не выбрана. Откройте /settings и привяжите свою группу."
            await _reply_group(app, message, text, chat)
            return
        if name not in logic_router.GROUP_COMMANDS:
            return
        chat = await _bind_adder_group_if_ready(app, chat, message.from_user.id)
        if not chat or not chat.get("group_id"):
            await _reply_group(app, message, "Чат пока не привязан к группе. Откройте /settings и нажмите «Привязать к моей группе».", chat)
            return
        ctx = Ctx(app.repo, app.cfg, {"id": message.from_user.id, "group_id": None, "subgroup": None, "role": "student"})
        scr = await logic_router.group_command(ctx, chat["group_id"], name)
        if scr:
            await _reply_group(app, message, scr.text, chat)

    @r.message(group, F.text)
    async def group_text(message: Message) -> None:
        if message.from_user is None or message.from_user.is_bot or not message.text:
            return
        chat = await app.repo.get_chat(message.chat.id)
        if not chat or not chat.get("group_id") or chat["smart_mode"] == "off":
            return
        mention = f"@{app.username.lower()}"
        text = message.text
        addressed = mention in text.lower()
        rt = message.reply_to_message
        if rt is not None and rt.from_user is not None and rt.from_user.id == app.bot.id:
            addressed = True
        user_row = await app.repo.get_user(message.from_user.id)
        if addressed and app.repo.flag("group_require_start") and (not user_row or not user_row.get("private_started")):
            link = f"https://t.me/{app.username}?start=group_access"
            await _reply_group(app, message,
                "Чтобы задавать вопросы боту в группе, сначала откройте его в личных сообщениях и нажмите /start.\n"
                f"👉 <a href=\"{link}\">Запустить бота</a>", chat)
            return
        active = chat["smart_mode"] == "active" and app.questions is not None
        if active:  # ответ человека может закрыть ожидающий вопрос
            await app.questions.mark_answers(message.chat.id, message.from_user.id, text,
                                             rt.message_id if rt is not None else None)
        if addressed:
            text = re.sub(re.escape(mention), "", text, flags=re.I).strip()
        if len(text) > 300:
            return
        ctx = Ctx(app.repo, app.cfg, {"id": message.from_user.id, "group_id": None, "subgroup": None, "role": "student"})
        scr = await logic_router.group_text(ctx, chat["group_id"], text, chat["smart_mode"], addressed)
        if scr is None:
            if active and not addressed:  # вопрос без обращения к боту: ждём, ответят ли люди
                await app.questions.consider(chat, message.from_user.id, message.message_id, text)
            return
        key = (message.chat.id, scr.text[:40])
        now = time.monotonic()
        if now - app.last_group_answer.get(key, 0) < 20:
            return  # антифлуд: одинаковый ответ в чат не чаще раза в 20 секунд
        app.last_group_answer[key] = now
        if len(app.last_group_answer) > 5000:
            app.last_group_answer.clear()
        await _reply_group(app, message, scr.text, chat)

    return r


async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    try:
        await cb.answer(text=text, show_alert=alert)
    except TelegramAPIError:
        pass


async def _reply_group(app: App, message: Message, text: str, chat: dict | None) -> None:
    try:
        sent = await message.reply(text[:MAX_TEXT])
    except TelegramBadRequest as e:
        if not _is(e, "can't parse entities"):
            log.warning("Ответ в группе не отправлен: %s", e)
            return
        sent = await message.reply(strip_tags(text)[:MAX_TEXT], parse_mode=None)
    except TelegramAPIError as e:
        log.warning("Ответ в группе не отправлен: %s", e)
        return
    minutes = (chat or {}).get("autodelete_min", 0)
    if minutes:
        app.spawn(_delete_later(sent, minutes * 60))


async def _delete_later(message: Message, seconds: int) -> None:
    await asyncio.sleep(seconds)
    await safe_delete(message)


async def _is_tg_admin(app: App, chat_id: int, uid: int) -> bool:
    try:
        member = await app.bot.get_chat_member(chat_id, uid)
    except TelegramAPIError:
        return False
    return getattr(member.status, "value", member.status) in ("creator", "administrator")


async def _bind_adder_group_if_ready(app: App, chat: dict | None, uid: int) -> dict | None:
    """Если добавивший бота зарегистрировался позже, автоматически привязываем его группу."""
    if chat is None or chat.get("group_id") is not None or chat.get("added_by") != uid:
        return chat
    user = await app.repo.get_user(uid)
    if user and user.get("group_id"):
        await app.repo.update_chat(chat["chat_id"], group_id=user["group_id"])
        return await app.repo.get_chat(chat["chat_id"])
    return chat


async def _send_chat_settings(app: App, message: Message, chat: dict | None) -> None:
    if message.from_user is None:
        return
    if chat is None:
        chat = await app.repo.upsert_chat(message.chat.id, message.chat.title, None, None)
    chat = await _bind_adder_group_if_ready(app, chat, message.from_user.id)
    user = await app.repo.get_user(message.from_user.id)
    tg_admin = await _is_tg_admin(app, message.chat.id, message.from_user.id)
    if not logic_chat.can_manage(user, chat, app.cfg.superadmin_id, tg_admin):
        await _reply_group(app, message, "Настройки доступны добавившему бота и администраторам чата.", chat)
        return
    scr = await logic_chat.screen(app.repo, chat)
    try:
        await message.answer(scr.text, reply_markup=to_markup(scr.kb))
    except TelegramAPIError:
        log.warning("Не удалось показать настройки чата")


async def _chat_settings_action(app: App, cb: CallbackQuery) -> None:
    msg = cb.message
    if cb.data is None or not isinstance(msg, Message):
        return
    parts = cb.data.split(":")
    if len(parts) != 3:
        return
    try:
        cid = int(parts[1])
    except ValueError:
        return
    if cid != msg.chat.id:
        return
    chat = await app.repo.get_chat(cid)
    if chat is None:
        return
    user = await app.repo.get_user(cb.from_user.id)
    tg_admin = await _is_tg_admin(app, cid, cb.from_user.id)
    if not logic_chat.can_manage(user, chat, app.cfg.superadmin_id, tg_admin):
        await _safe_answer(cb, "Нет прав на настройки этого чата", True)
        return
    if parts[2] == "open":
        scr = await logic_chat.screen(app.repo, chat)
        try:
            await msg.edit_text(scr.text, reply_markup=to_markup(scr.kb))
        except TelegramBadRequest as e:
            if not _is(e, "message is not modified"):
                raise
        return
    problem = await logic_chat.apply(app.repo, chat, user, parts[2])
    if problem:
        await _safe_answer(cb, problem, True)
        return
    chat = await app.repo.get_chat(cid) or chat
    scr = await logic_chat.screen(app.repo, chat)
    try:
        await msg.edit_text(scr.text, reply_markup=to_markup(scr.kb))
    except TelegramBadRequest as e:
        if not _is(e, "message is not modified"):
            raise


async def answer_due_questions(app: App) -> int:
    """Отвечает на вопросы, на которые люди не ответили за отведённое время (вызывается фоновой задачей)."""
    if app.questions is None:
        return 0
    sent_count = 0
    for p, scr in await app.questions.due_answers():
        chat = await app.repo.get_chat(p["chat_id"])
        reply = ReplyParameters(message_id=p["message_id"], allow_sending_without_reply=True)
        try:
            try:
                sent = await app.bot.send_message(p["chat_id"], scr.text[:MAX_TEXT], reply_parameters=reply)
            except TelegramBadRequest as e:
                if not _is(e, "can't parse entities"):
                    raise
                sent = await app.bot.send_message(p["chat_id"], strip_tags(scr.text)[:MAX_TEXT], reply_parameters=reply,
                                                  parse_mode=None)
        except TelegramForbiddenError:
            await app.repo.update_chat(p["chat_id"], active=0)
            continue
        except TelegramAPIError as e:
            log.warning("Ответ на вопрос в чате %s не отправлен: %s", p["chat_id"], e)
            continue
        sent_count += 1
        minutes = (chat or {}).get("autodelete_min", 0)
        if minutes:
            app.spawn(_delete_later(sent, minutes * 60))
    return sent_count
