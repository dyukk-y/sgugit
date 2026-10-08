from pathlib import Path
import ast

ROOT = Path(__file__).parents[1]
PKG = ROOT / 'src' / 'sgugit_bot'


def top_level_defs(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]


def test_package_compiles_and_has_no_duplicate_definitions():
    names = {}
    for path in PKG.glob('*.py'):
        for name in top_level_defs(path):
            names.setdefault(name, []).append(path.name)
    duplicates = {k: v for k, v in names.items() if len(v) > 1}
    assert not duplicates, duplicates


def test_single_runtime_entrypoint():
    main = (PKG / 'main.py').read_text()
    assert 'def build_application' in main
    assert 'def main' in main
    assert 'main_v12' not in main
    assert 'legacy_callback_router' not in main


def test_sponsor_is_tracked_and_redirected():
    services = (PKG / 'services.py').read_text()
    web = (PKG / 'web.py').read_text()
    handlers = (PKG / 'handlers.py').read_text()
    assert 'def sponsor_click_token' in services
    assert 'def sponsor_click_url' in services
    assert 'hmac.new' in services
    assert '/sponsor/click' in web
    assert 'RedirectResponse(SPONSOR_URL, status_code=302)' in web
    assert "if data=='sponsor:open'" in handlers


def test_referral_is_personal_and_shareable():
    services = (PKG / 'services.py').read_text()
    handlers = (PKG / 'handlers.py').read_text()
    assert 'def referral_link' in services
    assert 'referral_signature' in services
    assert 'def referral_share_url' in services
    assert 't.me/share/url' in services
    assert 'share_url=referral_share_url' in handlers
    assert "?start=ref_" in services


def test_task_ownership_and_group_visibility():
    handlers = (PKG / 'handlers.py').read_text()
    assert "SELECT chat_id FROM tasks WHERE id=?" in handlers
    assert "if not row or row[0]!=chat" in handlers
    assert 'WHERE group_code=? AND shared=1 AND chat_id!=?' in handlers
    assert "context.user_data.pop('pending_task',None)" in handlers
