from pathlib import Path

ROOT = Path(__file__).parents[1]
PKG = ROOT / "src" / "sgugit_bot"


def test_env_is_loaded_before_runtime_configuration():
    core = (PKG / "core.py").read_text(encoding="utf-8")
    assert "load_dotenv(BASE_DIR / \".env\", override=False)" in core
    assert "BASE_DIR = Path(__file__).resolve().parents[2]" in core


def test_sqlite_parent_directory_is_created_and_default_is_stable():
    core = (PKG / "core.py").read_text(encoding="utf-8")
    assert 'os.getenv("DB_PATH", "./data/sgugit.sqlite3")' in core
    assert "DB_PATH.parent.mkdir(parents=True, exist_ok=True)" in core


def test_weekly_report_insert_has_matching_columns_and_values():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    assert "owner_reports(period_start,period_end,created_at,file_name) VALUES(?,?,?,?)" in services
    assert "owner_reports(period_start,period_end,created_at,file_name) VALUES(?,?,?,?,?)" not in services


def test_web_uses_shared_application_reference():
    web = (PKG / "web.py").read_text(encoding="utf-8")
    main = (PKG / "main.py").read_text(encoding="utf-8")
    assert "core_module.BOT_APPLICATION" in web
    assert "core.BOT_APPLICATION = app" in main
    assert "start_web_server()" in main


def test_handlers_explicitly_imports_private_ui_helper_used_by_start():
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    assert "from .core import _delete_previous_ui" in handlers
    assert "await _delete_previous_ui(context, chat)" in handlers


def test_background_workers_start_after_post_init_without_application_create_task_warning():
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    assert "application.create_task(scheduler_multi(application))" not in handlers
    assert "application.create_task(owner_weekly_report(application))" not in handlers
    assert "loop.create_task(scheduler_multi(application), name='sgugit-scheduler')" in handlers
    assert "loop.create_task(owner_weekly_report(application), name='sgugit-weekly-report')" in handlers
    assert "async def post_shutdown(application):" in handlers


def test_sponsor_never_blocks_registration_or_text_router():
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    services = (PKG / "services.py").read_text(encoding="utf-8")
    start = handlers.index("async def text_router")
    end = handlers.index("async def callbacks", start)
    block = handlers[start:end]
    assert "sponsor_requirement_satisfied(chat)" not in block
    assert "sponsor_click_url(chat)" not in block
    assert "return True" in services[services.index('def sponsor_requirement_satisfied'):services.index('def sponsor_benefit_state')]


def test_container_and_render_use_direct_main_entrypoint():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert 'CMD ["python", "src/sgugit_bot/main.py"]' in docker
    assert "startCommand: python src/sgugit_bot/main.py" in render


def test_release_version_is_consistent():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'APP_VERSION = "2.3.0"' in services
    assert 'version="2.3.0"' in project

def test_disabled_sponsor_does_not_route_text_messages_into_sponsor_gate():
    from pathlib import Path
    handlers = Path(__file__).parents[1] / "src" / "sgugit_bot" / "handlers.py"
    text = handlers.read_text(encoding="utf-8")
    assert "sponsor_requirement_satisfied(chat)" not in text
    assert "if not sponsor_ok(chat) and not sponsor_personal_exempt(chat):" not in text


def test_sponsor_keyboard_has_no_actionless_button_when_disabled():
    from pathlib import Path
    services = Path(__file__).parents[1] / "src" / "sgugit_bot" / "services.py"
    text = services.read_text(encoding="utf-8")
    assert "if not sponsor_url():" in text
    assert "url=sponsor_click_url(chat_id)" in text



def test_owner_excel_uses_project_data_directory_not_unix_tmp():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    assert "reports_dir = BASE_DIR / 'data' / 'reports'" in services
    assert "reports_dir.mkdir(parents=True, exist_ok=True)" in services
    assert "Path('/tmp')" not in services


def test_welcome_uses_read_button_and_completed_profile_is_required():
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    assert "callback_data='welcome:read'" in handlers
    assert "callback_data='welcome:read'" in handlers[handlers.index("async def start"):handlers.index("async def text_router")]
    assert "Теперь обязательно введи ФИО полностью." in handlers


def test_notifications_do_not_require_sponsor_click():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    assert "sponsor_ok=1 OR chat_id IN" not in services
    assert "AND (sponsor_ok=1" not in services


def test_registration_finishes_in_main_menu_without_second_read_confirmation():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8'); start=handlers.index("if state=='await_fio':"); end=handlers.index("if (is_leader(chat) or owner_only(chat))",start); block=handlers[start:end]
    assert 'reply_markup=premium_menu(chat)' in block
    assert "callback_data='welcome:read'" not in block

def test_owner_help_and_ai_commands_are_registered():
    main=(PKG/'main.py').read_text(encoding='utf-8')
    assert "CommandHandler('owner_help',owner_help_cmd)" in main
    assert "CommandHandler('ai',ai_cmd)" in main
    assert 'def owner_commands_help' in (PKG/'services.py').read_text(encoding='utf-8')

def test_invite_menu_has_no_useless_open_bot_button():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8'); start=handlers.index("if data=='p:invite':"); end=handlers.index("if data=='p:schedule':",start); assert 'Открыть бота' not in handlers[start:end]

def test_ai_has_generic_next_lesson_path():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8'); services=(PKG/'services.py').read_text(encoding='utf-8'); assert "следующая пара" in handlers or "следующая пара" in services; assert "ближайшая пара" in handlers or "ближайшая пара" in services


def test_leader_application_rejection_is_permanent_and_button_is_hidden():
    services=(PKG/'services.py').read_text(encoding='utf-8')
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert 'def leader_application_blocked(chat_id: int) -> bool:' in services
    assert "status='rejected'" in services[services.index('def leader_application_blocked'):services.index('def leader_group')]
    assert 'leader_application_blocked(chat)' in handlers
    assert "not is_leader(chat) and not leader_application_blocked(chat)" in handlers
    assert 'Повторная подача запрещена' in handlers


def test_start_logic_contains_single_welcome_and_menu_for_registered_users():
    from pathlib import Path
    text = Path('src/sgugit_bot/handlers.py').read_text(encoding='utf-8')
    assert "if reg_complete(chat):" in text
    assert "set_registration(chat, '')" in text
    assert "Главное меню" in text


def test_owner_direct_leader_assignment_notifies_user():
    from pathlib import Path
    text = Path('src/sgugit_bot/handlers.py').read_text(encoding='utf-8')
    assert "Ты назначен старостой!" in text
    assert "Пользователь уведомлён" in text


def test_no_bs4_dependency_and_docker_preflight_is_valid():
    requirements=(ROOT/'requirements.txt').read_text(encoding='utf-8')
    docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
    build=(ROOT/'BUILD_CHECK.py').read_text(encoding='utf-8')
    assert 'beautifulsoup4' not in requirements
    assert 'bs4' not in build
    assert "import openpyxl, requests, telegram, fastapi, uvicorn, dotenv" in docker


def test_owner_sponsor_screen_avoids_nested_single_quote_fstring():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert 'secret_status = \'настроен\' if bot_setting("sponsor_tracking_secret")' in handlers
    assert "bot_setting(\'sponsor_tracking_secret\')" not in handlers[handlers.index("if data==\'owner:sponsor\'"):handlers.index("if data==\'owner:sponsor:url\'")]


def test_ai_supports_task_lookup_and_free_form_functionality():
    services=(PKG/'services.py').read_text(encoding='utf-8')
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert 'def _assistant_task_subject_score' in services
    assert 'def _assistant_tasks_text' in services
    assert 'какое задание по матану' in services
    assert 'task:subject:' in handlers


def test_task_subject_short_names_are_mapped_to_schedule_subjects():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert "'матан':'математический анализ'" in handlers
    assert "'геодез':'геодезия'" in handlers
    assert 'Понял предмет' in handlers


def test_ai_button_has_only_one_live_callback_route():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert handlers.count("data=='p:ai'") == 1


def test_ai_has_general_web_fallback():
    services=(PKG/'services.py').read_text(encoding='utf-8')
    assert 'async def _assistant_web_lookup' in services
    assert 'ru.wikipedia.org/w/api.php' in services
    assert 'web_answer=await _assistant_web_lookup(text)' in services


def test_edit_text_is_idempotent_on_message_not_modified():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    assert 'from telegram.error import BadRequest' in handlers
    assert 'async def safe_edit_text(message, *args, **kwargs):' in handlers
    assert 'if "Message is not modified" in str(exc):' in handlers
    assert 'q.message.edit_text(' not in handlers

