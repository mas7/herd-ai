"""Database connection pool and raw SQL executor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    """Thin async SQLite wrapper. No ORM. Raw SQL only."""

    def __init__(self, db_path: str = "./data/herd.db") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> aiosqlite.Cursor:
        assert self._conn is not None, "Database not connected"
        return await self._conn.execute(sql, params)

    async def execute_many(
        self, sql: str, params_list: list[tuple[Any, ...]]
    ) -> None:
        assert self._conn is not None, "Database not connected"
        await self._conn.executemany(sql, params_list)

    async def fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        assert self._conn is not None, "Database not connected"
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        assert self._conn is not None, "Database not connected"
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def commit(self) -> None:
        assert self._conn is not None, "Database not connected"
        await self._conn.commit()

    async def run_migration(self, migration_path: str | Path) -> None:
        """Execute a SQL migration file."""
        path = Path(migration_path)
        sql = path.read_text()
        assert self._conn is not None, "Database not connected"
        await self._conn.executescript(sql)
        logger.info("Migration applied: %s", path.name)
