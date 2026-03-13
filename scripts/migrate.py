"""Run SQL migrations in order."""
from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.db import Database


async def run_migrations() -> None:
    db = Database()
    await db.connect()

    migrations_dir = Path("migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration in migration_files:
        print(f"Applying: {migration.name}")
        await db.run_migration(migration)

    await db.commit()
    await db.close()
    print("All migrations applied.")


if __name__ == "__main__":
    asyncio.run(run_migrations())
