"""Proposal queue endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.core.db import Database

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("")
async def list_proposals(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return proposals joined with job title, ordered by created_at descending."""
    if status:
        rows = await db.fetch_all(
            """
            SELECT p.*, j.title as job_title, j.client_country
            FROM proposals p
            JOIN jobs j ON j.id = p.job_id
            WHERE p.status = ?
            ORDER BY p.created_at DESC LIMIT ?
            """,
            (status, limit),
        )
    else:
        rows = await db.fetch_all(
            """
            SELECT p.*, j.title as job_title, j.client_country
            FROM proposals p
            JOIN jobs j ON j.id = p.job_id
            ORDER BY p.created_at DESC LIMIT ?
            """,
            (limit,),
        )
    return rows


@router.get("/counts")
async def proposal_counts(db: Database = Depends(get_db)) -> dict[str, int]:
    rows = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM proposals GROUP BY status"
    )
    return {row["status"]: row["count"] for row in rows}


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: str, db: Database = Depends(get_db)
) -> dict[str, Any] | None:
    return await db.fetch_one(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    )
