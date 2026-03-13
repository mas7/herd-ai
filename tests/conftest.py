"""Shared test fixtures."""
from __future__ import annotations

import pytest

from src.core.db import Database
from src.core.events import InProcessEventBus


@pytest.fixture
async def db(tmp_path):
    """In-memory test database."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.run_migration("migrations/001_initial.sql")
    yield database
    await database.close()


@pytest.fixture
def event_bus():
    """Fresh event bus for each test."""
    return InProcessEventBus()
