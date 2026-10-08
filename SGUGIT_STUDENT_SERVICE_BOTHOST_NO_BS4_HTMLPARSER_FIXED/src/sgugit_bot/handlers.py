from .core import *
from .core import _delete_previous_ui
from .services import *


async def errors(update, context):
    """Global Telegram error handler: log the exception without crashing polling."""
    err = context.error
    log.exception("Unhandled Telegram update error", exc_info=err)
    try:
        if update and getattr(update, "effective_chat", None):
            await context.application.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Произошла внутренняя ошибка. Попробуй ещё раз через несколько секунд.",
            )
    except Exception:
        pass

# --- start / onboarding ------------------------------------------------
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat.id; u=update.effective_user
    register_user(chat,u.username if u else '',u.first_name if u else '')
    if getattr(context,'args',None):
        arg=context.args[0].strip()
        if arg.startswith('join_'):
            token=arg[5:]
            if invite_info(token):
                with connect() as c:
                    c.execute('INSERT INTO pending_invites(chat_id,token,created_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET token=excluded.token,created_at=excluded.created_at',(chat,token,now_iso()))
        else:
            inviter = parse_referral_arg(arg)
            if inviter is not None and register_referral(chat, inviter):
                try:
                    await context.application.bot.send_message(
                        inviter,
                        '🎉 <b>По твоей ссылке открыл бота новый пользователь!</b>\n\n'
                        f'👥 Всего приглашено: <b>{referral_count(inviter)}</b>',
                        parse_mode=ParseMode.HTML, disable_notification=True,
                    )
                except Exception:
                    pass

    p=profile(chat)
    await _delete_previous_ui(context, chat)

    # Приветствие показываем только один раз. Повторный /start у полностью
    # зарегистрированного пользователя сразу открывает главное меню.
    if reg_complete(chat):
        set_registration(chat, '')
        await reply_ui(update, context, '🏠 <b>Главное меню</b>\n\nВыбирай нужный раздел.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        return

    state = p[5] if p else ''
    if state == 'await_welcome':
        await reply_ui(update, context,
            '👋 <b>Добро пожаловать!</b>\n\n'
            '🎓 Расписание • задания • ИИ-помощник • уведомления • староста\n\n'
            '⚠️ Частный проект, не связан с СГУГиТ и не является его официальным сервисом.',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Прочитал', callback_data='welcome:read')]]))
        return

    if state == 'await_group':
        await reply_ui(update, context, '🎓 <b>Регистрация не завершена</b>\n\nВведи свою группу, например: <code>ОИ-11.1</code>.', parse_mode=ParseMode.HTML)
        return
    if state == 'await_fio':
        await reply_ui(update, context, '👤 <b>Регистрация не завершена</b>\n\nТеперь введи ФИО полностью.', parse_mode=ParseMode.HTML)
        return

    # Защита старых/частично созданных записей: новый пользователь получает
    # приветствие один раз и после подтверждения продолжает регистрацию.
    set_registration(chat, 'await_welcome')
    await reply_ui(update, context,
        '👋 <b>Добро пожаловать!</b>\n\n'
        '🎓 Расписание • задания • ИИ-помощник • уведомления • староста\n\n'
        '⚠️ Частный проект, не связан с СГУГиТ и не является его официальным сервисом.',
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Прочитал', callback_data='welcome:read')]]))


async def _text_router_impl(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text: return
    chat=update.effective_chat.id; text=update.effective_message.text.strip(); u=update.effective_user
    register_user(chat,u.username if u else '',u.first_name if u else '')
    p=profile(chat)
    # anti-spam
    bucket=now().strftime('%Y%m%d%H%M')
    with connect() as c:
        row=c.execute('SELECT hits FROM spam_hits WHERE chat_id=? AND bucket=?',(chat,bucket)).fetchone()
        hits=(row[0] if row else 0)+1
        c.execute('INSERT INTO spam_hits(chat_id,bucket,hits) VALUES(?,?,?) ON CONFLICT(chat_id,bucket) DO UPDATE SET hits=excluded.hits',(chat,bucket,hits))
        if hits>15:
            await reply_ui(update, context, '🛡 Слишком много сообщений подряд. Подожди немного.')
            return
    if owner_only(chat) and context.user_data.get('owner_action')=='sponsor_text':
        new_text=text.strip()[:64]
        if not new_text:
            await reply_ui(update,context,'❌ Текст не может быть пустым.',reply_markup=owner_panel_keyboard()); return
        with connect() as c: c.execute("UPDATE bot_settings SET value=?,updated_at=? WHERE key='sponsor_button_text'",(new_text,now_iso()))
        context.user_data.pop('owner_action',None)
        await reply_ui(update,context,f'✅ <b>Текст изменён.</b>\n\nТеперь кнопка выглядит так:\n<b>{esc(new_text)}</b>',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return

    if owner_only(chat) and context.user_data.get('owner_action')=='sponsor_url':
        value=''.join(text.split())
        if value=='-': value=''
        elif not (value.startswith('https://') or value.startswith('http://') or value.startswith('tg://')):
            await reply_ui(update,context,'❌ Укажи корректный URL, начинающийся с https://, http:// или tg://.',reply_markup=owner_panel_keyboard()); return
        set_bot_setting('sponsor_url', value); context.user_data.pop('owner_action',None)
        await reply_ui(update,context,'✅ URL спонсора сохранён.' if value else '✅ Спонсор отключён.',reply_markup=owner_panel_keyboard()); return
    if owner_only(chat) and context.user_data.get('owner_action')=='sponsor_secret':
        value=text.strip()
        if len(value)<16:
            await reply_ui(update,context,'❌ Секрет должен содержать минимум 16 символов.',reply_markup=owner_panel_keyboard()); return
        set_bot_setting('sponsor_tracking_secret', value); context.user_data.pop('owner_action',None)
        await reply_ui(update,context,'✅ Секрет сохранён.',reply_markup=owner_panel_keyboard()); return
    if owner_only(chat) and context.user_data.get('owner_action')=='leader_ids':
        raw=text.strip()
        ids=[] if raw in ('','-','нет') else [int(x.strip()) for x in raw.split(',') if x.strip().isdigit()]
        with connect() as c:
            c.execute('DELETE FROM leaders')
            for leader_id in ids:
                row=c.execute('SELECT username,first_name FROM users WHERE chat_id=?',(leader_id,)).fetchone()
                c.execute('INSERT INTO leaders(chat_id,username,first_name,added_by,added_at) VALUES(?,?,?,?,?)',(leader_id,row[0] if row else '',row[1] if row else '',OWNER_ID,now_iso()))
        context.user_data.pop('owner_action',None)
        await reply_ui(update,context,f'✅ Старосты обновлены. Назначено: <b>{len(ids)}</b>.',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return

    # Owner control-center text flows. Every flow is explicit and cancellable.
    owner_action=context.user_data.get('owner_action')
    if owner_only(chat) and owner_action=='broadcast_text':
        text=text.strip()[:4000]
        context.user_data.pop('owner_action',None)
        audience=context.user_data.pop('owner_broadcast','all')
        if audience.startswith('group:'):
            group=audience.split(':',1)[1]
            with connect() as c:
                ids=[r[0] for r in c.execute("SELECT chat_id FROM users WHERE group_code=? AND muted=0",(group,)).fetchall()]
            sent,failed=await send_to_users(context.application,ids,'📣 <b>Сообщение владельца</b>\n\n'+esc(text),premium_menu)
        else:
            with connect() as c:
                ids=[r[0] for r in c.execute("SELECT chat_id FROM users WHERE muted=0").fetchall()]
            sent,failed=await send_to_users(context.application,ids,'📣 <b>Сообщение владельца</b>\n\n'+esc(text),premium_menu)
        await reply_ui(update,context,f'✅ Рассылка завершена.\n\n📨 Отправлено: <b>{sent}</b>\n⚠️ Ошибок: <b>{failed}</b>',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return

    if owner_only(chat) and owner_action=='user_find':
        try: target=int(text.strip())
        except ValueError:
            await reply_ui(update,context,'❌ Нужен числовой Chat ID.',reply_markup=owner_panel_keyboard()); return
        context.user_data.pop('owner_action',None)
        row=owner_user(target)
        if not row:
            await reply_ui(update,context,'❌ Пользователь не найден.',reply_markup=owner_panel_keyboard()); return
        await reply_ui(update,context,
            f'👤 <b>{esc(row[1] or row[2] or str(row[0]))}</b>\n\n'
            f'ID: <code>{row[0]}</code>\nГруппа: <b>{esc(row[3] or "—")}</b>\n'
            f'Статус рассылки: {"🔕 muted" if row[4] else "🔔 активен"}\n'
            f'Спонсор: {"🟢" if row[5] else "⚪"}',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🔕 Заглушить' if not row[4] else '🔔 Вернуть уведомления',callback_data=f'owner:user:mute:{target}')],
                [InlineKeyboardButton('🎓 Сменить группу',callback_data=f'owner:user:group:{target}'),InlineKeyboardButton('🗑 Убрать из группы',callback_data=f'owner:user:ungroup:{target}')],
                [InlineKeyboardButton('👑 Назначить старостой',callback_data=f'owner:user:leader:{target}')],
                [InlineKeyboardButton('‹ Панель владельца',callback_data='owner:back')],
            ])); return

    if owner_only(chat) and owner_action=='user_group':
        try: target=int(context.user_data.get('owner_target'))
        except Exception:
            context.user_data.pop('owner_action',None); return
        try:
            g=owner_set_group(target,text.strip())
            context.user_data.pop('owner_action',None); context.user_data.pop('owner_target',None)
            await reply_ui(update,context,f'✅ Пользователь <code>{target}</code> переведён в группу <b>{esc(g[0])}</b>.',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard())
        except Exception:
            await reply_ui(update,context,'❌ Группа не найдена. Напиши точное название, например <code>ОИ-11.1</code>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]]))
        return

    if owner_only(chat) and owner_action in ('schedule_add','schedule_replace','schedule_delete'):
        try:
            raw=text.strip()
            dm, rest = raw.split(None,1)
            d=datetime.strptime(dm,'%d.%m.%Y').date()
            times, payload = rest.split('|',1)
            start,end=[x.strip() for x in times.split('-',1)]
            datetime.strptime(start,'%H:%M'); datetime.strptime(end,'%H:%M')
            group=context.user_data.get('owner_schedule_group','')
            if not group: raise ValueError
            if owner_action=='schedule_delete':
                record_manual_change(d,start,end,'delete',reason='Правка владельца',author_id=chat,author_name='Владелец',group_code=group)
            else:
                parts=[x.strip() for x in payload.split('|')]
                if not parts or not parts[0]: raise ValueError
                subject=parts[0]; teacher=parts[1] if len(parts)>1 else ''; room=parts[2] if len(parts)>2 else ''
                record_manual_change(d,start,end,'replace' if owner_action=='schedule_replace' else 'add',subject,teacher,room,'owner','Правка владельца',chat,'Владелец',group)
            context.user_data.pop('owner_action',None); context.user_data.pop('owner_schedule_group',None)
            await reply_ui(update,context,'✅ Правка сохранена и будет применена к расписанию группы.',reply_markup=owner_panel_keyboard()); return
        except Exception:
            await reply_ui(update,context,'❌ Формат не распознан.\nДобавление/замена: <code>08.10.2026 09:00-10:35 | Математика | Иванов | 301</code>\nУдаление: <code>08.10.2026 09:00-10:35 | причина</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]])); return
    state=p[5] if p else ''
    if state=='await_welcome':
        await reply_ui(update, context,
            '👋 Сначала нажми кнопку <b>«Прочитал»</b> в приветственном сообщении.',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Прочитал', callback_data='welcome:read')]]))
        return
    if state=='await_group':
        status,exact,similar=resolve_group(text)
        if status == 'none' and not group_catalog():
            await reply_ui(update, context, '🔎 Загружаю актуальный список групп…')
            await asyncio.to_thread(refresh_group_catalog, True)
            status,exact,similar=resolve_group(text)
        if status in ('exact','fuzzy') and exact:
            g=exact[0]
            save_profile(chat,'',g); set_registration(chat,'await_fio')
            await reply_ui(update, context, f'✅ Нашёл: <b>{esc(g[0])}</b>\n\nТеперь напиши <b>ФИО полностью</b>.',parse_mode=ParseMode.HTML)
            return
        if similar:
            rows=[]
            for g in similar[:6]: rows.append([InlineKeyboardButton(g[0],callback_data='group:'+g[0])])
            rows.append([InlineKeyboardButton('↻ Обновить список групп',callback_data='groups:refresh')])
            await reply_ui(update, context, '🔎 Точного совпадения не нашёл. Возможно, ты имел в виду:',reply_markup=InlineKeyboardMarkup(rows)); return
        await reply_ui(update, context, 'Не нашёл такую группу. Проверь написание, например <code>ОИ-11.1</code>.',parse_mode=ParseMode.HTML); return
    if state=='await_fio':
        if not safe_fio(text):
            await reply_ui(update, context, '⚠️ Похоже, это не обычное ФИО. Напиши фамилию, имя и отчество/второе имя без лишних символов.')
            return
        g=(p[2],p[2],p[3]); save_profile(chat,text,g); set_registration(chat,'')
        await reply_ui(update, context,
            '🎉 <b>Профиль заполнен!</b>\n\n'
            f'👤 ФИО: <b>{esc(text)}</b>\n'
            f'🎓 Группа: <b>{esc(g[0])}</b>\n\n'
            'Теперь бот готов к работе. Выбирай нужный раздел ниже.',
            parse_mode=ParseMode.HTML,
            reply_markup=premium_menu(chat)); return
    if (is_leader(chat) or owner_only(chat)) and context.user_data.get('leader_schedule_action'):
        action=context.user_data.pop('leader_schedule_action')
        try:
            raw=text.strip(); dm, rest=raw.split(None,1); d=datetime.strptime(dm,'%d.%m.%Y').date()
            times,payload=rest.split('|',1); start,end=[x.strip() for x in times.split('-',1)]
            datetime.strptime(start,'%H:%M'); datetime.strptime(end,'%H:%M')
            g=leader_group(chat,context)
            if action=='delete':
                record_manual_change(d,start,end,'delete',reason='Правка старосты',author_id=chat,author_name=profile(chat)[1] or 'Староста',group_code=g)
            else:
                parts=[x.strip() for x in payload.split('|')]; subject=parts[0]
                if not subject: raise ValueError
                record_manual_change(d,start,end,'replace' if action=='replace' else 'add',subject,parts[1] if len(parts)>1 else '',parts[2] if len(parts)>2 else '','leader','Правка старосты',chat,profile(chat)[1] or 'Староста',g)
            await reply_ui(update,context,f'✅ Правка сохранена для группы <b>{esc(g)}</b>.',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return
        except Exception:
            await reply_ui(update,context,'❌ Неверный формат.\nДобавить/заменить: <code>08.10.2026 09:00-10:35 | Предмет | Преподаватель | Аудитория</code>\nУдалить: <code>08.10.2026 09:00-10:35 | причина</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:leader')]])); return

    action=context.user_data.get('flow_action')
    if action=='task_subject':
        # Smart subject matching against the user's next 14 days.
        try:
            data=await group_data(chat)
            subjects=[]
            for off in range(14):
                for l in data.get(now().date()+timedelta(days=off),[]):
                    if l.subject and l.subject not in subjects: subjects.append(l.subject)
            from difflib import SequenceMatcher
            scored=sorted(((SequenceMatcher(None,text.lower(),x.lower()).ratio(),x) for x in subjects),reverse=True)
            if scored and scored[0][0]>=0.48:
                subject=scored[0][1]
                context.user_data['task_subject']=subject; context.user_data['flow_action']='task_text'
                await reply_ui(update, context, f'📚 Предмет: <b>{esc(subject)}</b>\n\nТеперь напиши само задание.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:tasks')]])); return
        except Exception: pass
        context.user_data['task_subject']=text; context.user_data['flow_action']='task_text'
        await reply_ui(update, context, f'📚 Сохраню предмет как <b>{esc(text)}</b>.\n\nТеперь напиши само задание.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:tasks')]])); return
    if action=='task_text':
        context.user_data.pop('flow_action',None); subject=context.user_data.pop('task_subject','')
        context.user_data['pending_task']={'subject':subject,'text':text}
        await reply_ui(update, context, f'📝 <b>{esc(subject)}</b>\n\nПоказывать это задание однокурсникам?',parse_mode=ParseMode.HTML,reply_markup=task_visibility_keyboard()); return
    if action=='poll_text':
        context.user_data.pop('flow_action',None); context.user_data['poll_question']=text; context.user_data['flow_action']='poll_options'
        await reply_ui(update, context, '📊 Теперь напиши варианты через `;`\nНапример: <code>Буду;Не буду;Пока не знаю</code>',parse_mode=ParseMode.HTML); return
    if action=='poll_options':
        opts=[x.strip() for x in text.split(';') if x.strip()]
        if len(opts)<2 or len(opts)>8: await reply_ui(update, context, 'Нужно от 2 до 8 вариантов через `;`.'); return
        context.user_data['poll_options']=opts; context.user_data['flow_action']='poll_title'; await reply_ui(update, context, '🏷 Напиши короткое название опроса.'); return
    if action=='poll_title':
        context.user_data.pop('flow_action',None); opts=context.user_data.pop('poll_options'); q=context.user_data.pop('poll_question')
        context.user_data['poll_pending']={'title':text,'question':q,'options':opts}
        await reply_ui(update, context, '📸 Нужен скриншот после ответа?',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📸 Да',callback_data='poll:publish:1'),InlineKeyboardButton('Без скриншота',callback_data='poll:publish:0')],[InlineKeyboardButton('‹ Отмена',callback_data='p:leader')]])); return
    if action=='announce':
        context.user_data.pop('flow_action',None)
        result,reason,req_id=await submit_publication(context.application,chat,leader_group(chat,context),'announcement',{'text':text})
        if result=='accept': msg='✅ Объявление прошло проверку и опубликовано.'
        elif result=='reject': msg='❌ Объявление не прошло проверку. Попробуй сформулировать его иначе.'
        else: msg='🛡 Объявление отправлено на проверку. После решения владельца оно появится у группы.'
        await reply_ui(update, context, msg,reply_markup=leader_premium_menu()); return
    if AI_ASSISTANT_ENABLED and context.user_data.get('ai_mode') and reg_complete(chat):
        try:
            answer = await answer_student_question(chat, text)
            await reply_ui(update, context, answer, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🤖 Ещё вопрос',callback_data='p:ai')],[InlineKeyboardButton('‹ В меню',callback_data='p:menu')]]))
        except ScheduleError:
            await reply_ui(update, context, '⚠️ Не удалось загрузить расписание группы. Нажми «📅 Расписание» → «🔄 Обновить» и попробуй ещё раз.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        except Exception:
            log.exception('student assistant failed')
            await reply_ui(update, context, '⚠️ Помощник не смог обработать вопрос. Попробуй спросить проще: «что завтра?», «сколько пар завтра?» или «где следующая пара?».', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        return

    # Natural-language student assistant.
    if AI_ASSISTANT_ENABLED and reg_complete(chat):
        try:
            answer = await answer_student_question(chat, text)
            await reply_ui(update, context, answer, parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        except ScheduleError:
            await reply_ui(update, context, '⚠️ Не удалось загрузить расписание группы. Нажми «📅 Расписание» → «🔄 Обновить» и попробуй ещё раз.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        except Exception:
            log.exception('student assistant failed')
            await reply_ui(update, context, '⚠️ Помощник временно не смог обработать вопрос. Попробуй сформулировать его иначе. Например: «следующая пара» или «что завтра?». ', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        return
    await reply_ui(update, context, 'ℹ️ Сначала заполни профиль, затем я смогу отвечать по твоему расписанию.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))


async def render_task_list(q, chat_id: int):
    p=profile(chat_id)
    with connect() as c:
        own=c.execute('SELECT id,subject,text,done,shared,author_name FROM tasks WHERE chat_id=? ORDER BY done ASC,id DESC', (chat_id,)).fetchall()
        peer=c.execute('SELECT id,subject,text,done,author_name FROM tasks WHERE group_code=? AND shared=1 AND chat_id!=? ORDER BY id DESC LIMIT 20', (p[2],chat_id)).fetchall() if p and p[2] and user_setting(chat_id,'peer_tasks_enabled') else []
    blocks=[]
    if own:
        blocks.append('<b>Мои</b>\n'+'\n\n'.join((('✅' if r[3] else '⏳')+f' <b>{esc(r[1])}</b>\n{esc(r[2])}\n'+('👥 Видно группе' if r[4] else '🔒 Только тебе')) for r in own))
    if peer:
        blocks.append('<b>Однокурсники</b>\n'+'\n\n'.join(f'👤 {esc(r[4] or "Студент")} · <b>{esc(r[1])}</b>\n{esc(r[2])}' for r in peer))
    text='📝 <b>Задания</b>\n\n'+('\n\n'.join(blocks) if blocks else 'Заданий пока нет.')
    await q.message.edit_text(text,parse_mode=ParseMode.HTML,reply_markup=task_list_keyboard(chat_id))


async def text_router(update:Update,context:ContextTypes.DEFAULT_TYPE):
    """Process a user text and remove the user's message afterwards.

    The bot is intentionally chat-clean: once the text has been processed (or
    rejected), the original user message is deleted. This keeps registration,
    owner input, leader edits and AI questions from accumulating in the chat.
    Telegram may reject deletion for very old messages or missing permissions;
    that must never break the actual bot flow.
    """
    try:
        await _text_router_impl(update, context)
    finally:
        try:
            msg = getattr(update, 'effective_message', None)
            if msg and getattr(msg, 'message_id', None):
                await msg.delete()
        except Exception:
            pass


async def callbacks(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data; chat=q.message.chat.id
    if data != 'sponsor:open':
        await q.answer()
    if q.message:
        context.user_data["last_ui_message_id"] = q.message.message_id
    if data.startswith('owner:'):
        if chat != OWNER_ID: return
        if data=='owner:overview':
            await q.message.edit_text(owner_overview_text(),parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:activity':
            await q.message.edit_text(owner_activity_text(),parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:users':
            rows=owner_user_rows(40)
            txt='👥 <b>Последние пользователи</b>\n\n'+('\n'.join(f'• {esc(r[1] or "Без ФИО")} · {esc(r[3] or "—")} · <code>{r[0]}</code>' for r in rows) if rows else 'Пользователей нет.')
            await q.message.edit_text(txt,parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:groups':
            with connect() as c: rows=c.execute("SELECT group_code,COUNT(*) FROM users WHERE group_code!='' GROUP BY group_code ORDER BY COUNT(*) DESC,group_code LIMIT 50").fetchall()
            txt='🎓 <b>Группы</b>\n\n'+('\n'.join(f'• {esc(g)} — <b>{n}</b> чел.' for g,n in rows) if rows else 'Групп нет.')
            await q.message.edit_text(txt,parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:leaders':
            rows=leader_rows(); txt='👑 <b>Старосты</b>\n\n'+('\n'.join(f'• {esc(r[2] or r[1] or str(r[0]))} · <code>{r[0]}</code>' for r in rows) if rows else 'Старост нет.')
            await q.message.edit_text(txt,parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:moderation':
            with connect() as c: rows=c.execute("SELECT id,kind,group_code,decision,created_at FROM publication_requests WHERE status='pending' ORDER BY id DESC LIMIT 20").fetchall()
            txt='🛡 <b>Модерация</b>\n\n'+('\n'.join(f'#{r[0]} · {"📢" if r[1]=="announcement" else "📊"} · {esc(r[2])} · {esc(r[3] or "review")}' for r in rows) if rows else 'Очередь пуста.')
            await q.message.edit_text(txt,parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return

        if data=='owner:broadcast':
            await q.message.edit_text('📣 <b>Рассылка владельца</b>\n\nВыбери аудиторию.',parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('👥 Всем активным',callback_data='owner:broadcast:all')],
                    [InlineKeyboardButton('🎓 В конкретную группу',callback_data='owner:broadcast:group')],
                    [InlineKeyboardButton('‹ Назад',callback_data='owner:back')],
                ])); return
        if data=='owner:broadcast:all':
            context.user_data['owner_action']='broadcast_text'; context.user_data['owner_broadcast']='all'
            await q.message.edit_text('📣 Отправь текст сообщения для всех активных пользователей.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]])); return
        if data=='owner:broadcast:group':
            await q.message.edit_text('🎓 Выбери группу для рассылки:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(g,callback_data=f'owner:broadcast:pick:{g}')] for g in owner_group_codes()] + [[InlineKeyboardButton('‹ Назад',callback_data='owner:broadcast')]])); return
        if data.startswith('owner:broadcast:pick:'):
            g=data.split(':',3)[3]
            context.user_data['owner_action']='broadcast_text'; context.user_data['owner_broadcast']='group:'+g
            await q.message.edit_text(f'📣 Отправь сообщение для группы <b>{esc(g)}</b>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:broadcast')]])); return
        if data=='owner:user:find':
            context.user_data['owner_action']='user_find'
            await q.message.edit_text('👤 Введи Chat ID пользователя.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]])); return
        if data.startswith('owner:user:mute:'):
            target=int(data.rsplit(':',1)[1]); row=owner_user(target)
            if not row: await q.answer('Пользователь не найден.',show_alert=True); return
            owner_set_muted(target,not bool(row[4]))
            row=owner_user(target)
            await q.message.edit_text(f'👤 <b>Пользователь {target}</b>\n\nСтатус: {"🔕 заглушен" if row[4] else "🔔 активен"}',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data.startswith('owner:user:group:'):
            target=int(data.rsplit(':',1)[1]); context.user_data['owner_action']='user_group'; context.user_data['owner_target']=target
            await q.message.edit_text(f'🎓 Введи новую группу для пользователя <code>{target}</code>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]])); return
        if data.startswith('owner:user:ungroup:'):
            target=int(data.rsplit(':',1)[1]); owner_remove_group(target)
            await q.message.edit_text(f'✅ Пользователь <code>{target}</code> убран из группы.',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data.startswith('owner:user:leader:'):
            target=int(data.rsplit(':',1)[1]); row=owner_user(target)
            if not row or not row[3]: await q.answer('Сначала назначь пользователю группу.',show_alert=True); return
            u=await context.application.bot.get_chat(target)
            add_leader(target,getattr(u,'username','') or '',getattr(u,'first_name','') or row[1] or '',OWNER_ID)
            try:
                await context.application.bot.send_message(
                    target,
                    f'👑 <b>Ты назначен старостой!</b>\n\n'
                    f'🎓 Группа: <b>{esc(row[3])}</b>\n'
                    'Владелец назначил тебя старостой. Тебе доступен кабинет старосты.',
                    parse_mode=ParseMode.HTML,
                    reply_markup=leader_premium_menu(),
                )
            except Exception:
                pass
            await q.message.edit_text(f'👑 Пользователь <code>{target}</code> назначен старостой группы <b>{esc(row[3])}</b>.\n\n📨 Пользователь уведомлён о назначении.',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:leader:manage':
            rows=leader_rows()
            kb=[[InlineKeyboardButton(f'🗑 Снять · {((r[2] or r[1] or str(r[0]))[:28])}',callback_data=f'owner:leader:revoke:{r[0]}')] for r in rows]
            kb.append([InlineKeyboardButton('‹ Назад',callback_data='owner:back')])
            await q.message.edit_text('👑 <b>Управление старостами</b>\n\n'+('\n'.join(f'• {esc(r[2] or r[1] or str(r[0]))} · {r[0]}' for r in rows) if rows else 'Старост нет.'),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
        if data.startswith('owner:leader:revoke:'):
            target=int(data.rsplit(':',1)[1]); owner_revoke_leader(target)
            try:
                await context.application.bot.send_message(target,'ℹ️ <b>Полномочия старосты сняты.</b>\n\nВладелец снял с тебя статус старосты.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(target))
            except Exception:
                pass
            await q.message.edit_text('✅ Полномочия старосты сняты.\n\n📨 Пользователь уведомлён.',reply_markup=owner_panel_keyboard()); return
        if data=='owner:group:manage':
            groups=owner_group_codes()
            await q.message.edit_text('🎓 <b>Управление группой</b>\n\nВыбери группу:',parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(g,callback_data=f'owner:group:pick:{g}')] for g in groups]+[[InlineKeyboardButton('‹ Назад',callback_data='owner:back')]])); return
        if data.startswith('owner:group:pick:'):
            g=data.split(':',3)[3]; rows=owner_group_users(g)
            await q.message.edit_text(f'🎓 <b>{esc(g)}</b>\n\n👥 Пользователей: <b>{len(rows)}</b>\n\nМожно открыть кабинет группы и управлять её расписанием.',parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('👑 Открыть кабинет',callback_data=f'owner:panel:{g}')],[InlineKeyboardButton('📣 Рассылка группе',callback_data=f'owner:broadcast:pick:{g}')],[InlineKeyboardButton('‹ Назад',callback_data='owner:group:manage')]])); return
        if data=='owner:schedule':
            groups=owner_group_codes()
            await q.message.edit_text('📅 <b>Правки расписания</b>\n\nСначала выбери группу.',parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(g,callback_data=f'owner:schedule:pick:{g}')] for g in groups]+[[InlineKeyboardButton('‹ Назад',callback_data='owner:back')]])); return
        if data.startswith('owner:schedule:pick:'):
            g=data.split(':',3)[3]; context.user_data['owner_schedule_group']=g
            await q.message.edit_text(f'📅 <b>Правки: {esc(g)}</b>\n\nВыбери действие.',parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('➕ Добавить',callback_data='owner:schedule:add'),InlineKeyboardButton('✏️ Заменить',callback_data='owner:schedule:replace')],[InlineKeyboardButton('🗑 Удалить',callback_data='owner:schedule:delete')],[InlineKeyboardButton('‹ Назад',callback_data='owner:back')]])); return
        if data.startswith('owner:schedule:') and data.rsplit(':',1)[1] in ('add','replace','delete'):
            action=data.rsplit(':',1)[1]; context.user_data['owner_action']='schedule_'+action
            await q.message.edit_text('📅 Отправь одну правку сообщением.\nДобавить/заменить: <code>08.10.2026 09:00-10:35 | Предмет | Преподаватель | Аудитория</code>\nУдалить: <code>08.10.2026 09:00-10:35 | причина</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:back')]])); return
        if data=='owner:settings':
            leaders=', '.join(str(r[0]) for r in leader_rows()) or 'нет назначенных'
            await q.message.edit_text(f'⚙️ <b>Настройки владельца</b>\n\n⭐ Спонсор: <b>{"включён" if sponsor_url() else "выключен"}</b>\n👑 Старосты: <code>{esc(leaders)}</code>\n\nВсе эти параметры хранятся в базе данных и больше не требуют .env.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⭐ Спонсор',callback_data='owner:sponsor')],[InlineKeyboardButton('👑 Настроить старост',callback_data='owner:settings:leaders')],[InlineKeyboardButton('‹ Назад',callback_data='owner:back')]])); return
        if data=='owner:settings:leaders':
            context.user_data['owner_action']='leader_ids'; await q.message.edit_text('👑 <b>ID старост</b>\n\nОтправь Telegram ID через запятую. Пустой список снимет полномочия со всех старост.\n\nПример: <code>123456789,987654321</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:settings')]])); return
        if data=='owner:sponsor':
            url=sponsor_url() or 'не настроен'
            await q.message.edit_text(f'⭐ <b>Спонсор</b>\n\n🔗 URL: <code>{esc(url)}</code>\n🔐 Секрет: <b>{"настроен" if bot_setting('sponsor_tracking_secret') else "автоматически от BOT_TOKEN"}</b>\n📝 Текст кнопки: <b>{esc(sponsor_button_text())}</b>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔗 Изменить URL',callback_data='owner:sponsor:url')],[InlineKeyboardButton('🔐 Изменить секрет',callback_data='owner:sponsor:secret')],[InlineKeyboardButton('✏️ Изменить текст',callback_data='owner:sponsor:edit')],[InlineKeyboardButton('‹ Назад',callback_data='owner:settings')]])); return
        if data=='owner:sponsor:url':
            context.user_data['owner_action']='sponsor_url'; await q.message.edit_text('🔗 <b>URL спонсора</b>\n\nОтправь ссылку целиком. Чтобы отключить спонсора, отправь <code>-</code>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:sponsor')]])); return
        if data=='owner:sponsor:secret':
            context.user_data['owner_action']='sponsor_secret'; await q.message.edit_text('🔐 <b>Секрет отслеживания</b>\n\nОтправь новую случайную строку. Она используется для подписи переходов.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:sponsor')]])); return
        if data=='owner:sponsor:edit':
            context.user_data['owner_action']='sponsor_text'
            await q.message.edit_text('✏️ <b>Новый текст кнопки «Спонсор»</b>\n\nОтправь одним сообщением новый текст. Он сразу будет использоваться во всех пользовательских меню.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='owner:sponsor')]])); return
        if data=='owner:report':
            path=await build_owner_excel()
            with open(path,'rb') as f: await context.application.bot.send_document(chat, f, filename=path.name, caption='📊 Отчёт сформирован.', disable_notification=True)
            await q.message.edit_text('✅ <b>Excel-отчёт отправлен.</b>',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:system':
            await q.message.edit_text('⚙️ <b>Система</b>\n\n• Меню пользователей — фиксированное\n• /panel ГРУППА — вход в кабинет группы\n• Еженедельный Excel — понедельник 09:00, без звука\n• Доступ к владельческой панели — только OWNER_ID\n• Скрытая проверка доверия старост работает автоматически',parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data=='owner:help':
            await q.message.edit_text(owner_commands_help(),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='owner:back')]])); return
        if data=='owner:back':
            await q.message.edit_text(owner_overview_text(),parse_mode=ParseMode.HTML,reply_markup=owner_panel_keyboard()); return
        if data.startswith('owner:panel:'):
            g=data.split(':',2)[2]; context.user_data['owner_panel_group']=g
            await q.message.edit_text(f'👑 <b>Кабинет старосты</b>\n\n🎓 Группа: <b>{esc(g)}</b>',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return
        return
    if data=='welcome:read':
        p=profile(chat)
        if not reg_complete(chat):
            # Только после подтверждения приветствия начинаем обязательную регистрацию.
            if not (p and p[2]):
                set_registration(chat,'await_group')
                await q.message.edit_text(
                    '🎓 <b>Шаг 1 из 2 — группа</b>\n\n'
                    'Введи свою группу. Например: <code>ОИ-11.1</code>.\n'
                    'Пустое значение не принимается.',
                    parse_mode=ParseMode.HTML)
            else:
                set_registration(chat,'await_fio')
                await q.message.edit_text(
                    '👤 <b>Шаг 2 из 2 — ФИО</b>\n\n'
                    'Теперь обязательно введи ФИО полностью. Пустое значение не принимается.',
                    parse_mode=ParseMode.HTML)
            return
        set_registration(chat,'')
        await q.message.edit_text('🏠 <b>Главное меню</b>\n\nВыбирай нужный раздел.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        return

    if data=='sponsor:open':
        # Legacy callback kept for old messages. New sponsor buttons use the
        # tracked HTTP redirect because Telegram URL buttons cannot emit a
        # callback query at the same time.
        set_sponsor(chat)
        await q.answer('Доступ открыт.')
        await q.message.edit_text('🏠 <b>Главное меню</b>\n\nВыбирай нужный раздел.', parse_mode=ParseMode.HTML, reply_markup=premium_menu(chat))
        return
    if data=='groups:refresh':
        try: refresh_group_catalog(True); await q.message.edit_text('🔄 Список групп обновлён. Теперь напиши группу ещё раз.')
        except Exception: await q.message.edit_text('⚠️ Не удалось обновить список групп. Попробуй ещё раз через минуту.')
        return
    if data.startswith('group:'):
        code=data[6:]; status,rows,_=resolve_group(code)
        if rows:
            save_profile(chat,'',rows[0]); set_registration(chat,'await_fio'); await q.message.edit_text(f'✅ Группа <b>{esc(rows[0][0])}</b> выбрана.\n\nТеперь напиши ФИО полностью.',parse_mode=ParseMode.HTML)
        return
    if data=='leaderapp:new':
        if is_leader(chat): return
        if leader_application_blocked(chat):
            await q.answer('Заявка уже была отклонена. Повторная подача недоступна.', show_alert=True)
            await q.message.edit_text('🚫 <b>Повторная заявка на старосту недоступна.</b>\n\nТвоя предыдущая заявка была отклонена владельцем. Повторно отправить её нельзя.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat))
            return
        p=profile(chat)
        with connect() as c: active=c.execute("SELECT id FROM leader_applications_v12 WHERE chat_id=? AND status='pending'",(chat,)).fetchone()
        if active: await q.message.edit_text('🕓 <b>Заявка уже рассматривается.</b>',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); return
        created=now(); deadline=created; days=0
        while days<5:
            deadline+=timedelta(days=1)
            if deadline.weekday()<5: days+=1
        with connect() as c: cur=c.execute('INSERT INTO leader_applications_v12(chat_id,group_code,full_name,created_at,deadline_at) VALUES(?,?,?,?,?)',(chat,p[2],p[1],created.isoformat(),deadline.isoformat())); aid=cur.lastrowid
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Принять',callback_data=f'leaderapp:approve:{aid}'),InlineKeyboardButton('❌ Отклонить',callback_data=f'leaderapp:reject:{aid}')]])
        try: await context.application.bot.send_message(OWNER_ID,f'⭐ <b>Заявка старосты #{aid}</b>\n\n👤 {esc(p[1])}\n🎓 {esc(p[2])}\n⏳ До: {deadline.strftime("%d.%m.%Y")}',parse_mode=ParseMode.HTML,reply_markup=kb,disable_notification=True)
        except Exception: pass
        await q.message.edit_text(f'⭐ <b>Заявка отправлена.</b>\n\nРешение ожидается до {deadline.strftime("%d.%m.%Y")}.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); return
    if data.startswith('leaderapp:') and chat==OWNER_ID:
        _,action,aid_s=data.split(':'); aid=int(aid_s)
        with connect() as c: row=c.execute('SELECT chat_id,group_code,full_name,status FROM leader_applications_v12 WHERE id=?',(aid,)).fetchone()
        if not row or row[3]!='pending': return
        if action=='approve':
            add_leader(row[0], '', row[2], OWNER_ID)
            with connect() as c: c.execute("UPDATE leader_applications_v12 SET status='approved',processed_at=?,processed_by=? WHERE id=?",(now_iso(),OWNER_ID,aid))
            try: await context.application.bot.send_message(row[0],f'⭐ <b>Ты назначен старостой группы {esc(row[1])}.</b>\n\nТеперь тебе доступен кабинет старосты.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(row[0]))
            except Exception: pass
            await q.message.edit_text(f'✅ Заявка #{aid} принята. Староста назначен.',parse_mode=ParseMode.HTML); return
        if action=='reject':
            with connect() as c: c.execute("UPDATE leader_applications_v12 SET status='rejected',processed_at=?,processed_by=? WHERE id=?",(now_iso(),OWNER_ID,aid))
            try: await context.application.bot.send_message(row[0],'❌ Заявка на старосту отклонена.')
            except Exception: pass
            await q.message.edit_text(f'❌ Заявка #{aid} отклонена.',parse_mode=ParseMode.HTML); return
    if data.startswith('mod:') and chat==OWNER_ID:
        _,action,req_s=data.split(':'); req_id=int(req_s)
        with connect() as c:
            row=c.execute('SELECT leader_id,group_code,kind,status,payload_json FROM publication_requests WHERE id=?',(req_id,)).fetchone()
        if not row or row[3] not in ('pending','approved'): return
        leader_id,group_code,kind,status,payload_json=row
        if action=='approve':
            with connect() as c: c.execute("UPDATE publication_requests SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=?",(now_iso(),OWNER_ID,req_id))
            await publish_request(context.application,req_id,owner=True)
            try: await context.application.bot.send_message(leader_id,'✅ Публикация одобрена и размещена у группы.',reply_markup=leader_premium_menu())
            except Exception: pass
            await q.message.edit_text(f'✅ <b>Модерация #{req_id}</b> — опубликовано.',parse_mode=ParseMode.HTML)
            return
        if action=='reject':
            with connect() as c: c.execute("UPDATE publication_requests SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=?",(now_iso(),OWNER_ID,req_id))
            update_trust(leader_id,group_code,False)
            try: await context.application.bot.send_message(leader_id,'❌ Публикация отклонена после проверки владельцем.',reply_markup=leader_premium_menu())
            except Exception: pass
            await q.message.edit_text(f'❌ <b>Модерация #{req_id}</b> — отклонено.',parse_mode=ParseMode.HTML)
            return
    if data=='sponsor:buy':
        if not reg_complete(chat):
            await q.message.edit_text('Сначала заверши профиль, затем оплата будет доступна в нём.',reply_markup=premium_menu(chat)); return
        if not sponsor_button_allowed(chat):
            await q.message.edit_text('⭐ Спонсор больше не показывается в твоём интерфейсе.',reply_markup=premium_menu(chat)); return
        await q.message.edit_text('⭐ <b>Отключение спонсора</b>\n\n25 ⭐ — и упоминание спонсора исчезнет для тебя. Если ты староста, одновременно оно отключится и для твоей группы.\n\nОплата проходит внутри Telegram Stars.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💫 Оплатить 25 ⭐',callback_data='sponsor:invoice')],[InlineKeyboardButton('‹ Назад',callback_data='p:profile')]])); return
    if data=='sponsor:invoice':
        try:
            msg=await context.application.bot.send_invoice(chat_id=chat,title='Отключение спонсора',description='25 ⭐ — убрать упоминания спонсора из интерфейса. Для старосты также отключается для его группы.',payload=f'sponsor_exempt:{chat}',provider_token='',currency='XTR',prices=[LabeledPrice('Отключение спонсора',SPONSOR_EXEMPT_STARS)])
            context.user_data['stars_invoice_message_id']=msg.message_id
            await q.message.edit_text('💫 <b>Счёт отправлен.</b>\n\nОплати 25 ⭐ в сообщении Telegram выше. После успешной оплаты настройки применятся автоматически.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='p:profile')]]))
        except Exception:
            await q.message.edit_text('⚠️ Не удалось создать счёт. Попробуй ещё раз позже.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='p:profile')]]))
        return
    if data=='p:menu':
        context.user_data.pop('ai_mode',None)
        await q.message.edit_text('🏠 <b>Главное меню</b>',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); return
    if data=='p:invite':
        try:
            me=await context.application.bot.get_me()
            link=referral_link(me.username, chat)
            share_url=referral_share_url(me.username, chat)
            count=referral_count(chat)
            await q.message.edit_text(
                '👥 <b>Пригласить друзей</b>\n\n'
                'Твоя персональная ссылка — по ней бот поймёт, что пользователь пришёл именно от тебя.\n\n'
                f'👤 Приглашено: <b>{count}</b>\n\n'
                f'<code>{esc(link)}</code>',
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('📨 Поделиться', url=share_url)],
                    [InlineKeyboardButton('‹ Назад',callback_data='p:menu')],
                ]),
            )
        except Exception:
            await q.message.edit_text('👥 <b>Пригласить друзей</b>\n\nНе удалось создать персональную ссылку. Попробуй ещё раз.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='p:menu')]]))
        return
    if data=='p:schedule': await q.message.edit_text('📅 <b>Расписание</b>',parse_mode=ParseMode.HTML,reply_markup=schedule_menu()); return
    if data=='p:tasks':
        for key in ('flow_action','task_subject','pending_task'):
            context.user_data.pop(key,None)
        await q.message.edit_text('📝 <b>Задания</b>\n\nДобавляй задания обычным текстом — предмет можно написать сокращённо.',parse_mode=ParseMode.HTML,reply_markup=task_menu()); return
    if data=='task:cancel':
        for key in ('flow_action','task_subject','pending_task'):
            context.user_data.pop(key,None)
        await q.message.edit_text('📝 <b>Задания</b>',parse_mode=ParseMode.HTML,reply_markup=task_menu()); return
    if data.startswith('task:done:'):
        parts=data.split(':'); task_id=int(parts[2]); done=int(parts[3])
        with connect() as c:
            row=c.execute('SELECT chat_id FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row or row[0]!=chat:
                await q.answer('Это задание тебе не принадлежит.', show_alert=True); return
            c.execute('UPDATE tasks SET done=?, completed_at=? WHERE id=?',(done, now_iso() if done else '', task_id))
        await q.answer('Готово.' if done else 'Возвращено в активные.')
        await render_task_list(q, chat)
        return
    if data.startswith('task:delete:'):
        task_id=int(data.split(':')[-1])
        with connect() as c:
            row=c.execute('SELECT chat_id FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row or row[0]!=chat:
                await q.answer('Это задание тебе не принадлежит.', show_alert=True); return
            c.execute('DELETE FROM tasks WHERE id=?',(task_id,))
        await q.answer('Задание удалено.')
        await render_task_list(q, chat)
        return
    if data.startswith('task:share:'):
        pending=context.user_data.pop('pending_task',None)
        context.user_data.pop('flow_action',None)
        context.user_data.pop('task_subject',None)
        if not pending or not pending.get('subject') or not pending.get('text'):
            await q.answer('Сессия добавления задания устарела. Начни заново.', show_alert=True); return
        shared=int(data.rsplit(':',1)[1]); p=profile(chat); author=p[1] or 'Студент'
        if shared and not user_setting(chat,'share_tasks_enabled'):
            shared=0
        with connect() as c:
            c.execute('INSERT INTO tasks(chat_id,subject,text,group_code,author_name,shared,created_at) VALUES(?,?,?,?,?,?,?)',(chat,pending['subject'][:200],pending['text'][:2000],p[2],author[:200],shared,now_iso()))
        await q.message.edit_text(f'✅ <b>Задание добавлено</b>\n\n📚 {esc(pending["subject"])}\n📝 {esc(pending["text"])}\n'+('👥 Видно группе' if shared else '🔒 Только тебе'),parse_mode=ParseMode.HTML,reply_markup=task_menu()); return
    if data=='task:toggle_peers':
        set_user_setting(chat,'peer_tasks_enabled',not user_setting(chat,'peer_tasks_enabled')); await q.message.edit_text('👥 <b>Задания однокурсников</b>\n\n'+('🟢 Ты видишь задания однокурсников.' if user_setting(chat,'peer_tasks_enabled') else '⚪ Задания однокурсников скрыты.'),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='profile:tasks')]])); return
    if data=='task:toggle_share':
        set_user_setting(chat,'share_tasks_enabled',not user_setting(chat,'share_tasks_enabled')); await q.message.edit_text('📢 <b>Мои задания</b>\n\n'+('🟢 Новые задания можно показывать группе.' if user_setting(chat,'share_tasks_enabled') else '⚪ Новые задания по умолчанию только для тебя.'),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='profile:tasks')]])); return
    if data=='profile:tasks':
        await q.message.edit_text('👥 <b>Настройки заданий</b>\n\nОднокурсники: '+('🟢 видны' if user_setting(chat,'peer_tasks_enabled') else '⚪ скрыты')+'\nМои задания: '+('🟢 можно показывать группе' if user_setting(chat,'share_tasks_enabled') else '⚪ только мне'),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('👥 '+('Скрыть' if user_setting(chat,'peer_tasks_enabled') else 'Показывать')+' задания однокурсников',callback_data='task:toggle_peers')],[InlineKeyboardButton('📢 '+('Скрыть мои от группы' if user_setting(chat,'share_tasks_enabled') else 'Разрешить мои группе'),callback_data='task:toggle_share')],[InlineKeyboardButton('‹ Назад',callback_data='p:profile')]])); return
    if data=='task:add':
        context.user_data['flow_action']='task_subject'; await q.message.edit_text('📝 Напиши предмет. Можно сокращённо, например: <code>хим</code>, <code>геодез</code>, <code>твимс</code>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:tasks')]])); return
    if data=='task:list':
        await render_task_list(q, chat)
        return
    if data=='p:ai': await q.message.edit_text('🤖 <b>Умный помощник</b>\n\nПросто напиши вопрос обычным сообщением. Я пойму дату и попробую найти нужную пару.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='p:menu')]])); return
    if data=='p:notify':
        labels=[('notify_daily','📅 Расписание на завтра'),('notify_lessons','⏰ Напоминания о парах'),('notify_changes','🔄 Изменения расписания'),('notify_tasks','📝 Задания'),('notify_announcements','📢 Объявления'),('notify_polls','📊 Опросы'),('notify_applications','⭐ Заявки/статусы'),('notify_system','📣 Сообщения системы')]
        st=notification_state(chat)
        kb=[
            [InlineKeyboardButton('📅 Только расписание',callback_data='notify:preset:schedule'),InlineKeyboardButton('✨ Всё нужное',callback_data='notify:preset:recommended')],
            [InlineKeyboardButton('🔕 Выключить всё',callback_data='notify:preset:off')],
            [InlineKeyboardButton('⚙️ Тонкая настройка',callback_data='notify:custom')],
            [InlineKeyboardButton('🌙 '+('Тихие часы: ВКЛ' if quiet_now(chat) else 'Тихие часы: ВЫКЛ'),callback_data='notify:quiet')],
            [InlineKeyboardButton('⏰ Напоминать за 60 мин',callback_data='notify:reminder')],
            [InlineKeyboardButton('‹ Назад',callback_data='p:menu')]
        ]
        with connect() as c: rr=c.execute('SELECT reminder_minutes,quiet_enabled,quiet_start,quiet_end FROM users WHERE chat_id=?',(chat,)).fetchone()
        rm=rr[0] if rr else 60; qtxt=f'\n🌙 Тихие часы: {rr[2]}–{rr[3]}' if rr and rr[1] else ''
        kb[-2]=[InlineKeyboardButton(f'⏰ Напоминание: за {rm} мин',callback_data='notify:reminder')]
        await q.message.edit_text('🔔 <b>Центр уведомлений</b>\n\n<b>Сейчас:</b> '+notification_preset_name(chat)+qtxt+'\n\nГотовые режимы + точная настройка + тихие часы. Всё меняется одним нажатием.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
    if data=='notify:quiet':
        with connect() as c: row=c.execute('SELECT quiet_enabled,quiet_start,quiet_end FROM users WHERE chat_id=?',(chat,)).fetchone()
        enabled=not bool(row and row[0]); set_quiet(chat,enabled)
        await q.message.edit_text(('🌙 <b>Тихие часы включены</b>\n\nУведомления не будут приходить с 23:00 до 07:00. Важные действия внутри бота остаются доступными.' if enabled else '☀️ <b>Тихие часы выключены.</b>'),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ К уведомлениям',callback_data='p:notify')]])); return
    if data=='notify:reminder':
        rm=cycle_reminder_minutes(chat)
        await q.message.edit_text(f'⏰ <b>Напоминание</b>\n\nТеперь бот будет напоминать о парах примерно за <b>{rm} минут</b>.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⏰ Изменить',callback_data='notify:reminder')],[InlineKeyboardButton('‹ К уведомлениям',callback_data='p:notify')]])); return
    if data.startswith('notify:preset:'):
        preset=data.rsplit(':',1)[1]; set_notification_preset(chat,preset)
        await q.message.edit_text('🔔 <b>Настройки сохранены</b>\n\nСейчас: <b>'+esc(notification_preset_name(chat))+'</b>\n\nНичего лишнего присылать не буду.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚙️ Настроить точнее',callback_data='notify:custom')],[InlineKeyboardButton('‹ К уведомлениям',callback_data='p:notify')]])); return
    if data=='notify:custom':
        labels=[('notify_daily','📅 Расписание на завтра'),('notify_lessons','⏰ Напоминания о парах'),('notify_changes','🔄 Изменения расписания'),('notify_tasks','📝 Задания'),('notify_announcements','📢 Объявления'),('notify_polls','📊 Опросы'),('notify_applications','⭐ Заявки/статусы'),('notify_system','📣 Сообщения системы')]
        kb=[[InlineKeyboardButton(('🟢 ' if user_setting(chat,f) else '⚪ ')+label,callback_data='notify:'+f)] for f,label in labels]
        kb += [[InlineKeyboardButton('📅 Только расписание',callback_data='notify:preset:schedule')],[InlineKeyboardButton('‹ К уведомлениям',callback_data='p:notify')]]
        await q.message.edit_text('⚙️ <b>Тонкая настройка</b>\n\nНажимай на пункты, которые хочешь получать.\n<b>📅 Только расписание</b> — лучший вариант, если тебе больше ничего не нужно.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith('notify:'):
        field=data.split(':',1)[1]
        if field in NOTIFY_FIELDS:
            set_user_setting(chat,field,not user_setting(chat,field))
            labels=[('notify_daily','📅 Расписание на завтра'),('notify_lessons','⏰ Напоминания о парах'),('notify_changes','🔄 Изменения расписания'),('notify_tasks','📝 Задания'),('notify_announcements','📢 Объявления'),('notify_polls','📊 Опросы'),('notify_applications','⭐ Заявки/статусы'),('notify_system','📣 Сообщения системы')]
            kb=[[InlineKeyboardButton(('🟢 ' if user_setting(chat,f) else '⚪ ')+label,callback_data='notify:'+f)] for f,label in labels]
            kb += [[InlineKeyboardButton('📅 Только расписание',callback_data='notify:preset:schedule')],[InlineKeyboardButton('‹ К уведомлениям',callback_data='p:notify')]]
            await q.message.edit_text('⚙️ <b>Тонкая настройка</b>\n\nСейчас: <b>'+esc(notification_preset_name(chat))+'</b>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
    if data=='p:profile':
        p=profile(chat); rows=[[InlineKeyboardButton('🎓 Сменить группу',callback_data='profile:group')]]
        if not is_leader(chat) and not leader_application_blocked(chat): rows.append([InlineKeyboardButton('⭐ Подать заявку на старосту',callback_data='leaderapp:new')])
        rows += [[InlineKeyboardButton('🔔 Уведомления',callback_data='p:notify')],[InlineKeyboardButton('👥 Настройки заданий',callback_data='profile:tasks')]]
        if sponsor_button_allowed(chat):
            rows.append([InlineKeyboardButton('⭐ Отключить спонсора · 25 ⭐',callback_data='sponsor:buy')])
        rows.append([InlineKeyboardButton('‹ Назад',callback_data='p:menu')])
        await q.message.edit_text(f'👤 <b>Профиль</b>\n\nФИО: <b>{esc(p[1])}</b>\nГруппа: <b>{esc(p[2])}</b>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(rows)); return
    if data=='profile:group': set_registration(chat,'await_group'); await q.message.edit_text('🎓 Напиши новую группу. Старый профиль останется, изменится только расписание.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:profile')]])); return
    if data=='p:leader:schedule' and (is_leader(chat) or owner_only(chat)):
        await q.message.edit_text('📅 <b>Расписание группы</b>',parse_mode=ParseMode.HTML,reply_markup=schedule_menu()); return
    if data=='leader:edit' and (is_leader(chat) or owner_only(chat)):
        await q.message.edit_text('✏️ <b>Правки расписания</b>\n\nВыбери действие. Для владельца сначала используется выбранная группа из панели.',parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('➕ Добавить',callback_data='leader:edit:add'),InlineKeyboardButton('✏️ Заменить',callback_data='leader:edit:replace')],
                [InlineKeyboardButton('🗑 Удалить',callback_data='leader:edit:delete')],
                [InlineKeyboardButton('‹ Назад',callback_data='p:leader')],
            ])); return
    if data.startswith('leader:edit:') and (is_leader(chat) or owner_only(chat)):
        action=data.rsplit(':',1)[1]
        context.user_data['leader_schedule_action']=action
        await q.message.edit_text('📅 Отправь правку.\nДобавить/заменить: <code>08.10.2026 09:00-10:35 | Предмет | Преподаватель | Аудитория</code>\nУдалить: <code>08.10.2026 09:00-10:35 | причина</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:leader')]])); return
    if data=='p:leader' and (is_leader(chat) or owner_only(chat)): await q.message.edit_text('👑 <b>Кабинет старосты</b>',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return
    if data=='p:ai' and await require_ready(update, context):
        context.user_data.pop('ai_mode', None)
        await q.answer()
        await q.message.edit_text('🚧 <b>ИИ-помощник в разработке</b>\n\nФункционал сохранён в проекте, но публичный доступ временно закрыт.\n\nМы дорабатываем качество ответов и откроем помощника после завершения тестирования.', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ В меню',callback_data='p:menu')]]))
        return
    if data=='lead:students' and (is_leader(chat) or owner_only(chat)):
        g=leader_group(chat, context); students=group_students(g)
        lines=[f'👥 <b>Состав {esc(g)}</b>',f'\nВсего: <b>{len(students)}</b>']
        for i,r in enumerate(students,1): lines.append(f'\n{i}. {esc(r[1] or r[2] or "Без ФИО")}')
        kb=[[InlineKeyboardButton('➕ Пригласить однокурсников',callback_data='lead:invite')]]
        for r in students:
            if r[0]!=chat: kb.append([InlineKeyboardButton('🗑 Удалить · '+(r[1] or r[2] or str(r[0]))[:28],callback_data=f'lead:remove:{r[0]}')])
        kb.append([InlineKeyboardButton('‹ Назад',callback_data='p:leader')])
        await q.message.edit_text(''.join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
    if data=='lead:invite' and (is_leader(chat) or owner_only(chat)):
        token=create_group_invite(leader_group(chat, context),chat)
        try: me=await context.application.bot.get_me(); link=f'https://t.me/{me.username}?start=join_{token}'
        except Exception: link=f'бот?start=join_{token}'
        await q.message.edit_text(f'🔗 <b>Приглашение в группу {esc(leader_group(chat, context))}</b>\n\nОтправь эту ссылку однокурсникам. Она действует 7 дней и рассчитана на 100 вступлений.\n\n<code>{esc(link)}</code>',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📋 Ссылка',callback_data='lead:invite:copy')],[InlineKeyboardButton('‹ Назад',callback_data='lead:students')]])); return
    if data=='lead:invite:copy':
        token=create_group_invite(leader_group(chat, context),chat); me=await context.application.bot.get_me(); link=f'https://t.me/{me.username}?start=join_{token}'
        await q.message.edit_text(f'🔗 <code>{esc(link)}</code>\n\nСкопируй и отправь в чат группы.',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Назад',callback_data='lead:students')]])); return
    if data.startswith('lead:remove:') and (is_leader(chat) or owner_only(chat)):
        target=int(data.split(':')[-1]); g=leader_group(chat, context)
        with connect() as c: c.execute("UPDATE users SET group_code='',group_url='',reg_state='await_group' WHERE chat_id=? AND group_code=?",(target,g))
        try: await context.application.bot.send_message(target,f'ℹ️ Староста исключил тебя из группы <b>{esc(g)}</b>. Ты можешь выбрать другую группу в профиле.',parse_mode=ParseMode.HTML)
        except Exception: pass
        await q.message.edit_text('✅ Студент удалён из состава группы.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('👥 Состав группы',callback_data='lead:students'),InlineKeyboardButton('🔗 Пригласить',callback_data='lead:invite')],[InlineKeyboardButton('‹ Назад',callback_data='p:leader')]])); return
    if data=='invite:join':
        with connect() as c: ir=c.execute('SELECT token FROM pending_invites WHERE chat_id=?',(chat,)).fetchone()
        inv=invite_info(ir[0]) if ir else None
        if not inv or not consume_invite(inv[0],chat): await q.message.edit_text('⚠️ Приглашение недействительно или уже использовано.'); return
        # resolve group from current catalog/cache
        rows=group_catalog(); g=next((r for r in rows if r[0]==inv[1]),None)
        if not g: await q.message.edit_text('⚠️ Не удалось найти расписание этой группы. Попробуй позже.'); return
        p=profile(chat); save_profile(chat,p[1] or '',g); set_registration(chat,'')
        with connect() as c: c.execute('DELETE FROM pending_invites WHERE chat_id=?',(chat,))
        await q.message.edit_text(f'🎉 <b>Ты в группе {esc(g[0])}</b>\n\nРасписание, задания и уведомления теперь привязаны к этой группе.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); return
    if data=='invite:other':
        with connect() as c: c.execute('DELETE FROM pending_invites WHERE chat_id=?',(chat,))
        set_registration(chat,'await_group'); await q.message.edit_text('🎓 Введи свою группу, например <code>ОИ-11.1</code>.',parse_mode=ParseMode.HTML); return
    if data=='lead:announce' and (is_leader(chat) or owner_only(chat)): context.user_data['flow_action']='announce'; await q.message.edit_text('📢 Напиши текст объявления.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:leader')]])); return
    if data=='poll:new' and (is_leader(chat) or owner_only(chat)): context.user_data['flow_action']='poll_text'; await q.message.edit_text('📊 Напиши вопрос опроса.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ Отмена',callback_data='p:leader')]])); return
    if data=='poll:list' and (is_leader(chat) or owner_only(chat)):
        with connect() as c: polls=c.execute('SELECT id,title,active FROM polls WHERE leader_id=? ORDER BY id DESC LIMIT 20',(chat,)).fetchall()
        txt='📸 <b>Опросы</b>\n\n'+('\n'.join(f'#{r[0]} · {esc(r[1])} · {"🟢" if r[2] else "⚪"}' for r in polls) if polls else 'Пока нет опросов.')
        await q.message.edit_text(txt,parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return
    if data.startswith('poll:publish:') and (is_leader(chat) or owner_only(chat)):
        need=int(data.rsplit(':',1)[1]); pending=context.user_data.pop('poll_pending',None)
        if not pending: return
        p=profile(chat)
        pending['require_photo']=need
        result,reason,req_id=await submit_publication(context.application,chat,leader_group(chat,context),'poll',pending)
        if result=='accept': msg='✅ Опрос прошёл проверку и опубликован.'
        elif result=='reject': msg='❌ Опрос не прошёл проверку. Проверь формулировку и варианты.'
        else: msg='🛡 Опрос отправлен на проверку. После решения владельца он появится у группы.'
        await q.message.edit_text(msg,reply_markup=leader_premium_menu()); return
    if data.startswith('pollvote:'):
        _,pid_s,idx_s=data.split(':'); pid=int(pid_s); idx=int(idx_s)
        with connect() as c:
            row=c.execute('SELECT group_code,title,question,options_json,require_photo,active FROM polls WHERE id=?',(pid,)).fetchone()
            p=profile(chat)
            if not row or not row[5] or not p or p[2]!=row[0]: return
            c.execute('INSERT INTO poll_answers(poll_id,chat_id,option_idx,answered_at) VALUES(?,?,?,?) ON CONFLICT(poll_id,chat_id) DO UPDATE SET option_idx=excluded.option_idx,answered_at=excluded.answered_at',(pid,chat,idx,now_iso()))
        if row[4]:
            context.user_data['waiting_poll_photo']=pid
            await q.message.edit_text('✅ Ответ сохранён.\n\n📸 Теперь отправь сюда скриншот подтверждения.',parse_mode=ParseMode.HTML); return
        await q.message.edit_text('✅ <b>Ответ сохранён.</b>',parse_mode=ParseMode.HTML); return
    # delegate schedule callbacks after readiness
    if data in {'today','tomorrow','week','next','refresh','settings','toggle_daily','toggle_changes','help','status','menu','leader'}:
        if await require_ready(update, context):
            await schedule_callback_router(update,context,data)
        return


async def schedule_callback_router(update,context,data):
    # Re-implement the most useful old callbacks without depending on the old callback dispatcher.
    q=update.callback_query; chat=q.message.chat.id
    if data=='today':
        l=await get_day(now().date(),chat_id=chat); await q.message.edit_text(format_day(now().date(),l),parse_mode=ParseMode.HTML,reply_markup=schedule_menu()); return
    if data=='tomorrow':
        d=now().date()+timedelta(days=1); l=await get_day(d,chat_id=chat); await q.message.edit_text(format_day(d,l),parse_mode=ParseMode.HTML,reply_markup=schedule_menu()); return
    if data=='week':
        d0=now().date(); text='\n\n'.join(format_compact_day(d0+timedelta(days=i),(await get_day(d0+timedelta(days=i),chat_id=chat))) for i in range(7)); await q.message.edit_text('🗓 <b>7 дней</b>\n\n'+text,parse_mode=ParseMode.HTML,reply_markup=schedule_menu()); return
    if data=='next': await next_lesson(update,context); return
    if data=='refresh': await refresh_schedule(update,context); return
    if data=='settings': await q.message.edit_text('🔔 <b>Уведомления</b>',parse_mode=ParseMode.HTML,reply_markup=settings_keyboard(chat)); return
    if data=='toggle_daily':
        row=profile(chat); set_setting(chat,'daily_enabled',not bool(row[6])); await q.message.edit_text('🔔 <b>Уведомления</b>',parse_mode=ParseMode.HTML,reply_markup=settings_keyboard(chat)); return
    if data=='toggle_changes':
        row=profile(chat); set_setting(chat,'change_enabled',not bool(row[7])); await q.message.edit_text('🔔 <b>Уведомления</b>',parse_mode=ParseMode.HTML,reply_markup=settings_keyboard(chat)); return
    if data=='menu': await q.message.edit_text('🏠 <b>Главное меню</b>',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat)); return
    if data=='leader' and is_leader(chat): await q.message.edit_text('👑 <b>Кабинет старосты</b>',parse_mode=ParseMode.HTML,reply_markup=leader_premium_menu()); return


async def next_lesson(update,context):
    chat=update.effective_chat.id; cur=now(); candidates=[]; data=await group_data(chat)
    for off in range(8):
        d=cur.date()+timedelta(days=off)
        for l in data.get(d,[]):
            try: dt=datetime.combine(d,datetime.strptime(l.start,'%H:%M').time(),tzinfo=TZ)
            except: continue
            if dt>cur: candidates.append((dt,l,d))
    if not candidates: text='🎉 Ближайших занятий не найдено.'
    else:
        dt,l,d=min(candidates,key=lambda x:x[0]); mins=max(0,int((dt-cur).total_seconds()//60)); text=f'⏭ <b>Следующая пара</b>\n\n📅 {esc(date_ru(d))}\n⏰ <b>{l.start}–{l.end}</b>\n📚 {esc(l.subject)}\n'+(f'👨‍🏫 {esc(l.teacher)}\n' if l.teacher else '')+(f'🚪 {esc(l.room)}\n' if l.room else '')+f'\n⏳ Через <b>{mins//60} ч. {mins%60} мин.</b>'
    await reply_ui(update, context, text,parse_mode=ParseMode.HTML,reply_markup=schedule_menu())


async def refresh_schedule(update,context):
    chat=update.effective_chat.id
    try:
        data=await group_data(chat,True); await reply_ui(update, context, f'🔄 <b>Готово.</b> Обновлено дней: {len(data)}',parse_mode=ParseMode.HTML,reply_markup=schedule_menu())
    except Exception as e: await reply_ui(update, context, '⚠️ Не удалось обновить расписание.',reply_markup=schedule_menu())


async def help_cmd(update,context):
    if not await require_ready(update, context): return
    await reply_ui(update, context, 'ℹ️ <b>Помощь</b>\n\nМожно нажимать кнопки или писать вопрос обычным текстом.\n\nНапример: «что завтра?», «какие пары в пятницу?», «когда следующая геодезия?»',parse_mode=ParseMode.HTML,reply_markup=premium_menu(update.effective_chat.id))


async def owner_help_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OWNER_ID: return
    await reply_ui(update, context, owner_commands_help(), parse_mode=ParseMode.HTML, reply_markup=owner_panel_keyboard())


async def ai_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_ready(update, context): return
    context.user_data.pop('ai_mode', None)
    await reply_ui(update, context,
        '🚧 <b>ИИ-помощник в разработке</b>\n\n'
        'Функционал сохранён в проекте, но публичный доступ временно закрыт.\n\n'
        'После завершения тестирования помощник будет снова доступен из главного меню.',
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ В меню',callback_data='p:menu')]]))


async def today(update,context):
    if not await require_ready(update, context): return
    d=now().date(); await reply_ui(update, context, format_day(d,await get_day(d,chat_id=update.effective_chat.id)),parse_mode=ParseMode.HTML,reply_markup=schedule_menu())
async def tomorrow(update,context):
    if not await require_ready(update, context): return
    d=now().date()+timedelta(days=1); await reply_ui(update, context, format_day(d,await get_day(d,chat_id=update.effective_chat.id)),parse_mode=ParseMode.HTML,reply_markup=schedule_menu())
async def week(update,context):
    if not await require_ready(update, context): return
    d0=now().date(); text='\n\n'.join(format_compact_day(d0+timedelta(days=i),await get_day(d0+timedelta(days=i),chat_id=update.effective_chat.id)) for i in range(7)); await reply_ui(update, context, '🗓 <b>7 дней</b>\n\n'+text,parse_mode=ParseMode.HTML,reply_markup=schedule_menu())
async def subscribe(update,context):
    if not await require_ready(update, context): return
    set_setting(update.effective_chat.id,'daily_enabled',True); await reply_ui(update, context, '🔔 Ежедневные уведомления включены.',reply_markup=premium_menu(update.effective_chat.id))
async def unsubscribe(update,context):
    if not await require_ready(update, context): return
    set_setting(update.effective_chat.id,'daily_enabled',False); await reply_ui(update, context, '🔕 Ежедневные уведомления выключены.',reply_markup=premium_menu(update.effective_chat.id))
async def refresh_cmd(update,context):
    if not await require_ready(update, context): return
    await refresh_schedule(update,context)
async def next_cmd(update,context):
    if not await require_ready(update, context): return
    await next_lesson(update,context)




async def photo_router(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo: return
    chat=update.effective_chat.id; pid=context.user_data.get('waiting_poll_photo')
    if not pid: return
    fid=update.message.photo[-1].file_id
    with connect() as c:
        row=c.execute('SELECT leader_id,group_code FROM polls WHERE id=?',(pid,)).fetchone()
        if not row: return
        c.execute('UPDATE poll_answers SET photo_file_id=?,answered_at=? WHERE poll_id=? AND chat_id=?',(fid,now_iso(),pid,chat))
        c.execute('INSERT INTO events(event,data,created_at) VALUES(?,?,?)',('poll_photo',f'poll={pid} student={chat}',now_iso()))
    context.user_data.pop('waiting_poll_photo',None)
    await reply_ui(update, context, '📸 <b>Скриншот принят.</b> Староста сможет проверить его в кабинете.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat))




def add_leader(chat_id: int, username: str, first_name: str, added_by: int):
    # Один староста на группу; разные группы могут иметь разных старост.
    p=profile(chat_id); g=p[2] if p else ''
    with connect() as c:
        if g: c.execute("DELETE FROM leaders WHERE chat_id IN (SELECT chat_id FROM users WHERE group_code=?) AND chat_id!=?",(g,chat_id))
        c.execute("""INSERT INTO leaders(chat_id,username,first_name,added_by,added_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, added_by=excluded.added_by, added_at=excluded.added_at""",
                  (chat_id,username or '',first_name or '',added_by,now_iso()))


async def leader_application(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_ready(update, context): return
    chat=update.effective_chat.id; p=profile(chat)
    if leader_application_blocked(chat):
        await reply_ui(update, context, '🚫 <b>Повторная заявка на старосту недоступна.</b>\n\nТвоя предыдущая заявка была отклонена владельцем. Повторная подача запрещена.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat))
        return
    with connect() as c:
        active=c.execute("SELECT id FROM leader_applications_v12 WHERE chat_id=? AND status='pending'",(chat,)).fetchone()
        if active:
            await reply_ui(update, context, '🕓 Заявка уже находится на рассмотрении.'); return
        created=now(); deadline=created
        days=0
        while days<5:
            deadline+=timedelta(days=1)
            if deadline.weekday()<5: days+=1
        c.execute('INSERT INTO leader_applications_v12(chat_id,group_code,full_name,created_at,deadline_at) VALUES(?,?,?,?,?)',(chat,p[2],p[1],created.isoformat(),deadline.isoformat()))
    try:
        await context.application.bot.send_message(OWNER_ID,f'⭐ <b>Новая заявка старосты</b>\\n\\n👤 {esc(p[1])}\\n🎓 {esc(p[2])}\\n⏳ До: {deadline.strftime("%d.%m.%Y")}',parse_mode=ParseMode.HTML,disable_notification=True)
    except Exception: pass
    await reply_ui(update, context, f'⭐ Заявка отправлена владельцу.\\n\\n⏳ Решение — до {deadline.strftime("%d.%m.%Y")}.',parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat))


async def admin_leader_applications(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id!=OWNER_ID: return
    with connect() as c: rows=c.execute("SELECT id,full_name,group_code,status,deadline_at FROM leader_applications_v12 WHERE status='pending' ORDER BY id DESC").fetchall()
    if not rows: await reply_ui(update, context, '⭐ Активных заявок нет.'); return
    txt='⭐ <b>Заявки старост</b>\\n\\n'+ '\\n'.join(f'#{r[0]} · {esc(r[1])} · {esc(r[2])} · до {esc(r[4][:10])}' for r in rows)
    await reply_ui(update, context, txt,parse_mode=ParseMode.HTML)

async def post_init(application):
    ensure_schema()
    try:
        await asyncio.to_thread(refresh_group_catalog, False)
    except Exception as e:
        log.warning('group catalog warmup: %s', e)

    # post_init runs before Application.start().  Using Application.create_task()
    # here makes PTB warn that the task cannot be awaited automatically.
    # Schedule the long-running workers on the active event loop instead.
    loop = asyncio.get_running_loop()
    application.bot_data['_background_tasks'] = [
        loop.create_task(scheduler_multi(application), name='sgugit-scheduler'),
        loop.create_task(owner_weekly_report(application), name='sgugit-weekly-report'),
    ]


async def post_shutdown(application):
    """Cancel background workers cleanly when polling stops."""
    tasks = application.bot_data.pop('_background_tasks', [])
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def precheckout_stars(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.pre_checkout_query
    if not q.invoice_payload.startswith('sponsor_exempt:'):
        await q.answer(ok=False,error_message='Неизвестный платёж.')
        return
    try:
        chat=int(q.invoice_payload.split(':',1)[1])
    except Exception:
        await q.answer(ok=False,error_message='Некорректный платёж.')
        return
    if chat != q.from_user.id or q.total_amount != SPONSOR_EXEMPT_STARS:
        await q.answer(ok=False,error_message='Счёт устарел или изменён.')
        return
    await q.answer(ok=True)

async def successful_stars_payment(update:Update, context:ContextTypes.DEFAULT_TYPE):
    payment=update.message.successful_payment
    if not payment or not payment.invoice_payload.startswith('sponsor_exempt:'): return
    chat=update.effective_chat.id; p=profile(chat); group_code=p[2] if p else ''
    is_leader_now=is_leader(chat)
    with connect() as c:
        c.execute('INSERT INTO sponsor_exemptions(chat_id,personal,group_code,group_enabled,stars,purchased_at,telegram_charge_id) VALUES(?,?,?,?,?,?,?) '
                  'ON CONFLICT(chat_id) DO UPDATE SET personal=1,group_code=excluded.group_code,group_enabled=excluded.group_enabled,stars=sponsor_exemptions.stars+excluded.stars,purchased_at=excluded.purchased_at,telegram_charge_id=excluded.telegram_charge_id',
                  (chat,1,group_code,1 if is_leader_now and group_code else 0,payment.total_amount,now_iso(),payment.telegram_payment_charge_id))
        if is_leader_now and group_code:
            c.execute('INSERT INTO group_sponsor_exemptions(group_code,leader_id,stars,purchased_at,telegram_charge_id) VALUES(?,?,?,?,?) '
                      'ON CONFLICT(group_code) DO UPDATE SET leader_id=excluded.leader_id,stars=group_sponsor_exemptions.stars+excluded.stars,purchased_at=excluded.purchased_at,telegram_charge_id=excluded.telegram_charge_id',
                      (group_code,chat,payment.total_amount,now_iso(),payment.telegram_payment_charge_id))
    mid=context.user_data.pop('stars_invoice_message_id',None)
    if mid:
        try: await context.application.bot.delete_message(chat,mid)
        except Exception: pass
    await reply_ui(update,context,'🎉 <b>Готово!</b>\n\n⭐ Спонсор отключён. У тебя его больше не будет в кнопках. '+('\n👥 Для твоей группы — тоже отключён.' if is_leader_now and group_code else ''),parse_mode=ParseMode.HTML,reply_markup=premium_menu(chat))

