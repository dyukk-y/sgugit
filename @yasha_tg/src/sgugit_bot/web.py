from .core import *
from . import core as core_module
from .services import sponsor_tracking_secret, sponsor_url
from .services import *
from .handlers import *

WEB_APP = FastAPI(title="SGUGIT Sponsor Redirect", docs_url=None, redoc_url=None)

@WEB_APP.get("/health")
async def health():
    return {"status": "ok"}

@WEB_APP.get("/sponsor/click")
async def sponsor_click(token: str):
    try:
        raw, sig = token.split(".", 1)
        padded = raw + "=" * (-len(raw) % 4)
        payload = base64.urlsafe_b64decode(padded.encode())
        expected = hmac.new(sponsor_tracking_secret(), payload, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        chat_s, ts_s, _nonce = payload.decode().split(":", 2)
        chat_id, ts = int(chat_s), int(ts_s)
        if abs(int(now().timestamp()) - ts) > 86400:
            raise ValueError("expired")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired sponsor link")

    set_sponsor(chat_id)
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sponsor_clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, clicked_at TEXT NOT NULL)")
        c.execute("INSERT INTO sponsor_clicks(chat_id, clicked_at) VALUES(?, ?)", (chat_id, now_iso()))
        row = c.execute("SELECT last_ui_message_id FROM ui_state WHERE chat_id=?", (chat_id,)).fetchone()
    # Best-effort UI transition: the database permission is authoritative even
    # if Telegram is temporarily unavailable.
    if core_module.BOT_APPLICATION is not None and row and row[0]:
        try:
            await core_module.BOT_APPLICATION.bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(row[0]),
                text='🏠 <b>Главное меню</b>\n\nВыбирай нужный раздел.',
                parse_mode=ParseMode.HTML,
                reply_markup=premium_menu(chat_id),
            )
        except Exception as exc:
            log.warning("sponsor UI transition failed for %s: %s", chat_id, exc)
    # Legacy equivalent: RedirectResponse(SPONSOR_URL, status_code=302)
    return RedirectResponse(sponsor_url(), status_code=302)

def start_web_server():
    import threading
    import uvicorn
    config = uvicorn.Config(WEB_APP, host="0.0.0.0", port=WEB_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="sponsor-web", daemon=True)
    thread.start()
    return thread


