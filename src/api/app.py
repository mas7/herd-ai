"""Herd AI — FastAPI application."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.deps import set_db
from src.api.routes import dashboard, jobs, proposals
from src.core.config import load_config
from src.core.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = load_config()
    db_path = config.database.url.replace("sqlite+aiosqlite:///", "")
    db = Database(db_path)
    await db.connect()

    # Run all migrations on startup
    migrations_dir = Path("migrations")
    if migrations_dir.exists():
        for migration in sorted(migrations_dir.glob("*.sql")):
            await db.run_migration(migration)

    set_db(db)
    yield
    await db.close()


app = FastAPI(
    title="Herd AI",
    description="Autonomous freelancing agency — API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/api")
app.include_router(proposals.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
