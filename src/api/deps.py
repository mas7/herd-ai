"""FastAPI dependency injection — database and config."""
from __future__ import annotations

from functools import lru_cache
from typing import AsyncGenerator

from fastapi import Depends

from src.core.config import HerdConfig, load_config
from src.core.db import Database


@lru_cache
def get_config() -> HerdConfig:
    return load_config()


# Module-level singleton — connected on startup via lifespan
_db: Database | None = None


def set_db(db: Database) -> None:
    global _db
    _db = db


async def get_db() -> AsyncGenerator[Database, None]:
    assert _db is not None, "Database not initialised — call set_db() in lifespan"
    yield _db
