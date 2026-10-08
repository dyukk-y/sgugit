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
    assert 'APP_VERSION = "2.3.3"' in services
    assert 'version="2.3.3"' in project

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

def test_owner_help_is_registered_and_ai_surface_is_removed():
    main=(PKG/'main.py').read_text(encoding='utf-8')
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    services=(PKG/'services.py').read_text(encoding='utf-8')
    assert "CommandHandler('owner_help',owner_help_cmd)" in main
    assert "CommandHandler('ai',ai_cmd)" not in main
    assert 'async def ai_cmd' not in handlers
    assert 'p:ai' not in handlers
    assert 'ИИ-помощник' not in services
    assert 'def owner_commands_help' in services


def test_profile_replaces_ai_and_contains_notifications():
    services=(PKG/'services.py').read_text(encoding='utf-8')
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8')
    menu=services[services.index('def premium_menu'):services.index('def schedule_menu')]
    assert "callback_data='p:profile'" in menu
    assert 'ИИ-помощник' not in menu
    assert "callback_data='p:notify'" not in menu
    profile=handlers[handlers.index("if data=='p:profile'"):handlers.index("if data=='profile:group'")]
    assert "callback_data='p:notify'" in profile


def test_legacy_notification_toggles_mirror_current_notification_fields():
    core=(PKG/'core.py').read_text(encoding='utf-8')
    assert '"daily_enabled": "notify_daily"' in core
    assert '"change_enabled": "notify_changes"' in core

def test_invite_menu_has_no_useless_open_bot_button():
    handlers=(PKG/'handlers.py').read_text(encoding='utf-8'); start=handlers.index("if data=='p:invite':"); end=handlers.index("if data=='p:schedule':",start); assert 'Открыть бота' not in handlers[start:end]

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
    text = (Path(__file__).parents[1] / 'src' / 'sgugit_bot' / 'handlers.py').read_text(encoding='utf-8')
    assert "if reg_complete(chat):" in text
    assert "set_registration(chat, '')" in text
    assert "Главное меню" in text


def test_owner_direct_leader_assignment_notifies_user():
    from pathlib import Path
    text = (Path(__file__).parents[1] / 'src' / 'sgugit_bot' / 'handlers.py').read_text(encoding='utf-8')
    assert "Ты назначен старостой!" in text
    assert "Пользователь уведомлён" in text


