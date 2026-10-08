from .core import *

# Production application services and domain logic
# ============================================================

APP_VERSION = "2.3.2"

SPONSOR_EXEMPT_STARS = 25
TRUSTED_LEADER_STREAK = 10
GROUP_INDEX_URL = "https://sgugit.ru/raspisanie/"
GROUP_CACHE_SECONDS = 900


def ensure_schema():
    with connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        for name, ddl in [
            ("group_code", "ALTER TABLE users ADD COLUMN group_code TEXT NOT NULL DEFAULT ''"),
            ("group_url", "ALTER TABLE users ADD COLUMN group_url TEXT NOT NULL DEFAULT ''"),
            ("full_name", "ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT ''"),
            ("sponsor_ok", "ALTER TABLE users ADD COLUMN sponsor_ok INTEGER NOT NULL DEFAULT 0"),
            ("reg_state", "ALTER TABLE users ADD COLUMN reg_state TEXT NOT NULL DEFAULT ''"),
            ("muted", "ALTER TABLE users ADD COLUMN muted INTEGER NOT NULL DEFAULT 0"),
            ("peer_tasks_enabled", "ALTER TABLE users ADD COLUMN peer_tasks_enabled INTEGER NOT NULL DEFAULT 1"),
            ("share_tasks_enabled", "ALTER TABLE users ADD COLUMN share_tasks_enabled INTEGER NOT NULL DEFAULT 1"),
            ("notify_lessons", "ALTER TABLE users ADD COLUMN notify_lessons INTEGER NOT NULL DEFAULT 1"),
            ("notify_daily", "ALTER TABLE users ADD COLUMN notify_daily INTEGER NOT NULL DEFAULT 1"),
            ("notify_changes", "ALTER TABLE users ADD COLUMN notify_changes INTEGER NOT NULL DEFAULT 1"),
            ("notify_tasks", "ALTER TABLE users ADD COLUMN notify_tasks INTEGER NOT NULL DEFAULT 1"),
            ("notify_announcements", "ALTER TABLE users ADD COLUMN notify_announcements INTEGER NOT NULL DEFAULT 1"),
            ("notify_polls", "ALTER TABLE users ADD COLUMN notify_polls INTEGER NOT NULL DEFAULT 1"),
            ("notify_applications", "ALTER TABLE users ADD COLUMN notify_applications INTEGER NOT NULL DEFAULT 1"),
            ("notify_system", "ALTER TABLE users ADD COLUMN notify_system INTEGER NOT NULL DEFAULT 1"),
            ("quiet_enabled", "ALTER TABLE users ADD COLUMN quiet_enabled INTEGER NOT NULL DEFAULT 0"),
            ("quiet_start", "ALTER TABLE users ADD COLUMN quiet_start TEXT NOT NULL DEFAULT '23:00'"),
            ("quiet_end", "ALTER TABLE users ADD COLUMN quiet_end TEXT NOT NULL DEFAULT '07:00'"),
            ("reminder_minutes", "ALTER TABLE users ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 60"),
        ]:
            if name not in cols:
                c.execute(ddl)
        c.execute("""CREATE TABLE IF NOT EXISTS group_catalog(
            code TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
            normalized TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            subject TEXT NOT NULL, text TEXT NOT NULL, lesson_day TEXT NOT NULL DEFAULT '',
            lesson_start TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '')""")
        task_cols={r[1] for r in c.execute('PRAGMA table_info(tasks)').fetchall()}
        for name, ddl in [
            ('group_code', "ALTER TABLE tasks ADD COLUMN group_code TEXT NOT NULL DEFAULT ''"),
            ('author_name', "ALTER TABLE tasks ADD COLUMN author_name TEXT NOT NULL DEFAULT ''"),
            ('shared', "ALTER TABLE tasks ADD COLUMN shared INTEGER NOT NULL DEFAULT 1"),
            ('due_at', "ALTER TABLE tasks ADD COLUMN due_at TEXT NOT NULL DEFAULT ''"),
        ]:
            if name not in task_cols:
                try: c.execute(ddl)
                except sqlite3.OperationalError: pass
        c.execute("""CREATE TABLE IF NOT EXISTS polls(
            id INTEGER PRIMARY KEY AUTOINCREMENT, leader_id INTEGER NOT NULL,
            group_code TEXT NOT NULL, title TEXT NOT NULL, question TEXT NOT NULL,
            options_json TEXT NOT NULL, require_photo INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS poll_answers(
            poll_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, option_idx INTEGER NOT NULL,
            photo_file_id TEXT NOT NULL DEFAULT '', answered_at TEXT NOT NULL,
            PRIMARY KEY(poll_id, chat_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS leader_applications_v12(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, group_code TEXT NOT NULL,
            full_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, deadline_at TEXT NOT NULL, processed_at TEXT NOT NULL DEFAULT '',
            processed_by INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS group_invites(
            token TEXT PRIMARY KEY, group_code TEXT NOT NULL, leader_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, max_uses INTEGER NOT NULL DEFAULT 50,
            uses INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pending_invites(
            chat_id INTEGER PRIMARY KEY, token TEXT NOT NULL, created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS referrals(
            invited_chat_id INTEGER PRIMARY KEY, inviter_chat_id INTEGER NOT NULL,
            created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS spam_hits(
            chat_id INTEGER NOT NULL, bucket TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id,bucket))""")
        # Hidden trust + moderation queue. The leader never sees the internal trust level.
        c.execute("""CREATE TABLE IF NOT EXISTS leader_trust(
            leader_id INTEGER PRIMARY KEY, group_code TEXT NOT NULL DEFAULT '',
            approved_streak INTEGER NOT NULL DEFAULT 0, approved_total INTEGER NOT NULL DEFAULT 0,
            rejected_total INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS publication_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT, leader_id INTEGER NOT NULL, group_code TEXT NOT NULL,
            kind TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT '', reviewed_by INTEGER NOT NULL DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS sponsor_exemptions(
            chat_id INTEGER PRIMARY KEY, personal INTEGER NOT NULL DEFAULT 0,
            group_code TEXT NOT NULL DEFAULT '', group_enabled INTEGER NOT NULL DEFAULT 0,
            stars INTEGER NOT NULL DEFAULT 0, purchased_at TEXT NOT NULL DEFAULT '',
            telegram_charge_id TEXT NOT NULL DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS group_sponsor_exemptions(
            group_code TEXT PRIMARY KEY, leader_id INTEGER NOT NULL, stars INTEGER NOT NULL DEFAULT 0,
            purchased_at TEXT NOT NULL DEFAULT '', telegram_charge_id TEXT NOT NULL DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bot_settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
        )""")
        c.execute("INSERT OR IGNORE INTO bot_settings(key,value,updated_at) VALUES(?,?,?)",('sponsor_button_text','⭐ Спонсор',now_iso()))
        c.execute("INSERT OR IGNORE INTO bot_settings(key,value,updated_at) VALUES(?,?,?)",('sponsor_url','',now_iso()))
        c.execute("INSERT OR IGNORE INTO bot_settings(key,value,updated_at) VALUES(?,?,?)",('sponsor_tracking_secret','',now_iso()))
        c.execute("""CREATE TABLE IF NOT EXISTS owner_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
            created_at TEXT NOT NULL, file_name TEXT NOT NULL
        )""")
        c.commit()

ensure_schema()





def bot_setting(key: str, default: str = '') -> str:
    with connect() as c:
        row = c.execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
    return (row[0] if row else default) or default


def set_bot_setting(key: str, value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO bot_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, now_iso()))


def sponsor_url() -> str:
    return bot_setting('sponsor_url', '').strip()


def sponsor_tracking_secret() -> bytes:
    value = bot_setting('sponsor_tracking_secret', '').strip()
    return (value or BOT_TOKEN or 'change-me').encode()

def user_setting(chat_id:int, field:str, default=True)->bool:
    allowed={'peer_tasks_enabled','share_tasks_enabled','notify_lessons','notify_daily','notify_changes','notify_tasks','notify_announcements','notify_polls','notify_applications','notify_system','quiet_enabled','reminder_minutes'}
    if field not in allowed: raise ValueError(field)
    with connect() as c:
        row=c.execute(f'SELECT {field} FROM users WHERE chat_id=?',(chat_id,)).fetchone()
    return bool(row[0]) if row else default


def set_user_setting(chat_id:int, field:str, value:bool):
    allowed={'peer_tasks_enabled','share_tasks_enabled','notify_lessons','notify_daily','notify_changes','notify_tasks','notify_announcements','notify_polls','notify_applications','notify_system','quiet_enabled','reminder_minutes'}
    if field not in allowed: raise ValueError(field)
    with connect() as c: c.execute(f'UPDATE users SET {field}=?,last_seen=? WHERE chat_id=?',(1 if value else 0,now_iso(),chat_id))


NOTIFY_FIELDS = ('notify_daily','notify_lessons','notify_changes','notify_tasks','notify_announcements','notify_polls','notify_applications','notify_system')

def set_notification_preset(chat_id:int, preset:str):
    """Apply a simple notification profile so the student never has to configure 7 toggles manually."""
    presets = {
        'schedule': {'notify_daily':1,'notify_lessons':1,'notify_changes':1,'notify_tasks':0,'notify_announcements':0,'notify_polls':0,'notify_applications':0,'notify_system':0},
        'recommended': {'notify_daily':1,'notify_lessons':1,'notify_changes':1,'notify_tasks':1,'notify_announcements':1,'notify_polls':1,'notify_applications':1,'notify_system':1},
        'off': {f:0 for f in NOTIFY_FIELDS},
    }
    values=presets.get(preset)
    if values is None: raise ValueError(preset)
    with connect() as c:
        for field,value in values.items():
            c.execute(f'UPDATE users SET {field}=?,last_seen=? WHERE chat_id=?',(value,now_iso(),chat_id))

def notification_state(chat_id:int):
    with connect() as c:
        row=c.execute('SELECT notify_daily,notify_lessons,notify_changes,notify_tasks,notify_announcements,notify_polls,notify_applications,notify_system FROM users WHERE chat_id=?',(chat_id,)).fetchone()
    return dict(zip(NOTIFY_FIELDS,row or [1]*len(NOTIFY_FIELDS)))

def notification_preset_name(chat_id:int)->str:
    st=notification_state(chat_id)
    if all(v==0 for v in st.values()): return '🔕 Всё выключено'
    if st['notify_daily'] and st['notify_lessons'] and st['notify_changes'] and not any(st[f] for f in ('notify_tasks','notify_announcements','notify_polls','notify_applications')):
        return '📅 Только расписание'
    if all(v==1 for v in st.values()): return '✨ Рекомендуемый режим'
    return '⚙️ Своя настройка'


def leader_application_blocked(chat_id: int) -> bool:
    """Permanent anti-spam lock: after an owner rejection, no new leader application is allowed."""
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM leader_applications_v12 WHERE chat_id=? AND status='rejected' LIMIT 1",
            (chat_id,),
        ).fetchone()
    return bool(row)


def leader_group(chat_id:int, context=None)->str:
    if context is not None and chat_id == OWNER_ID:
        override=context.user_data.get('owner_panel_group','')
        if override: return override
    p=profile(chat_id)
    return p[2] if p else ''


def group_students(group_code:str):
    with connect() as c:
        return c.execute("SELECT chat_id,full_name,username,registered_at,last_seen FROM users WHERE group_code=? ORDER BY full_name,chat_id",(group_code,)).fetchall()


def referral_signature(chat_id: int) -> str:
    payload = str(chat_id).encode()
    return hmac.new(globals().get('SPONSOR_TRACKING_SECRET') or sponsor_tracking_secret(), b'ref:' + payload, hashlib.sha256).hexdigest()[:16]


def referral_link(bot_username: str, chat_id: int) -> str:
    return f'https://t.me/{bot_username}?start=ref_{chat_id}_{referral_signature(chat_id)}'



def referral_share_url(bot_username: str, chat_id: int) -> str:
    from urllib.parse import quote
    link=referral_link(bot_username,chat_id)
    text="🎓 Попробуй бота для студентов СГУГиТ: расписание, задания и уведомления."
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"

def register_referral(invited_chat_id: int, inviter_chat_id: int) -> bool:
    if invited_chat_id == inviter_chat_id:
        return False
    with connect() as c:
        # A user can be attributed only once; later /start links must not overwrite
        # the original inviter.
        row = c.execute('SELECT 1 FROM referrals WHERE invited_chat_id=?', (invited_chat_id,)).fetchone()
        if row:
            return False
        inviter = c.execute('SELECT 1 FROM users WHERE chat_id=?', (inviter_chat_id,)).fetchone()
        if not inviter:
            return False
        c.execute('INSERT INTO referrals(invited_chat_id,inviter_chat_id,created_at) VALUES(?,?,?)',
                  (invited_chat_id, inviter_chat_id, now_iso()))
        return True


def referral_count(chat_id: int) -> int:
    with connect() as c:
        return int(c.execute('SELECT COUNT(*) FROM referrals WHERE inviter_chat_id=?', (chat_id,)).fetchone()[0])


def parse_referral_arg(arg: str) -> Optional[int]:
    m = re.fullmatch(r'ref_(\d+)_([0-9a-f]{16})', arg or '')
    if not m:
        return None
    inviter = int(m.group(1))
    if not hmac.compare_digest(m.group(2), referral_signature(inviter)):
        return None
    return inviter


def create_group_invite(group_code:str, leader_id:int, hours:int=168, max_uses:int=100)->str:
    import secrets
    token=secrets.token_urlsafe(8).replace('-','').replace('_','')[:12]
    with connect() as c:
        c.execute('INSERT INTO group_invites(token,group_code,leader_id,created_at,expires_at,max_uses,uses,active) VALUES(?,?,?,?,?,?,0,1)',(token,group_code,leader_id,now_iso(),(now()+timedelta(hours=hours)).isoformat(),max_uses))
    return token


def invite_info(token:str):
    with connect() as c:
        row=c.execute('SELECT token,group_code,leader_id,created_at,expires_at,max_uses,uses,active FROM group_invites WHERE token=?',(token,)).fetchone()
    if not row: return None
    if not row[7] or row[6]>=row[5]: return None
    try:
        if now() >= datetime.fromisoformat(row[4]): return None
    except Exception: return None
    return row


def consume_invite(token:str, chat_id:int)->bool:
    with connect() as c:
        row=c.execute('SELECT expires_at FROM group_invites WHERE token=?',(token,)).fetchone()
        if not row: return False
        try:
            if now() >= datetime.fromisoformat(row[0]): return False
        except Exception: return False
        c.execute('UPDATE group_invites SET uses=uses+1 WHERE token=? AND active=1 AND uses<max_uses',(token,))
        return c.execute('SELECT changes()').fetchone()[0]==1


def clear_group_membership(chat_id:int):
    with connect() as c:
        c.execute("UPDATE users SET group_code='',group_url='',reg_state='await_group',last_seen=? WHERE chat_id=?",(now_iso(),chat_id))


def task_visibility_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton('👥 Видно моей группе',callback_data='task:share:1'),InlineKeyboardButton('🔒 Только мне',callback_data='task:share:0')],[InlineKeyboardButton('‹ Отмена',callback_data='task:cancel')]])


def normalize_group(value: str) -> str:
    v = (value or '').strip().upper().replace('Ё','Е')
    v = re.sub(r'[\s_]+', '', v)
    v = v.replace('—','-').replace('–','-').replace('−','-')
    v = re.sub(r'[^А-ЯA-Z0-9.-]', '', v)
    v = v.replace('ОИ11.1','ОИ-11.1') if v.startswith('ОИ11.') else v
    v = re.sub(r'([А-ЯA-Z]+)(\d)', r'\1-\2', v)
    return v


def _group_from_href(href: str) -> bool:
    return bool(re.search(r"/raspisanie/group/(\d+)(?:/)?(?:[?#].*)?$", href or "", re.I))


def _extract_group_title(a) -> str:
    parts = [
        a.get_text(" ", strip=True),
        a.get("title", ""),
        a.get("aria-label", ""),
        a.get("data-title", ""),
        a.get("data-group", ""),
    ]
    for value in parts:
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if value:
            return value
    return ""


class _GroupPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1_text = ""
        self.title_text = ""
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"h1", "title"} and self._capture is None:
            self._capture = tag
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._capture == tag:
            value = re.sub(r"\s+", " ", " ".join(self._buf)).strip()
            if tag == "h1" and not self.h1_text:
                self.h1_text = value
            elif tag == "title" and not self.title_text:
                self.title_text = value
            self._capture = None
            self._buf = []


class _GroupLinkParser(HTMLParser):
    """Extract schedule group links with the standard-library HTML parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._depth = 0

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() == "a":
            attrs_map = dict(attrs)
            href = attrs_map.get("href")
            if href:
                self.links.append((href, ""))

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "a" and self._href is None:
            attrs_map = dict(attrs)
            href = attrs_map.get("href")
            if href:
                self._href = href
                self._text = []
                self._depth = 1
        elif self._href is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._href is None:
            return
        if tag.lower() == "a":
            self._depth -= 1
            if self._depth <= 0:
                self.links.append((self._href, re.sub(r"\s+", " ", " ".join(self._text)).strip()))
                self._href = None
                self._text = []
                self._depth = 0
        else:
            self._depth = max(0, self._depth - 1)


def _parse_group_links(html_text: str) -> list[tuple[str,str,str]]:
    parser = _GroupLinkParser()
    parser.feed(html_text or "")
    parser.close()
    found = {}
    for href, title in parser.links:
        m = re.search(r"/raspisanie/group/(\d+)(?:/)?(?:[?#].*)?$", href or "", re.I)
        if not m:
            continue
        title = re.sub(r"\s+", " ", title or "").strip()
        if not title:
            continue
        mm = re.search(r"(?:Группа\s*)?([А-ЯA-Z]{1,12})\s*-?\s*(\d{1,3}(?:\.\d+)?)", title, re.I)
        if not mm:
            continue
        code = normalize_group(f"{mm.group(1)}-{mm.group(2)}")
        url = href if href.startswith("http") else requests.compat.urljoin(GROUP_INDEX_URL, href)
        found[code] = (code, title, url)
    return sorted(found.values(), key=lambda x: x[0])


def _probe_group_id(group_id: int):
    url = f"https://sgugit.ru/raspisanie/group/{group_id}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        if r.status_code != 200:
            return None
        r.encoding = r.apparent_encoding or "utf-8"
        parser = _GroupPageParser()
        parser.feed(r.text or "")
        parser.close()
        title = parser.h1_text or parser.title_text
        title = re.sub(r"\s+", " ", title).strip()
        mm = re.search(r"(?:Группа\s*)?([А-ЯA-Z]{1,12})\s*-?\s*(\d{1,3}(?:\.\d+)?)", title, re.I)
        if not mm:
            return None
        code = normalize_group(f"{mm.group(1)}-{mm.group(2)}")
        return (code, title or f"Группа {code}", url)
    except Exception:
        return None


def _probe_group_catalog() -> list[tuple[str,str,str]]:
    # The public index is sometimes rendered dynamically and may contain no
    # group links in raw HTML. In that case discover the real group pages by
    # their numeric IDs once, then cache the result in SQLite.
    found = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = [pool.submit(_probe_group_id, i) for i in range(1500, 2101)]
        for future in as_completed(futures):
            item = future.result()
            if item:
                found[item[0]] = item
    return sorted(found.values(), key=lambda x: x[0])


def refresh_group_catalog(force: bool=False) -> list[tuple[str,str,str]]:
    with connect() as c:
        if not force:
            row = c.execute("SELECT MAX(updated_at) FROM group_catalog").fetchone()
            if row and row[0]:
                try:
                    if (now()-datetime.fromisoformat(row[0])).total_seconds() < GROUP_CACHE_SECONDS:
                        cached = c.execute("SELECT code,title,url FROM group_catalog ORDER BY code").fetchall()
                        if cached:
                            return cached
                except Exception:
                    pass

    rows = []
    try:
        r = requests.get(GROUP_INDEX_URL, headers=HEADERS, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        rows = _parse_group_links(r.text)
    except Exception as exc:
        log.warning("group index fetch failed: %s", exc)

    if not rows:
        rows = _probe_group_catalog()

    if rows:
        with connect() as c:
            c.execute("DELETE FROM group_catalog")
            stamp = now_iso()
            c.executemany(
                "INSERT INTO group_catalog(code,title,url,normalized,updated_at) VALUES(?,?,?,?,?)",
                [(code,title,url,normalize_group(code),stamp) for code,title,url in rows],
            )
    return rows



def group_catalog() -> list[tuple[str,str,str]]:
    try: return refresh_group_catalog(False)
    except Exception:
        with connect() as c:
            return c.execute('SELECT code,title,url FROM group_catalog ORDER BY code').fetchall()


def resolve_group(value: str):
    q=normalize_group(value)
    rows=group_catalog()
    exact=[r for r in rows if normalize_group(r[0])==q or normalize_group(r[1])==q]
    if exact: return ('exact',exact,[])
    from difflib import SequenceMatcher
    scored=[]
    for r in rows:
        ratio=max(SequenceMatcher(None,q,normalize_group(r[0])).ratio(),
                  SequenceMatcher(None,q,normalize_group(r[1])).ratio())
        if ratio>=0.62: scored.append((ratio,r))
    scored.sort(key=lambda x:x[0],reverse=True)
    best=[r for _,r in scored[:6]]
    if best and scored[0][0]>=0.82: return ('fuzzy',best,[])
    return ('none',[],best)


def set_registration(chat_id:int,state:str):
    with connect() as c: c.execute('UPDATE users SET reg_state=?,last_seen=? WHERE chat_id=?',(state,now_iso(),chat_id))


def save_profile(chat_id:int, full_name:str, group):
    code,title,url=group
    with connect() as c:
        c.execute('UPDATE users SET full_name=?,group_code=?,group_url=?,reg_state=?,last_seen=? WHERE chat_id=?',
                  (full_name,code,url,'',now_iso(),chat_id))


def profile(chat_id:int):
    with connect() as c:
        return c.execute('SELECT chat_id,full_name,group_code,group_url,sponsor_ok,reg_state,daily_enabled,change_enabled,muted FROM users WHERE chat_id=?',(chat_id,)).fetchone()


def set_sponsor(chat_id:int):
    with connect() as c: c.execute('UPDATE users SET sponsor_ok=1,last_seen=? WHERE chat_id=?',(now_iso(),chat_id))


def sponsor_ok(chat_id:int)->bool:
    p=profile(chat_id); return bool(p and p[4])


def reg_complete(chat_id:int)->bool:
    p=profile(chat_id); return bool(p and p[1] and p[2] and p[3])


def safe_fio(v:str)->bool:
    v=re.sub(r'\s+',' ',(v or '').strip())
    parts=v.split(' ')
    if not 2<=len(parts)<=4: return False
    if any(not re.fullmatch(r'[А-Яа-яЁёA-Za-z-]{2,40}',x) for x in parts): return False
    bad={'тест тест','иван иван иван','адольф гитлер','микки маус','гарри поттер','шерлок холмс'}
    return v.lower() not in bad


async def require_ready(update:Update, context:ContextTypes.DEFAULT_TYPE)->bool:
    chat=update.effective_chat.id
    u=update.effective_user
    register_user(chat,u.username if u else '',u.first_name if u else '')
    p=profile(chat)
    if not reg_complete(chat):
        state=p[5] if p else ''
        if state=='await_group':
            await reply_ui(update,context,'🎓 Напиши свою группу, например <b>ОИ-11.1</b>. Можно с пробелами, дефисом или без него.',parse_mode=ParseMode.HTML)
        elif state=='await_fio':
            await reply_ui(update,context,'👤 Напиши <b>ФИО полностью</b> одним сообщением.',parse_mode=ParseMode.HTML)
        else:
            set_registration(chat,'await_group')
            await reply_ui(update,context,'🎓 <b>Выбери свою группу</b>\n\nПросто напиши её названием, например <code>ОИ-11.1</code>. Я сам найду нужную страницу расписания СГУГиТ.',parse_mode=ParseMode.HTML)
        return False
    return True


def sponsor_personal_exempt(chat_id:int)->bool:
    with connect() as c:
        row=c.execute('SELECT personal FROM sponsor_exemptions WHERE chat_id=?',(chat_id,)).fetchone()
    return bool(row and row[0])

def sponsor_group_exempt(group_code:str)->bool:
    if not group_code: return False
    with connect() as c:
        row=c.execute('SELECT 1 FROM group_sponsor_exemptions WHERE group_code=?',(group_code,)).fetchone()
    return bool(row)

def sponsor_requirement_satisfied(chat_id:int)->bool:
    # Sponsor is no longer an access requirement. Kept as a compatibility
    # function so older callbacks/plugins cannot accidentally re-enable a gate.
    return True

def sponsor_benefit_state(chat_id:int):
    p=profile(chat_id); g=p[2] if p else ''
    with connect() as c:
        row=c.execute('SELECT personal,group_enabled,stars FROM sponsor_exemptions WHERE chat_id=?',(chat_id,)).fetchone()
    personal=bool(row and row[0]); group=bool(row and row[1]) or sponsor_group_exempt(g)
    return personal,group,(row[2] if row else 0)

def trust_streak(leader_id:int, group_code:str='')->int:
    with connect() as c:
        row=c.execute('SELECT approved_streak FROM leader_trust WHERE leader_id=?',(leader_id,)).fetchone()
    return int(row[0]) if row else 0

def trusted_leader(leader_id:int)->bool:
    return trust_streak(leader_id) >= TRUSTED_LEADER_STREAK

def update_trust(leader_id:int, group_code:str, approved:bool):
    with connect() as c:
        row=c.execute('SELECT approved_streak,approved_total,rejected_total FROM leader_trust WHERE leader_id=?',(leader_id,)).fetchone()
        streak,total,rejected=row if row else (0,0,0)
        if approved:
            streak += 1; total += 1
        else:
            streak = 0; rejected += 1
        c.execute('INSERT INTO leader_trust(leader_id,group_code,approved_streak,approved_total,rejected_total,updated_at) VALUES(?,?,?,?,?,?) '
                  'ON CONFLICT(leader_id) DO UPDATE SET group_code=excluded.group_code,approved_streak=excluded.approved_streak,approved_total=excluded.approved_total,rejected_total=excluded.rejected_total,updated_at=excluded.updated_at',
                  (leader_id,group_code,streak,total,rejected,now_iso()))

def moderation_score(kind:str, payload:dict):
    """Local safety check. Returns accept/reject/review + reason. No external AI is required."""
    text=' '.join(str(payload.get(k,'')) for k in ('title','question','text','reason','options')).lower()
    text=re.sub(r'\s+',' ',text).strip()
    hard=[r'\bказино\b',r'\bставк',r'\bнаркот',r'\bкуплю\s+аккаунт',r'\bпродам\s+аккаунт',r'\bвзлом',r'\bпарол',r'\bкарта\s*банка',r'\bперевед(и|ите)\s+деньги',r'\bмат[ьь]']
    if any(re.search(x,text) for x in hard): return 'reject','Найдены признаки спама, сомнительных услуг или небезопасного содержания.'
    if len(text)<8: return 'reject','Слишком короткий текст.'
    if len(text)>1800: return 'reject','Слишком большой текст.'
    if kind=='poll':
        opts=payload.get('options') or []
        if not 2<=len(opts)<=8: return 'reject','Некорректное количество вариантов.'
        if len(set(x.strip().lower() for x in opts))!=len(opts): return 'reject','Повторяющиеся варианты ответа.'
    suspicious=[r'http://',r'https://',r't\.me/',r'\bреклама\b',r'\bзаработ',r'\bскидк',r'\bпродаж']
    if any(re.search(x,text) for x in suspicious): return 'review','В тексте есть ссылка или рекламный признак.'
    if text.count('!')>=5 or text.count('🔥')>=3: return 'review','Необычно много рекламных/эмоциональных маркеров.'
    return 'accept','Проверка пройдена.'


# ============================================================
# Student natural-language assistant: «следующая пара», «ближайшая пара» and free-form schedule questions.
# ============================================================

_WEEKDAY_ALIASES = {
    'пн': 0, 'понедельник': 0,
    'вт': 1, 'вторник': 1,
    'ср': 2, 'среда': 2,
    'чт': 3, 'четверг': 3,
    'пт': 4, 'пятница': 4,
    'сб': 5, 'суббота': 5,
    'вс': 6, 'воскресенье': 6,
}


def _assistant_target_date(text: str, base: date | None = None) -> date:
    """Resolve Russian natural-language date references without external AI."""
    q = re.sub(r'\s+', ' ', (text or '').strip().lower().replace('ё', 'е'))
    d = base or now().date()
    if re.search(r'\bпослезавтра\b', q):
        return d + timedelta(days=2)
    if re.search(r'\bзавтра\b', q):
        return d + timedelta(days=1)
    if re.search(r'\bсегодня\b|\bсейчас\b', q):
        return d
    if re.search(r'\bвчера\b', q):
        return d - timedelta(days=1)
    # Numeric dates: 08.10 or 08.10.2026
    m = re.search(r'\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b', q)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else d.year
        if year < 100:
            year += 2000
        try:
            candidate = date(year, month, day)
            if not m.group(3) and candidate < d - timedelta(days=30):
                candidate = date(year + 1, month, day)
            return candidate
        except ValueError:
            pass
    # Weekday references. "в пятницу" means the next occurrence, while
    # "в эту пятницу" also means the current week's occurrence.
    for name, weekday in _WEEKDAY_ALIASES.items():
        if re.search(r'\b' + re.escape(name) + r'\b', q):
            delta = (weekday - d.weekday()) % 7
            if delta == 0 and re.search(r'\bследующ(?:ий|ую|ем|ая)?\b', q):
                delta = 7
            return d + timedelta(days=delta)
    return d


def _assistant_normalize(text: str) -> str:
    q = (text or '').lower().replace('ё', 'е')
    q = re.sub(r'[«»"“”]', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q


def _assistant_subject_candidates(query: str, lessons: list[Lesson]) -> list[Lesson]:
    """Find lessons by subject/teacher/room using tolerant token matching."""
    q = _assistant_normalize(query)
    stop = {
        'когда','во','в','на','по','мне','у','меня','будет','есть','пара','пары',
        'занятие','занятия','следующая','следующее','следующие','ближайшая','ближайшее',
        'завтра','сегодня','послезавтра','понедельник','вторник','среда','четверг',
        'пятница','суббота','воскресенье','покажи','покажите','какая','какие','какой',
        'сколько','где','аудитория','кабинет','преподаватель','препода','есть','ли',
        'моя','мои','мое','мой','расписание','занятий','занятии','часов','час','времени',
    }
    tokens=[x for x in re.findall(r'[a-zа-я0-9.-]{2,}', q) if x not in stop]
    if not tokens:
        return []
    from difflib import SequenceMatcher
    scored=[]
    for lesson in lessons:
        hay=' '.join((lesson.subject, lesson.teacher, lesson.room, lesson.kind)).lower().replace('ё','е')
        token_hits=sum(1 for t in tokens if t in hay)
        fuzzy=max((SequenceMatcher(None,t,hay).ratio() for t in tokens), default=0)
        if token_hits or fuzzy >= 0.55:
            score=token_hits*2+fuzzy
            scored.append((score, lesson))
    scored.sort(key=lambda x:x[0], reverse=True)
    return [x[1] for x in scored[:8]]


def _assistant_time_text(lesson: Lesson) -> str:
    return f'⏰ <b>{esc(lesson.start)}–{esc(lesson.end)}</b>'


async def answer_student_question(chat_id: int, text: str) -> str:
    """Answer common student questions from the user's actual schedule.

    This is intentionally local and deterministic: it needs no secret API key,
    never invents lessons, and falls back with a useful explanation when a
    question is outside the schedule domain.
    """
    p=profile(chat_id)
    if not reg_complete(chat_id):
        return '⚠️ Сначала заполни профиль: группу и ФИО. После этого я смогу отвечать по твоему расписанию.'
    q=_assistant_normalize(text)
    if not q:
        return '🤖 Напиши вопрос, например: «что завтра?», «во сколько первая пара в пятницу?» или «когда геодезия?».'

    target=_assistant_target_date(q)
    data=await group_data(chat_id)
    # Apply owner/leader corrections before answering.
    day_lessons=apply_manual_overrides(target, data.get(target, []), p[2])[0]

    asks_next=bool(re.search(r'\bследующ(?:ая|ую|ая|ий|ую|ем)?\b|\bближайш',q))
    asks_count=bool(re.search(r'\bсколько\b.*\b(пар|занят|урок)',q))
    asks_room=bool(re.search(r'\b(где|аудитор|кабинет|корпус|место)\b',q))
    asks_time=bool(re.search(r'\b(во сколько|когда|время|начинается|начнется|начнётся|заканчивается|закончится)\b',q))
    asks_schedule=bool(re.search(r'\b(расписан|пары|занят|урок|учеб)',q))
    asks_first=bool(re.search(r'\bперв(?:ая|ую|ой|ое)\b',q))
    asks_last=bool(re.search(r'\bпоследн(?:яя|юю|ей|ее)\b',q))

    # Explicit "next lesson" searches across the next 8 days.
    if asks_next or re.search(r'\b(ближайш|следующ)\s+(пара|занят)',q):
        cur=now(); candidates=[]
        for off in range(8):
            d=cur.date()+timedelta(days=off)
            lessons=apply_manual_overrides(d,data.get(d,[]),p[2])[0]
            for lesson in lessons:
                try:
                    dt=datetime.combine(d,datetime.strptime(lesson.start,'%H:%M').time(),tzinfo=TZ)
                except ValueError:
                    continue
                if dt>cur:
                    candidates.append((dt,d,lesson))
        if not candidates:
            return '🎉 Ближайших занятий не найдено в загруженном расписании.'
        dt,d,lesson=min(candidates,key=lambda x:x[0])
        extra=[]
        if lesson.teacher: extra.append(f'👨‍🏫 {esc(lesson.teacher)}')
        if lesson.room: extra.append(f'📍 {esc(lesson.room)}')
        return '🤖 <b>Ближайшая пара</b>\n\n' + f'📅 <b>{esc(date_ru(d))}</b>\n{_assistant_time_text(lesson)}\n📚 <b>{esc(lesson.subject)}</b>' + (('\n'+'\n'.join(extra)) if extra else '')

    if asks_count:
        return f'🤖 <b>{esc(date_ru(target))}</b>\n\n📚 Пар: <b>{len(day_lessons)}</b>.'

    # Collect the full target day's schedule for broad schedule questions.
    if asks_schedule and not asks_time and not asks_room and not asks_first and not asks_last:
        return format_day(target,day_lessons)

    # First/last lesson of a day.
    if asks_first or asks_last:
        if not day_lessons:
            return f'🤖 {esc(date_ru(target))}: занятий нет.'
        lesson=day_lessons[-1] if asks_last else day_lessons[0]
        label='Последняя' if asks_last else 'Первая'
        return f'🤖 <b>{label} пара</b> · {esc(date_ru(target))}\n\n{_assistant_time_text(lesson)}\n📚 <b>{esc(lesson.subject)}</b>' + (f'\n👨‍🏫 {esc(lesson.teacher)}' if lesson.teacher else '') + (f'\n📍 {esc(lesson.room)}' if lesson.room else '')

    # Subject/teacher/room search in the target day first, then next 14 days.
    pool=list(day_lessons)
    if asks_time or asks_room or not asks_schedule:
        for off in range(1,14):
            d=target+timedelta(days=off)
            pool.extend(apply_manual_overrides(d,data.get(d,[]),p[2])[0])
    matches=_assistant_subject_candidates(q,pool)
    if matches:
        # Prefer target-day matches when question contains a concrete date/day.
        target_matches=[l for l in day_lessons if l in matches]
        if target_matches:
            matches=target_matches
            label=esc(date_ru(target))
        else:
            # Recover the date for the best match by scanning forward.
            found=None
            for off in range(14):
                d=target+timedelta(days=off)
                if any(l.key()==matches[0].key() for l in apply_manual_overrides(d,data.get(d,[]),p[2])[0]):
                    found=d; break
            label=esc(date_ru(found)) if found else 'ближайшее расписание'
        if len(matches)==1 or asks_time or asks_room:
            l=matches[0]
            return f'🤖 <b>{label}</b>\n\n📚 <b>{esc(l.subject)}</b>\n{_assistant_time_text(l)}' + (f'\n👨‍🏫 {esc(l.teacher)}' if l.teacher else '') + (f'\n📍 <b>{esc(l.room)}</b>' if l.room else '')
        lines=[f'🤖 <b>Нашёл {len(matches)} подходящих занятий</b>']
        for l in matches[:6]:
            lines.append(f'• {esc(l.start)}–{esc(l.end)} · <b>{esc(l.subject)}</b>' + (f' · {esc(l.room)}' if l.room else ''))
        return '\n'.join(lines)

    if asks_room and day_lessons:
        return format_day(target,day_lessons)

    return ('🤖 Я умею отвечать по твоему расписанию.\n\n'
            'Попробуй спросить:\n'
            '• «что завтра?»\n'
            '• «во сколько первая пара в пятницу?»\n'
            '• «сколько пар завтра?»\n'
            '• «где следующая пара?»\n'
            '• «когда геодезия?»\n'
            '• «когда у меня математика?»')


def sponsor_button_allowed(chat_id:int)->bool:
    if not sponsor_url():
        return False
    personal,group,_=sponsor_benefit_state(chat_id)
    return not personal and not group


def sponsor_click_token(chat_id: int) -> str:
    # Signed short-lived token: Telegram opens our redirect endpoint, which records
    # the click and immediately redirects the user to the sponsor.
    ts = int(now().timestamp())
    nonce = secrets.token_urlsafe(8)
    payload = f"{chat_id}:{ts}:{nonce}".encode()
    sig = hmac.new(globals().get('SPONSOR_TRACKING_SECRET') or sponsor_tracking_secret(), payload, hashlib.sha256).hexdigest()[:32]
    raw = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{raw}.{sig}"

def sponsor_click_url(chat_id: int) -> str:
    if not PUBLIC_BASE_URL:
        return sponsor_url()
    return f"{PUBLIC_BASE_URL}/sponsor/click?token={sponsor_click_token(chat_id)}" if PUBLIC_BASE_URL and sponsor_url() else sponsor_url()

def sponsor_open_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    # Defensive fallback: when the owner disabled the sponsor, never emit an
    # inline button without an action (Telegram rejects such buttons as text buttons).
    if not sponsor_url():
        return InlineKeyboardMarkup([[InlineKeyboardButton('‹ В меню', callback_data='p:menu')]])
    # Primary action is a tracked HTTPS redirect. The callback is an explicit
    # fallback for Telegram clients that block/interrupt the external browser.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(sponsor_button_text(), url=sponsor_click_url(chat_id))],
        [InlineKeyboardButton('✅ Я уже открыл спонсора', callback_data='sponsor:open')],
    ])

def publication_keyboard(req_id:int, kind:str):
    return InlineKeyboardMarkup([[InlineKeyboardButton('✅ Одобрить',callback_data=f'mod:approve:{req_id}'), InlineKeyboardButton('❌ Отклонить',callback_data=f'mod:reject:{req_id}')]])

async def submit_publication(application, leader_id:int, group_code:str, kind:str, payload:dict, context=None):
    decision,reason=moderation_score(kind,payload)
    with connect() as c:
        cur=c.execute('INSERT INTO publication_requests(leader_id,group_code,kind,payload_json,status,decision,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
                      (leader_id,group_code,kind,json.dumps(payload,ensure_ascii=False), 'pending',decision,reason,now_iso()))
        req_id=cur.lastrowid
    must_owner = not trusted_leader(leader_id)
    if decision=='reject':
        with connect() as c: c.execute("UPDATE publication_requests SET status='rejected',reviewed_at=?,reviewed_by=0 WHERE id=?",(now_iso(),req_id))
        update_trust(leader_id,group_code,False)
        return 'reject',reason,req_id
    if must_owner or decision=='review':
        label='📢 Объявление' if kind=='announcement' else '📊 Опрос'
        payload_text=payload.get('text') if kind=='announcement' else (f"<b>{esc(payload.get('title',''))}</b>\n\n{esc(payload.get('question',''))}\n\nВарианты: " + ', '.join(esc(x) for x in payload.get('options',[])))
        note='🧠 Бот уверен не полностью — нужна проверка владельца.' if decision=='review' else '🔐 Новая публикация старосты на обязательную проверку.'
        kb=publication_keyboard(req_id,kind)
        await application.bot.send_message(OWNER_ID, f'🛡 <b>Модерация #{req_id}</b>\n\n👑 Староста: <code>{leader_id}</code>\n🎓 Группа: <b>{esc(group_code)}</b>\n\n{label}\n{payload_text}\n\n{note}', parse_mode=ParseMode.HTML, reply_markup=kb, disable_notification=True)
        return 'owner',reason,req_id
    # Hidden automatic approval for trusted leaders.
    await publish_request(application,req_id,owner=False)
    return 'accept',reason,req_id

async def publish_request(application, req_id:int, owner:bool=False):
    with connect() as c:
        row=c.execute('SELECT leader_id,group_code,kind,payload_json,status FROM publication_requests WHERE id=?',(req_id,)).fetchone()
    if not row or row[4] not in ('pending','approved'): return False
    leader_id,group_code,kind,payload_json,_=row; payload=json.loads(payload_json)
    if kind=='announcement':
        await send_group(application,group_code,f'📢 <b>Объявление</b>\n\n{esc(payload["text"])}',premium_menu,kind='announcements')
    else:
        with connect() as c:
            cur=c.execute('INSERT INTO polls(leader_id,group_code,title,question,options_json,require_photo,created_at) VALUES(?,?,?,?,?,?,?)',(leader_id,group_code,payload['title'],payload['question'],json.dumps(payload['options'],ensure_ascii=False),payload.get('require_photo',0),now_iso())); pid=cur.lastrowid
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(o,callback_data=f'pollvote:{pid}:{i}')] for i,o in enumerate(payload['options'])])
        extra='\n\n📸 После ответа отправь скриншот.' if payload.get('require_photo') else ''
        await send_group(application,group_code,f'📊 <b>{esc(payload["title"])}</b>\n\n{esc(payload["question"])}{extra}',kb,kind='polls')
    with connect() as c: c.execute("UPDATE publication_requests SET status='published',reviewed_at=?,reviewed_by=? WHERE id=?",(now_iso(),OWNER_ID if owner else 0,req_id))
    update_trust(leader_id,group_code,True)
    return True

def sponsor_button_text()->str:
    try:
        with connect() as c:
            row=c.execute("SELECT value FROM bot_settings WHERE key='sponsor_button_text'").fetchone()
        return (row[0] if row and row[0] else '⭐ Спонсор')[:64]
    except Exception:
        return '⭐ Спонсор'


def premium_menu(chat_id:int):
    # User-facing menu is intentionally fixed: exactly five rows.
    rows=[
        [InlineKeyboardButton('📅 Расписание',callback_data='p:schedule')],
        [InlineKeyboardButton('📝 Задания',callback_data='p:tasks'),InlineKeyboardButton('🤖 ИИ-помощник',callback_data='p:ai')],
        [InlineKeyboardButton('👥 Пригласить друзей',callback_data='p:invite')],
        [InlineKeyboardButton('🔔 Уведомления',callback_data='p:notify'),InlineKeyboardButton('⚙️ Профиль',callback_data='p:profile')],
    ]
    if sponsor_button_allowed(chat_id):
        rows.append([InlineKeyboardButton(sponsor_button_text(),url=sponsor_click_url(chat_id))])
    if chat_id == OWNER_ID:
        rows.append([InlineKeyboardButton('🛠 Панель владельца',callback_data='owner:overview')])
    return InlineKeyboardMarkup(rows)


def schedule_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📖 Сегодня',callback_data='today'),InlineKeyboardButton('📆 Завтра',callback_data='tomorrow')],
        [InlineKeyboardButton('🗓 7 дней',callback_data='week'),InlineKeyboardButton('⏭ Следующая',callback_data='next')],
        [InlineKeyboardButton('🔄 Обновить',callback_data='refresh'),InlineKeyboardButton('‹ Назад',callback_data='p:menu')],
    ])


def task_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ Добавить', callback_data='task:add')],
        [InlineKeyboardButton('📋 Мои задания', callback_data='task:list')],
        [InlineKeyboardButton('👥 Видимость', callback_data='profile:tasks')],
        [InlineKeyboardButton('‹ Назад', callback_data='p:menu')],
    ])

def task_list_keyboard(chat_id: int):
    with connect() as c:
        rows = c.execute('SELECT id, done FROM tasks WHERE chat_id=? ORDER BY done ASC, id DESC LIMIT 20', (chat_id,)).fetchall()
    buttons=[]
    for task_id, done in rows:
        buttons.append([
            InlineKeyboardButton('↩️ Выполнить' if not done else '↩️ Вернуть', callback_data=f'task:done:{task_id}:{0 if done else 1}'),
            InlineKeyboardButton('🗑 Удалить', callback_data=f'task:delete:{task_id}'),
        ])
    buttons.append([InlineKeyboardButton('‹ К заданиям', callback_data='p:tasks')])
    return InlineKeyboardMarkup(buttons)


def leader_premium_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📅 Расписание',callback_data='p:leader:schedule')],
        [InlineKeyboardButton('📢 Объявление',callback_data='lead:announce'),InlineKeyboardButton('📊 Опрос',callback_data='poll:new')],
        [InlineKeyboardButton('📸 Опросы / ответы',callback_data='poll:list')],
        [InlineKeyboardButton('✏️ Правки расписания',callback_data='leader:edit')],
        [InlineKeyboardButton('👥 Состав группы',callback_data='lead:students'),InlineKeyboardButton('🔗 Пригласить',callback_data='lead:invite')],
        [InlineKeyboardButton('‹ Назад',callback_data='p:menu')],
    ])


# ============================================================
# OWNER CONTROL CENTER
# ============================================================

def owner_only(chat_id:int)->bool:
    return chat_id == OWNER_ID


def owner_panel_keyboard()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📖 Команды и подсказки',callback_data='owner:help')],
        [InlineKeyboardButton('📊 Обзор',callback_data='owner:overview'),InlineKeyboardButton('👥 Пользователи',callback_data='owner:users')],
        [InlineKeyboardButton('🎓 Группы',callback_data='owner:groups'),InlineKeyboardButton('👑 Старосты',callback_data='owner:leaders')],
        [InlineKeyboardButton('🛡 Модерация',callback_data='owner:moderation'),InlineKeyboardButton('📣 Рассылка',callback_data='owner:broadcast')],
        [InlineKeyboardButton('⭐ Спонсор',callback_data='owner:sponsor'),InlineKeyboardButton('📈 Активность',callback_data='owner:activity')],
        [InlineKeyboardButton('🧰 Управление пользователем',callback_data='owner:user:find'),InlineKeyboardButton('👑 Управление старостами',callback_data='owner:leader:manage')],
        [InlineKeyboardButton('🎓 Управление группой',callback_data='owner:group:manage'),InlineKeyboardButton('📅 Правки расписания',callback_data='owner:schedule')],
        [InlineKeyboardButton('📊 Excel-отчёт сейчас',callback_data='owner:report'),InlineKeyboardButton('⚙️ Система',callback_data='owner:system')],
        [InlineKeyboardButton('‹ Закрыть',callback_data='p:menu')],
    ])


def owner_user(chat_id:int):
    with connect() as c:
        return c.execute('SELECT chat_id,full_name,username,group_code,muted,sponsor_ok,last_seen FROM users WHERE chat_id=?',(chat_id,)).fetchone()


def owner_set_muted(chat_id:int, muted:bool):
    with connect() as c:
        c.execute('UPDATE users SET muted=?,last_seen=? WHERE chat_id=?',(1 if muted else 0,now_iso(),chat_id))


def owner_set_group(chat_id:int, group_code:str):
    status, rows, _ = resolve_group(group_code)
    if status not in ('exact','fuzzy') or not rows:
        raise ValueError('group_not_found')
    g=rows[0]
    with connect() as c:
        c.execute("UPDATE users SET group_code=?,group_url=?,reg_state='' WHERE chat_id=?",(g[0],g[2],chat_id))
    return g


def owner_remove_group(chat_id:int):
    with connect() as c:
        c.execute("UPDATE users SET group_code='',group_url='',reg_state='await_group' WHERE chat_id=?",(chat_id,))


def owner_revoke_leader(chat_id:int):
    with connect() as c:
        c.execute("DELETE FROM leaders WHERE chat_id=?",(chat_id,))


def owner_group_users(group_code:str):
    with connect() as c:
        return c.execute("SELECT chat_id,full_name,username,muted FROM users WHERE group_code=? ORDER BY full_name,chat_id",(group_code,)).fetchall()


def owner_group_codes(limit:int=50):
    with connect() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT group_code FROM users WHERE group_code!='' ORDER BY group_code LIMIT ?",(limit,)).fetchall()]


def owner_overview_text()->str:
    with connect() as c:
        users=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        complete=c.execute("SELECT COUNT(*) FROM users WHERE full_name!='' AND group_code!=''").fetchone()[0]
        groups=c.execute("SELECT COUNT(DISTINCT group_code) FROM users WHERE group_code!=''").fetchone()[0]
        leaders=c.execute('SELECT COUNT(*) FROM leaders').fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM publication_requests WHERE status='pending'").fetchone()[0]
        active7=c.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?",((now()-timedelta(days=7)).isoformat(),)).fetchone()[0]
        sponsors=c.execute("SELECT COUNT(*) FROM sponsor_exemptions WHERE personal=1").fetchone()[0]
    return (f'🛠 <b>Панель владельца</b>\n\n'
            f'👥 Пользователей: <b>{users}</b>\n'
            f'✅ Заполнили профиль: <b>{complete}</b>\n'
            f'🎓 Активных групп: <b>{groups}</b>\n'
            f'👑 Старост: <b>{leaders}</b>\n'
            f'🛡 На модерации: <b>{pending}</b>\n'
            f'🔥 Активны за 7 дней: <b>{active7}</b>\n'
            f'⭐ Отключили спонсора: <b>{sponsors}</b>')


def owner_user_rows(limit=50):
    with connect() as c:
        return c.execute('''SELECT chat_id,full_name,username,group_code,registered_at,last_seen,muted,sponsor_ok
                            FROM users ORDER BY last_seen DESC LIMIT ?''',(limit,)).fetchall()


def owner_activity_text()->str:
    with connect() as c:
        rows=c.execute('SELECT event,COUNT(*) n FROM events WHERE created_at>=? GROUP BY event ORDER BY n DESC LIMIT 15',((now()-timedelta(days=7)).isoformat(),)).fetchall()
    if not rows: return '📈 <b>Активность за 7 дней</b>\n\nПока данных мало.'
    return '📈 <b>Активность за 7 дней</b>\n\n'+'\n'.join(f'• {esc(str(e))}: <b>{n}</b>' for e,n in rows)


def owner_commands_help()->str:
    return ('📖 <b>Подсказка владельцу</b>\n\n'
            '<b>Команды</b>\n'
            '• /panel — панель владельца\n'
            '• /panel ГРУППА — кабинет группы\n'
            '• /owner_help — эта памятка\n'
            '• /leader_apps — заявки старост\n'
            '• /help — пользовательская помощь\n\n'
            '<b>Панель</b>\n'
            '• пользователи и группы; старосты; рассылки; модерация; правки расписания; Excel; активность; настройки.\n\n'
            '💡 Настройки владельца хранятся в SQLite и не требуют секретов в .env.')


async def owner_panel_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OWNER_ID: return
    raw=' '.join(context.args).strip()
    if raw:
        context.user_data['owner_panel_group']=raw
        status,rows,similar=resolve_group(raw)
        if status in ('exact','fuzzy') and rows:
            g=rows[0][0]; context.user_data['owner_panel_group']=g
            await reply_ui(update,context,f'👑 <b>Кабинет старосты</b>\n\n🎓 Группа: <b>{esc(g)}</b>\n\nТы вошёл в кабинет этой группы как владелец.',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return
    context.user_data.pop('owner_panel_group',None)
    await reply_ui(update,context,owner_overview_text(),parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard())


async def owner_panel_group_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OWNER_ID: return
    raw=' '.join(context.args).strip()
    if not raw:
        await reply_ui(update,context,'Использование: <code>/panel ОИ-11.1</code>',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
    status,rows,similar=resolve_group(raw)
    if status not in ('exact','fuzzy') or not rows:
        if similar:
            kb=[[InlineKeyboardButton(g[0],callback_data=f'owner:panel:{g[0]}')] for g in similar[:8]]
            await reply_ui(update,context,'🎓 Выбери группу:',reply_markup=InlineKeyboardMarkup(kb)); return
        await reply_ui(update,context,'❌ Группа не найдена.',reply_markup=owner_panel_keyboard()); return
    g=rows[0][0]; context.user_data['owner_panel_group']=g
    await reply_ui(update,context,f'👑 <b>Кабинет старосты</b>\n\n🎓 Группа: <b>{esc(g)}</b>\n\nТы вошёл в кабинет этой группы как владелец.',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu())



async def build_owner_excel()->Path:
    # Build a valid Excel report atomically and return its path.
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from zipfile import ZipFile, BadZipFile

    reports_dir = BASE_DIR / 'data' / 'reports'
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime('%Y-%m-%d_%H-%M-%S_%f')
    path = reports_dir / f'sgugit_report_{stamp}.xlsx'
    tmp_path = reports_dir / f'.{path.name}.tmp'

    def style_sheet(ws):
        if ws.max_row >= 1:
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(patternType='solid', fgColor='D9EAF7')
                cell.alignment = Alignment(vertical='center')
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
        for idx, column_cells in enumerate(ws.iter_cols(), start=1):
            values = [str(cell.value or '') for cell in column_cells]
            width = min(42, max(12, max((len(v) for v in values), default=0) + 2))
            ws.column_dimensions[get_column_letter(idx)].width = width

    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводка'
    ws.append(['Показатель', 'Значение'])

    with connect() as c:
        total = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        filled = c.execute("SELECT COUNT(*) FROM users WHERE full_name!='' AND group_code!=''").fetchone()[0]
        active24 = c.execute('SELECT COUNT(*) FROM users WHERE last_seen>=?', ((now() - timedelta(days=1)).isoformat(),)).fetchone()[0]
        active7 = c.execute('SELECT COUNT(*) FROM users WHERE last_seen>=?', ((now() - timedelta(days=7)).isoformat(),)).fetchone()[0]
        leaders = c.execute('SELECT COUNT(*) FROM leaders').fetchone()[0]
        sponsor_off = c.execute('SELECT COUNT(*) FROM sponsor_exemptions WHERE personal=1').fetchone()[0]
        user_rows = c.execute('''
            SELECT chat_id,full_name,username,group_code,registered_at,last_seen,
                   sponsor_ok,quiet_enabled,notify_daily,notify_lessons,
                   notify_changes,notify_tasks,notify_announcements,notify_polls,
                   notify_applications,notify_system
            FROM users ORDER BY group_code,full_name,chat_id
        ''').fetchall()

        ws.append(['Всего пользователей', total])
        ws.append(['Профиль заполнен', filled])
        ws.append(['Активны за 24 часа', active24])
        ws.append(['Активны за 7 дней', active7])
        ws.append(['Старосты', leaders])
        ws.append(['Отключили спонсора', sponsor_off])
        ws.append(['Сформировано', now().strftime('%d.%m.%Y %H:%M:%S')])

        users_ws = wb.create_sheet('Пользователи')
        users_ws.append(['Chat ID','ФИО','Username','Группа','Зарегистрирован','Последняя активность','Дней с регистрации','Дней без активности','Спонсор включён','Спонсор отключён','Тихие часы','Уведомления','Событий за 7 дней'])
        cutoff = (now() - timedelta(days=7)).isoformat()
        for r in user_rows:
            try:
                reg = datetime.fromisoformat(r[4]) if r[4] else now()
            except Exception:
                reg = now()
            try:
                last = datetime.fromisoformat(r[5]) if r[5] else now()
            except Exception:
                last = now()
            event_count = c.execute('SELECT COUNT(*) FROM events WHERE data LIKE ? AND created_at>=?', (f'%student={r[0]}%', cutoff)).fetchone()[0]
            personal = c.execute('SELECT personal FROM sponsor_exemptions WHERE chat_id=?', (r[0],)).fetchone()
            notify = sum(int(x or 0) for x in r[8:16])
            users_ws.append([r[0], r[1] or '', ('@'+r[2]) if r[2] else '', r[3] or '', r[4] or '', r[5] or '', max(0,(now()-reg).days), max(0,(now()-last).days), 'Да' if r[6] else 'Нет', 'Да' if personal and personal[0] else 'Нет', 'Да' if r[7] else 'Нет', f'{notify}/8', event_count])

        groups_ws = wb.create_sheet('Группы')
        groups_ws.append(['Группа','Студентов','Старост'])
        for group_code, count in c.execute("SELECT group_code,COUNT(*) FROM users WHERE group_code!='' GROUP BY group_code ORDER BY group_code").fetchall():
            leader_count = c.execute('SELECT COUNT(*) FROM leaders l JOIN users u ON u.chat_id=l.chat_id WHERE u.group_code=?', (group_code,)).fetchone()[0]
            groups_ws.append([group_code, count, leader_count])

        leaders_ws = wb.create_sheet('Старосты')
        leaders_ws.append(['Chat ID','Имя','Username','Группа','Назначен'])
        for r in c.execute('SELECT l.chat_id,l.first_name,l.username,u.group_code,l.added_at FROM leaders l LEFT JOIN users u ON u.chat_id=l.chat_id ORDER BY u.group_code,l.chat_id').fetchall():
            leaders_ws.append([r[0],r[1] or '',('@'+r[2]) if r[2] else '',r[3] or '',r[4]])

        tasks_ws = wb.create_sheet('Задания')
        tasks_ws.append(['ID','Автор','Группа','Предмет','Текст','День пары','Время','Срок','Выполнено','Видно группе'])
        try:
            rows = c.execute('SELECT t.id,t.chat_id,u.group_code,t.subject,t.text,t.lesson_day,t.lesson_start,t.due_at,t.done,t.shared FROM tasks t LEFT JOIN users u ON u.chat_id=t.chat_id ORDER BY t.id DESC LIMIT 5000').fetchall()
            for r in rows:
                tasks_ws.append(list(r))
        except sqlite3.Error:
            pass

        polls_ws = wb.create_sheet('Опросы')
        polls_ws.append(['ID','Староста','Группа','Название','Вопрос','Создан','Фото обязательно'])
        try:
            for r in c.execute('SELECT id,leader_id,group_code,title,question,created_at,require_photo FROM polls ORDER BY id DESC LIMIT 5000').fetchall():
                polls_ws.append(list(r))
        except sqlite3.Error:
            pass

        answers_ws = wb.create_sheet('Ответы опросов')
        answers_ws.append(['Опрос','Студент','Группа','Вариант','Скриншот','Дата'])
        try:
            for r in c.execute("SELECT a.poll_id,a.chat_id,u.group_code,a.option_text,CASE WHEN a.photo_file_id!='' THEN 'Да' ELSE 'Нет' END,a.created_at FROM poll_answers a LEFT JOIN users u ON u.chat_id=a.chat_id ORDER BY a.id DESC LIMIT 10000").fetchall():
                answers_ws.append(list(r))
        except sqlite3.Error:
            pass

        reminders_ws = wb.create_sheet('Напоминания')
        reminders_ws.append(['ID','Chat ID','Текст','Срок','Выполнено'])
        try:
            for r in c.execute('SELECT id,chat_id,text,due_at,done FROM personal_reminders ORDER BY id DESC LIMIT 10000').fetchall():
                reminders_ws.append(list(r))
        except sqlite3.Error:
            pass

        activity_ws = wb.create_sheet('Активность')
        activity_ws.append(['ID','Событие','Данные','Время'])
        for r in c.execute('SELECT id,event,data,created_at FROM events ORDER BY id DESC LIMIT 10000').fetchall():
            activity_ws.append(list(r))

    for sheet in wb.worksheets:
        style_sheet(sheet)
    try:
        wb.save(tmp_path)
        wb.close()
        with ZipFile(tmp_path, 'r') as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise BadZipFile(f'Повреждён XLSX: {bad_member}')
        tmp_path.replace(path)
    except Exception:
        try:
            wb.close()
        except Exception:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path


async def send_owner_excel(application, chat_id: int, caption: str = '📊 Excel-отчёт сформирован.') -> bool:
    try:
        path = await build_owner_excel()
        with path.open('rb') as document:
            await application.bot.send_document(chat_id=chat_id, document=document, filename=path.name, caption=caption, disable_notification=True)
        return True
    except Exception:
        log.exception('Excel report send failed for chat %s', chat_id)
        return False



async def owner_weekly_report(application):
    # Monday 09:00 report; persist only after Telegram accepts the document.
    while True:
        try:
            cur=now()
            if cur.weekday()==0 and (cur.hour>9 or (cur.hour==9 and cur.minute>=0)):
                with connect() as c:
                    last=c.execute('SELECT created_at FROM owner_reports ORDER BY id DESC LIMIT 1').fetchone()
                should_send=not last
                if last:
                    try:
                        should_send=datetime.fromisoformat(last[0]) < cur.replace(hour=9,minute=0,second=0,microsecond=0)
                    except Exception:
                        should_send=True
                if should_send:
                    path=await build_owner_excel()
                    with path.open('rb') as document:
                        await application.bot.send_document(OWNER_ID,document,filename=path.name,caption='📊 Еженедельный отчёт по пользователям и активности.',disable_notification=True)
                    with connect() as c:
                        c.execute('INSERT INTO owner_reports(period_start,period_end,created_at,file_name) VALUES(?,?,?,?)',((cur-timedelta(days=7)).isoformat(),cur.isoformat(),cur.isoformat(),path.name))
        except Exception:
            log.exception('owner weekly report')
        await asyncio.sleep(45)

# --- dynamic schedule -------------------------------------------------
class MultiSchedule:
    cache={}
    loaded={}
    @classmethod
    def load(cls,url,force=False):
        if not force and url in cls.cache and url in cls.loaded and (now()-cls.loaded[url]).total_seconds()<120:
            return cls.cache[url]
        r=requests.get(url,headers=HEADERS,timeout=HTTP_TIMEOUT); r.raise_for_status(); r.encoding=r.apparent_encoding or 'utf-8'
        data=parse_schedule(r.text)
        if not data: raise ScheduleError('Расписание группы не найдено')
        cls.cache[url]=data; cls.loaded[url]=now(); return data


async def group_data(chat_id,force=False):
    p=profile(chat_id)
    if not p or not p[3]: raise ScheduleError('Группа не выбрана')
    return await asyncio.to_thread(MultiSchedule.load,p[3],force)


async def get_day(d:date,force=False,chat_id=None):
    if chat_id is None: raise ScheduleError('chat_id required')
    data=await group_data(chat_id,force); g=profile(chat_id)[2]; lessons,marks=apply_manual_overrides(d,data.get(d,[]),g); return lessons

async def get_day_with_marks(d:date,force=False,chat_id=None):
    if chat_id is None: raise ScheduleError('chat_id required')
    data=await group_data(chat_id,force); g=profile(chat_id)[2]; return apply_manual_overrides(d,data.get(d,[]),g)


# --- notifications ----------------------------------------------------
NOTIFY_SQL = {
    'schedule': 'notify_daily=1 OR notify_lessons=1 OR notify_changes=1',
    'daily': 'notify_daily=1',
    'lessons': 'notify_lessons=1',
    'changes': 'notify_changes=1',
    'tasks': 'notify_tasks=1',
    'announcements': 'notify_announcements=1',
    'polls': 'notify_polls=1',
    'applications': 'notify_applications=1',
    'system': 'notify_system=1',
}

def quiet_now(chat_id:int)->bool:
    with connect() as c:
        row=c.execute('SELECT quiet_enabled,quiet_start,quiet_end FROM users WHERE chat_id=?',(chat_id,)).fetchone()
    if not row or not row[0]: return False
    cur=now().strftime('%H:%M'); start=row[1] or '23:00'; end=row[2] or '07:00'
    return (start <= cur < end) if start < end else (cur >= start or cur < end)

def set_quiet(chat_id:int, enabled:bool):
    with connect() as c: c.execute('UPDATE users SET quiet_enabled=?,last_seen=? WHERE chat_id=?',(1 if enabled else 0,now_iso(),chat_id))

def cycle_reminder_minutes(chat_id:int)->int:
    vals=(15,30,60,90)
    with connect() as c: row=c.execute('SELECT reminder_minutes FROM users WHERE chat_id=?',(chat_id,)).fetchone()
    cur=int(row[0]) if row and row[0] else 60
    nxt=vals[(vals.index(cur)+1)%len(vals)] if cur in vals else 60
    with connect() as c: c.execute('UPDATE users SET reminder_minutes=?,last_seen=? WHERE chat_id=?',(nxt,now_iso(),chat_id))
    return nxt

async def send_group(application,group_code,text,keyboard=None,kind='announcements'):
    condition=NOTIFY_SQL.get(kind, 'notify_announcements=1')
    with connect() as c:
        ids=[r[0] for r in c.execute(f'SELECT chat_id FROM users WHERE group_code=? AND muted=0 AND ({condition})',(group_code,)).fetchall()]
    ids=[x for x in ids if not quiet_now(x)]
    return await send_to_users(application,ids,text,keyboard)


async def daily_broadcast_multi(application,d):
    with connect() as c: groups=[r[0] for r in c.execute("SELECT DISTINCT group_code FROM users WHERE group_code!=''").fetchall()]
    for code in groups:
        with connect() as c: p=c.execute('SELECT group_url FROM users WHERE group_code=? LIMIT 1',(code,)).fetchone()
        if not p: continue
        try:
            data=await asyncio.to_thread(MultiSchedule.load,p[0],False)
            lessons,_=apply_manual_overrides(d,data.get(d,[]),code)
            text=f'🌙 <b>Расписание группы {esc(code)} на завтра</b>\n\n'+format_day(d,lessons)
            await send_group(application,code,text,premium_menu,kind='daily')
        except Exception as e: log.warning('daily %s: %s',code,e)


async def scheduler_multi(application):
    last=''
    while True:
        try:
            cur=now(); key=cur.strftime('%Y-%m-%d %H:%M')
            if cur.hour==NOTIFY_HOUR and cur.minute==NOTIFY_MINUTE and key!=last:
                last=key; await daily_broadcast_multi(application,cur.date()+timedelta(days=1))
            # reminder: about 1 hour before each lesson
            if cur.minute in (0,30):
                with connect() as c: users=c.execute("SELECT chat_id,group_code,group_url FROM users WHERE group_code!='' AND muted=0 AND notify_lessons=1").fetchall()
                for chat,code,url in users:
                    try:
                        data=await asyncio.to_thread(MultiSchedule.load,url,False)
                        for l in data.get(cur.date(),[]):
                            st=datetime.strptime(l.start,'%H:%M').time(); dt=datetime.combine(cur.date(),st,tzinfo=TZ)
                            with connect() as cc: rr=cc.execute('SELECT reminder_minutes FROM users WHERE chat_id=?',(chat,)).fetchone()
                            mins=int(rr[0]) if rr and rr[0] else 60
                            if not quiet_now(chat) and (mins-5)*60 <= (dt-cur).total_seconds() <= (mins+5)*60:
                                key2=f'remind:{chat}:{cur.date()}:{l.start}:{mins}'
                                if not delivered(key2):
                                    await application.bot.send_message(chat_id=chat,text=f'⏰ <b>Через час пара</b>\n\n📚 {esc(l.subject)}\n🕐 {l.start}–{l.end}'+(f'\n🚪 {esc(l.room)}' if l.room else ''),parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); mark_delivered(key2)
                    except Exception: pass
        except Exception: log.exception('scheduler')
        await asyncio.sleep(CLOCK_CHECK_SECONDS)


