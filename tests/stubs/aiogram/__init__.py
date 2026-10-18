"""Минимальная заглушка aiogram ТОЛЬКО для тестов без сети: проверяет логику склейки, а не API aiogram."""
class _Magic:
    def __getattr__(self, name): return self
    def __eq__(self, other): return self
    def __hash__(self): return 1
    def __invert__(self): return self
    def __call__(self, *a, **k): return self
    def startswith(self, *a): return self
    def in_(self, *a): return self
F = _Magic()
class BaseMiddleware: pass
class Bot: pass
class Dispatcher:
    def __init__(self, *a, **k): self.errors = type("E", (), {"register": lambda s, f: None})()
    def include_router(self, r): pass
class _Observer:
    def __init__(self, store, kind): self.store, self.kind, self.middlewares = store, kind, []
    def __call__(self, *filters):
        def deco(fn): self.store.setdefault(self.kind, []).append((fn, filters)); return fn
        return deco
    def outer_middleware(self, mw): self.middlewares.append(mw)
class Router:
    def __init__(self, name=None):
        self.handlers = {}
        self.message = _Observer(self.handlers, "message"); self.callback_query = _Observer(self.handlers, "callback_query")
        self.my_chat_member = _Observer(self.handlers, "my_chat_member")
