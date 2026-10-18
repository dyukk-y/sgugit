"""Тонкий слой доступа к БД: SQLite (stdlib) или PostgreSQL (asyncpg).

SQL пишется один раз с плейсхолдерами ``?``; для PostgreSQL они превращаются в ``$1, $2...``.
Все значения времени - целые секунды UTC, даты - строки ``YYYY-MM-DD``, флаги - 0/1.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterable, Sequence

log = logging.getLogger(__name__)


def _pg_sql(sql: str) -> str:
    out: list[str] = []
    n = 0
    for ch in sql:
        if ch == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


class _SqliteConn:
    def __init__(self, raw: sqlite3.Connection):
        self.raw = raw

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        def f() -> int:
            return self.raw.execute(sql, tuple(params)).rowcount

        return await asyncio.to_thread(f)

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        data = [tuple(r) for r in rows]

        def f() -> None:
            self.raw.executemany(sql, data)

        await asyncio.to_thread(f)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        def f() -> list[dict]:
            return [dict(r) for r in self.raw.execute(sql, tuple(params)).fetchall()]

        return await asyncio.to_thread(f)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        def f() -> dict | None:
            row = self.raw.execute(sql, tuple(params)).fetchone()
            return dict(row) if row is not None else None

        return await asyncio.to_thread(f)

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        def f() -> int:
            rows = self.raw.execute(sql + " RETURNING id", tuple(params)).fetchall()
            return int(rows[0][0])

        return await asyncio.to_thread(f)


class _PgConn:
    def __init__(self, conn: Any):
        self.c = conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        status = await self.c.execute(_pg_sql(sql), *params)
        try:
            return int(str(status).split()[-1])
        except (ValueError, IndexError):
            return 0

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        await self.c.executemany(_pg_sql(sql), [tuple(r) for r in rows])

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        return [dict(r) for r in await self.c.fetch(_pg_sql(sql), *params)]

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        r = await self.c.fetchrow(_pg_sql(sql), *params)
        return dict(r) if r is not None else None

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        return int(await self.c.fetchval(_pg_sql(sql) + " RETURNING id", *params))


class Database:
    def __init__(self, url: str):
        self.url = url
        self.kind = "pg" if url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")) else "sqlite"
        self.dirty = False  # были ли значимые изменения (для частых бэкапов в режиме SQLite)
        self._lock = asyncio.Lock()
        self._raw: sqlite3.Connection | None = None
        self._pool: Any = None

    # -------- подключение --------
    async def connect(self) -> None:
        if self.kind == "sqlite":
            path = self.url.split("sqlite:///", 1)[-1] if self.url.startswith("sqlite:///") else self.url
            if path != ":memory:":
                d = os.path.dirname(os.path.abspath(path))
                os.makedirs(d, exist_ok=True)

            def f() -> sqlite3.Connection:
                c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA busy_timeout=5000")
                return c

            self._raw = await asyncio.to_thread(f)
        else:
            import asyncpg  # noqa: WPS433 (импорт только если нужен)

            dsn = self.url.replace("postgresql+asyncpg://", "postgresql://", 1)
            self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=30)

    async def close(self) -> None:
        if self._raw is not None:
            await asyncio.to_thread(self._raw.close)
            self._raw = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # -------- операции --------
    @asynccontextmanager
    async def tx(self) -> AsyncIterator[Any]:
        """Транзакция. Внутри нужно пользоваться только переданным объектом."""
        if self.kind == "sqlite":
            async with self._lock:
                c = _SqliteConn(self._raw)  # type: ignore[arg-type]
                await c.execute("BEGIN")
                try:
                    yield c
                except BaseException:
                    await c.execute("ROLLBACK")
                    raise
                else:
                    await c.execute("COMMIT")
                    self.dirty = True
        else:
            async with self._pool.acquire() as raw:
                async with raw.transaction():
                    yield _PgConn(raw)
                    self.dirty = True

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[Any]:
        if self.kind == "sqlite":
            async with self._lock:
                yield _SqliteConn(self._raw)  # type: ignore[arg-type]
        else:
            async with self._pool.acquire() as raw:
                yield _PgConn(raw)

    async def execute(self, sql: str, *params: Any, volatile: bool = False) -> int:
        async with self._conn() as c:
            n = await c.execute(sql, params)
        if not volatile:
            self.dirty = True
        return n

    async def insert(self, sql: str, *params: Any) -> int:
        async with self._conn() as c:
            n = await c.insert(sql, params)
        self.dirty = True
        return n

    async def fetchall(self, sql: str, *params: Any) -> list[dict]:
        async with self._conn() as c:
            return await c.fetchall(sql, params)

    async def fetchone(self, sql: str, *params: Any) -> dict | None:
        async with self._conn() as c:
            return await c.fetchone(sql, params)

    async def scalar(self, sql: str, *params: Any) -> Any:
        row = await self.fetchone(sql, *params)
        return next(iter(row.values())) if row else None
