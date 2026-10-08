import sys
from pathlib import Path

# Allow direct execution: `python src\sgugit_bot\main.py`
# while keeping the package-relative imports inside sgugit_bot working.
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, PreCheckoutQueryHandler, filters
import sgugit_bot.core as core
from sgugit_bot.core import BOT_TOKEN
from sgugit_bot.handlers import (
    start, today, tomorrow, week, next_cmd, subscribe, unsubscribe,
    refresh_cmd, help_cmd, owner_help_cmd, leader_application, admin_leader_applications,
    callbacks, photo_router, text_router, precheckout_stars,
    successful_stars_payment, post_init, post_shutdown, errors, owner_panel_cmd,
)
from sgugit_bot.web import start_web_server

def build_application():
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN не задан. Создай .env в корне проекта и укажи BOT_TOKEN=...')
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    core.BOT_APPLICATION = app
    start_web_server()
    app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('today',today)); app.add_handler(CommandHandler('tomorrow',tomorrow)); app.add_handler(CommandHandler('week',week)); app.add_handler(CommandHandler('next',next_cmd)); app.add_handler(CommandHandler('subscribe',subscribe)); app.add_handler(CommandHandler('unsubscribe',unsubscribe)); app.add_handler(CommandHandler('refresh',refresh_cmd)); app.add_handler(CommandHandler('help',help_cmd)); app.add_handler(CommandHandler('owner_help',owner_help_cmd)); app.add_handler(CommandHandler('leader_apply',leader_application)); app.add_handler(CommandHandler('leader_apps',admin_leader_applications)); app.add_handler(CommandHandler('panel',owner_panel_cmd)); app.add_handler(PreCheckoutQueryHandler(precheckout_stars)); app.add_handler(CallbackQueryHandler(callbacks)); app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT,successful_stars_payment)); app.add_handler(MessageHandler(filters.PHOTO,photo_router)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router)); app.add_error_handler(errors)
    return app

def main(): build_application().run_polling(allowed_updates=Update.ALL_TYPES,drop_pending_updates=True)
if __name__=='__main__': main()
