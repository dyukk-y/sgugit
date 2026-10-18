"""Статическая проверка: необъявленные имена в модулях (замена pyflakes без сети)."""
import builtins, pathlib, symtable, sys

def check(path):
    src = pathlib.Path(path).read_text(encoding="utf-8")
    top = symtable.symtable(src, str(path), "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    bad = []
    def walk(t):
        for s in t.get_symbols():
            n = s.get_name()
            if not s.is_referenced(): continue
            local_def = s.is_assigned() or s.is_imported() or s.is_parameter() or s.is_namespace()
            is_global_ref = s.is_global() or (t.get_type() in ("module", "class") and not local_def and not s.is_free())
            if is_global_ref and n not in defined and not hasattr(builtins, n) and n not in ("__file__", "__name__", "__doc__"):
                bad.append((t.get_name(), n))
        for c in t.get_children(): walk(c)
    walk(top)
    return bad

problems = 0
for p in sorted(pathlib.Path(".").glob("app/**/*.py")) + sorted(pathlib.Path("tests").glob("test_*.py")):
    for scope, name in check(p):
        print(f"{p}: имя «{name}» в {scope} не определено"); problems += 1
print("проблем:", problems); sys.exit(1 if problems else 0)
