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
ANSWER_WORDS = ("будет", "будут", "не будет", "нет", "да ", "отмен", "перенес", "перенос", "заменя", "замена", "ауд", "каб",
                "состоится", "в ", "пара", "пары", "первая", "вторая", "третья")
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
        """Сообщение человека может быть ответом на ожидающий вопрос. Возвращает число снятых вопросов."""
        pend = await self.repo.pending_for_chat(chat_id)
        if not pend:
            return 0
        n = 0
        catalog = await self.repo.subject_catalog()
        t = norm(text)
        for p in pend:
            if p["user_id"] == user_id:
                continue
            answered = reply_to_id is not None and reply_to_id == p["message_id"]
            if not answered and text and len(text) <= 300 and "?" not in text:
                try:
                    subj = intent_from_json(p["intent"]).subject
                except (ValueError, KeyError):
                    subj = None
                has_signal = any(ch.isdigit() for ch in t) or any(w in f" {t} " for w in ANSWER_WORDS)
                subj_hit = bool(subj) and find_subject(text, [(subj.lower(), subj)] + [c for c in catalog if c[1] == subj]) == subj
                answered = has_signal and (subj_hit or not subj)
            if answered and await self.repo.set_pending_status(p["id"], "answered"):
                n += 1
        return n

    async def due_answers(self, now_ts: int | None = None, now_dt: datetime | None = None) -> list[tuple[dict, Screen]]:
        """Вопросы, на которые за отведённое время никто не ответил: готовые ответы бота."""
        now = now_ts if now_ts is not None else tu.now_ts()
        out: list[tuple[dict, Screen]] = []
        for p in await self.repo.pending_due(now):
            if not await self.repo.set_pending_status(p["id"], "sent"):
                continue
            chat = await self.repo.get_chat(p["chat_id"])
            if not chat or not chat.get("active") or not chat.get("group_id"):
                continue
            try:
                intent = intent_from_json(p["intent"])
            except (ValueError, KeyError):
                continue
            ctx = Ctx(self.repo, self.cfg, _dummy_user(p["user_id"]), now=now_dt)
            screen = await ls.answer_intent(ctx, intent, chat["group_id"], None, allow_kb=False)
            if screen is None:
                continue
            screen.text = "🤖 Пока никто не ответил, отвечаю по расписанию:\n\n" + screen.text
            out.append((p, screen))
        return out
