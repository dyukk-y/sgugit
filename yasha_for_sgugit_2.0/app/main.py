"""Точка входа: python -m app.main"""
from __future__ import annotations

import asyncio
import logging
import time
import sys
from pathlib import Path

# Поддерживаем запуск как `python app/main.py` на хостингах,
# которые игнорируют команду `python -m app.main`.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, ErrorEvent

from app import timeutil as tu
from app.bot import background, tg
from app.config import load_settings
from app.db.core import Database
from app.db.repo import Repo
from app.db.schema import migrate
from app.providers.directory import crawl_directory
from app.providers.site import fetch_all_groups
from app.services.directory import DirectorySync
from app.services.notifier import Notifier
from app.services.questions import QuestionService
from app.services.sync import SyncService

log = logging.getLogger("app")


async def set_commands(bot: Bot) -> None:
    private = [BotCommand(command="menu", description="Главное меню"), BotCommand(command="today", description="Расписание на сегодня"),
               BotCommand(command="tomorrow", description="Расписание на завтра"), BotCommand(command="week", description="Расписание на неделю"),
               BotCommand(command="next", description="Следующая пара"), BotCommand(command="hw", description="Задания группы"),
               BotCommand(command="help", description="Помощь")]
    groups = [BotCommand(command="today", description="Расписание на сегодня"), BotCommand(command="tomorrow", description="Расписание на завтра"),
              BotCommand(command="week", description="Расписание на неделю"), BotCommand(command="next", description="Следующая пара"),
              BotCommand(command="hw", description="Задания группы"), BotCommand(command="settings", description="Настройки чата")]
    try:
        await bot.set_my_commands(private, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(groups, scope=BotCommandScopeAllGroupChats())
    except TelegramAPIError as e:
        log.warning("Не удалось установить команды бота: %s", e)


async def main() -> None:
    cfg = load_settings()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tu.set_timezone(cfg.timezone)
    db = Database(cfg.database_url)
    await db.connect()
    await migrate(db)
    repo = Repo(db)
    await repo.load_settings()
    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    log.info("Бот @%s запущен, БД: %s", me.username, db.kind)

    sender = tg.Sender(bot, repo)
    notifier = Notifier(repo, sender.enqueue)
    app = tg.App(bot=bot, repo=repo, cfg=cfg, sender=sender, services={}, username=me.username or "bot",
                 questions=QuestionService(repo, cfg))

    async def alert(text: str) -> None:
        await background.notify_super(app, text)

    async def fetch_schedule():
        return await fetch_all_groups(cfg.schedule_source_url, tu.today())

    sync = SyncService(repo, fetch_schedule, on_changes=notifier.notify_changes, on_alert=alert)
    directory = DirectorySync(repo, lambda: crawl_directory(cfg.directory_url), on_alert=alert)
    app.services.update({"sync": sync, "directory": directory})

    dp = Dispatcher()
    dp.include_router(tg.build_router(app))
    last_error = {"t": 0.0}

    async def on_error(event: ErrorEvent) -> bool:
        log.error("Необработанная ошибка: %r", event.exception, exc_info=event.exception)
        if time.monotonic() - last_error["t"] > 600:  # не чаще раза в 10 минут
            last_error["t"] = time.monotonic()
            await alert(f"⚠️ Ошибка в боте: {type(event.exception).__name__}: {str(event.exception)[:200]}")
        return True

    dp.errors.register(on_error)
    await set_commands(bot)
    if await repo.is_empty():
        await alert("ℹ️ База данных пуста. Если это не первый запуск, данные могли пропасть при перезапуске: откройте "
                    "/admin → Бэкап → «Восстановить из файла» и пришлите последний бэкап.")
    sender.start()
    tasks = background.start_all(app, sync, directory, notifier)
    try:
        if cfg.webhook_url:
            await bot.set_webhook(cfg.webhook_url + cfg.webhook_path,
                                  secret_token=cfg.webhook_secret or None,
                                  allowed_updates=["message", "callback_query", "my_chat_member"])
            web_app = web.Application()
            SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=cfg.webhook_secret or None).register(web_app, path=cfg.webhook_path)
            setup_application(web_app, dp, bot=bot)
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", cfg.webhook_port)
            await site.start()
            log.info("Webhook слушает порт %s, путь %s", cfg.webhook_port, cfg.webhook_path)
            try:
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
        else:
            await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member"])
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sender.stop()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
