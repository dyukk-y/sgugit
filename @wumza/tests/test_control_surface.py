from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
PKG = ROOT / "src" / "sgugit_bot"


def test_owner_panel_buttons_have_handlers():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    # Every owner button declared in the panel must have an explicit callback path.
    callbacks = re.findall(r"callback_data='([^']+)'", services[services.index("def owner_panel_keyboard"):services.index("def owner_overview_text")])
    for cb in callbacks:
        assert cb in handlers or f"data.startswith('{cb.split(':')[0]}:" in handlers, cb


def test_leader_panel_core_actions_are_wired():
    services = (PKG / "services.py").read_text(encoding="utf-8")
    handlers = (PKG / "handlers.py").read_text(encoding="utf-8")
    for cb in ("p:leader:schedule", "leader:edit", "lead:students", "lead:invite", "lead:announce", "poll:new", "poll:list"):
        assert cb in services or cb in handlers
    assert "data=='p:leader:schedule'" in handlers
    assert "data=='leader:edit'" in handlers


def test_manual_schedule_changes_are_group_scoped():
    core = (PKG / "core.py").read_text(encoding="utf-8")
    services = (PKG / "services.py").read_text(encoding="utf-8")
    assert "group_code TEXT NOT NULL DEFAULT ''" in core
    assert "manual_rows(day, group_code)" in core
    assert "apply_manual_overrides(d,data.get(d,[]),g)" in services
    assert "record_manual_change" in services or "record_manual_change" in (PKG / "handlers.py").read_text(encoding="utf-8")


def test_owner_panel_command_is_registered():
    main = (PKG / "main.py").read_text(encoding="utf-8")
    assert "CommandHandler('panel',owner_panel_cmd)" in main


def test_main_import_surface_is_consistent():
    import ast
    main = ast.parse((PKG / "main.py").read_text(encoding="utf-8"))
    handlers = ast.parse((PKG / "handlers.py").read_text(encoding="utf-8"))
    services = ast.parse((PKG / "services.py").read_text(encoding="utf-8"))
    def defs(tree):
        return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    available = defs(handlers) | defs(services)
    imported = []
    for node in main.body:
        if isinstance(node, ast.ImportFrom) and node.module == "sgugit_bot.handlers":
            imported.extend(a.name for a in node.names)
    assert not [name for name in imported if name not in available]


def test_direct_main_entrypoint_is_configured():
    main = (PKG / "main.py").read_text(encoding="utf-8")
    assert "if __name__=='__main__': main()" in main
    assert "src\\sgugit_bot\\main.py" in main

def test_ai_public_access_is_disabled_but_feature_code_remains():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'src' / 'sgugit_bot' / 'core.py'
    text = p.read_text(encoding='utf-8')
    assert 'AI_ASSISTANT_ENABLED = False' in text


def test_ai_button_is_marked_in_development():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'src' / 'sgugit_bot' / 'services.py'
    text = p.read_text(encoding='utf-8')
    assert '🚧 ИИ-помощник · в разработке' in text
