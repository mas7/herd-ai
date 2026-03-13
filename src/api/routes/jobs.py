"""Job feed endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.core.db import Database

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return jobs ordered by discovered_at descending."""
    if status:
        rows = await db.fetch_all(
            "SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT ?",
            (limit,),
        )
    return rows


@router.get("/counts")
async def job_counts(db: Database = Depends(get_db)) -> dict[str, int]:
    """Return per-status job counts."""
    rows = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
    )
    return {row["status"]: row["count"] for row in rows}


@router.get("/{job_id}")
async def get_job(job_id: str, db: Database = Depends(get_db)) -> dict[str, Any] | None:
    return await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))


@router.get("/{job_id}/score")
async def get_job_score(job_id: str, db: Database = Depends(get_db)) -> dict[str, Any] | None:
    return await db.fetch_one(
        "SELECT * FROM scores WHERE job_id = ?", (job_id,)
    )


@router.get("/{job_id}/bid")
async def get_job_bid(job_id: str, db: Database = Depends(get_db)) -> dict[str, Any] | None:
    return await db.fetch_one(
        "SELECT * FROM bid_strategies WHERE job_id = ?", (job_id,)
    )


@router.get("/{job_id}/proposal")
async def get_job_proposal(job_id: str, db: Database = Depends(get_db)) -> dict[str, Any] | None:
    return await db.fetch_one(
        "SELECT * FROM proposals WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
        (job_id,),
    )
