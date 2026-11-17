"""Вопросы в групповых чатах: бот выжидает, не ответил ли кто-то из людей, и если нет, отвечает сам по расписанию."""
from __future__ import annotations

import json
from datetime import date, datetime

from app import timeutil as tu
from app.bot import logic_schedule as ls
from app.bot.core import Ctx, Screen
from app.config import Settings
from app.db.repo import Repo
from app.services.nlu import Intent, detect_intent, find_subject, looks_like_question, norm

WAIT_INTENTS = {"day", "first", "last", "count", "room", "teacher", "find_teacher", "when_subject", "subject_day", "next",
                "exam", "week", "hw"}
ANSWER_SIGNAL = __import__("re").compile(
    r"\\b(?:да|нет|будет|будут|не будет|не состоится|состоится|отменили|отменят|перенесли|перенесут|"
    r"заменили|заменят)\\b|\\b(?:ауд(?:итория)?|каб(?:инет)?)\\.?\\s*\\d+\\b|"
    r"\\bв\\s+\\d{1,4}(?:[:.]\\d{2})?\\b|\\b\\d{1,2}[:.]\\d{2}\\b|"
    r"\\b(?:первая|вторая|третья|четвертая|четвёртая|пятая|шестая)\\s+пара\\b",
    __import__("re").IGNORECASE,
)
MAX_PENDING_PER_CHAT = 5


def _dummy_user(uid: int) -> dict:
    return {"id": uid, "group_id": None, "subgroup": None, "role": "student"}


def intent_to_json(i: Intent) -> str:
    return json.dumps({"name": i.name, "day": i.day.isoformat() if i.day else None, "num": i.num, "subject": i.subject,
                       "week_shift": i.week_shift, "explicit": i.explicit_day, "teacher": i.teacher}, ensure_ascii=False)


def intent_from_json(raw: str) -> Intent:
    d = json.loads(raw)
    return Intent(name=d["name"], day=date.fromisoformat(d["day"]) if d.get("day") else None, num=d.get("num"),
                  subject=d.get("subject"), week_shift=d.get("week_shift"), explicit_day=bool(d.get("explicit")),
                  teacher=d.get("teacher"))


def signature(i: Intent) -> str:
    return f"{i.name}|{i.subject}|{i.day}|{i.num}|{i.teacher}"


class QuestionService:
    def __init__(self, repo: Repo, cfg: Settings):
        self.repo, self.cfg = repo, cfg

    async def consider(self, chat: dict, user_id: int, message_id: int, text: str, now_ts: int | None = None,
                       now_dt: datetime | None = None) -> bool:
        """Запоминает вопрос без обращения к боту, чтобы ответить, если за wait_min минут никто не ответит."""
        gid = chat.get("group_id")
        if not gid or chat.get("smart_mode") != "active" or not looks_like_question(text):
            return False
        ctx = Ctx(self.repo, self.cfg, _dummy_user(user_id), now=now_dt)
        intent = detect_intent(text, ctx.today, await self.repo.subject_catalog(), await self.repo.known_surnames())
        if intent is None or intent.name not in WAIT_INTENTS:
            return False
        pend = await self.repo.pending_for_chat(chat["chat_id"])
        if len(pend) >= MAX_PENDING_PER_CHAT:
            return False
        sig = signature(intent)
        for p in pend:
            if p["user_id"] == user_id:
                return False  # один ожидающий вопрос от человека
            try:
                if signature(intent_from_json(p["intent"])) == sig:
                    return False  # такой же вопрос уже ждёт ответа
            except (ValueError, KeyError):
                continue
        now = now_ts if now_ts is not None else tu.now_ts()
        wait = max(1, int(chat.get("wait_min") or 60))
        await self.repo.add_pending(chat["chat_id"], message_id, user_id, text, intent_to_json(intent), now + wait * 60)
        return True

    async def mark_answers(self, chat_id: int, user_id: int, text: str, reply_to_id: int | None) -> int:
        """Снимает вопрос по явному ответу на него, не принимая любое сообщение за ответ."""
        pend = await self.repo.pending_for_chat(chat_id)
        if not pend or not text or len(text) > 300 or "?" in text or looks_like_question(text):
            return 0
        n = 0
        catalog = await self.repo.subject_catalog()
        t = norm(text)
        has_signal = bool(ANSWER_SIGNAL.search(text))
        mentioned_subject = find_subject(text, catalog)
        schedule_intents = {"day", "week", "first", "last", "count", "next", "exam", "hw"}
        for p in pend:
            if p["user_id"] == user_id:
                continue
            answered = reply_to_id is not None and reply_to_id == p["message_id"]
            if not answered:
                try:
                    intent = intent_from_json(p["intent"])
                except (ValueError, KeyError, TypeError):
                    continue
                if intent.subject:
                    subject_hit = find_subject(
                        text, [(intent.subject.lower(), intent.subject)] +
                        [item for item in catalog if item[1] == intent.subject]
                    ) == intent.subject
                    # Для вопроса о конкретном предмете нужен именно этот предмет;
                    # короткое название предмета тоже считается ответом.
                    answered = subject_hit and (has_signal or len(t.split()) <= 3)
                    # Ответ без названия предмета принимаем только когда вопрос в чате один.
                    if not answered and len(pend) == 1:
                        answered = has_signal
                else:
                    # Для общих вопросов не закрываем сразу все ожидания сообщением «да»
                    # или случайным числом. Нужен единственный ожидающий вопрос и явный сигнал,
                    # либо упоминание предмета в ответе на единственный вопрос о расписании.
                    answered = len(pend) == 1 and (
                        has_signal or (bool(mentioned_subject) and intent.name in schedule_intents)
                    )
            if answered and await self.repo.set_pending_status(p["id"], "answered"):
                n += 1
        return n

    async def due_answers(self, now_ts: int | None = None, now_dt: datetime | None = None) -> list[tuple[dict, Screen]]:
        """Арендует просроченные вопросы и подготавливает ответы; завершение — после Telegram API."""
        now = now_ts if now_ts is not None else tu.now_ts()
        out: list[tuple[dict, Screen]] = []
        for p in await self.repo.pending_due(now):
            if not await self.repo.claim_pending(p["id"], now):
                continue
            chat = await self.repo.get_chat(p["chat_id"])
            if not chat or not chat.get("active") or not chat.get("group_id"):
                await self.repo.finish_pending(p["id"], True)
                continue
            try:
                intent = intent_from_json(p["intent"])
            except (ValueError, KeyError, TypeError):
                await self.repo.finish_pending(p["id"], True)
                continue
            ctx = Ctx(self.repo, self.cfg, _dummy_user(p["user_id"]), now=now_dt)
            screen = await ls.answer_intent(ctx, intent, chat["group_id"], None, allow_kb=False)
            if screen is None:
                await self.repo.finish_pending(p["id"], True)
                continue
            screen.text = "🤖 Пока никто не ответил, отвечаю по расписанию:\\n\\n" + screen.text
            out.append((p, screen))
        return out
