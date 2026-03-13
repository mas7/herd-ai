"""Dashboard summary endpoint — single request for the overview panel."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.api.deps import get_db
from src.core.db import Database

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(db: Database = Depends(get_db)) -> dict[str, Any]:
    """
    Aggregated snapshot of pipeline health.

    Returns counts, recent activity, and score distribution in one call
    so the dashboard can render without waterfall requests.
    """
    job_counts_rows = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
    )
    job_counts = {row["status"]: row["count"] for row in job_counts_rows}
    total_jobs = sum(job_counts.values())

    proposal_counts_rows = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM proposals GROUP BY status"
    )
    proposal_counts = {row["status"]: row["count"] for row in proposal_counts_rows}

    bid_counts_rows = await db.fetch_all(
        "SELECT decision, COUNT(*) as count FROM bid_strategies GROUP BY decision"
    )
    bid_counts = {row["decision"]: row["count"] for row in bid_counts_rows}

    # Score distribution buckets
    score_dist = await db.fetch_all(
        """
        SELECT
            CASE
                WHEN final_score >= 80 THEN 'strong_pursue'
                WHEN final_score >= 65 THEN 'pursue'
                WHEN final_score >= 50 THEN 'maybe'
                ELSE 'skip'
            END as bucket,
            COUNT(*) as count
        FROM scores
        GROUP BY bucket
        """
    )

    # Recent 10 jobs with their pipeline stage
    recent_jobs = await db.fetch_all(
        """
        SELECT j.id, j.title, j.status, j.platform, j.posted_at, j.discovered_at,
               s.final_score, s.recommendation,
               b.decision, b.bid_amount, b.confidence as bid_confidence
        FROM jobs j
        LEFT JOIN scores s ON s.job_id = j.id
        LEFT JOIN bid_strategies b ON b.job_id = j.id
        ORDER BY j.discovered_at DESC
        LIMIT 10
        """
    )

    # Win rate (proposals with known outcomes)
    win_stats = await db.fetch_one(
        """
        SELECT
            COUNT(*) as total,
            COALESCE(SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END), 0) as won,
            COALESCE(SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END), 0) as lost,
            COALESCE(SUM(CASE WHEN status = 'no_response' THEN 1 ELSE 0 END), 0) as no_response
        FROM proposals
        WHERE status IN ('won', 'lost', 'no_response')
        """
    )

    # Average scores
    avg_scores = await db.fetch_one(
        """
        SELECT
            AVG(final_score) as avg_final_score,
            AVG(deep_score_win_probability) as avg_win_probability,
            AVG(deep_score_relevance) as avg_relevance
        FROM scores
        """
    )

    return {
        "totals": {
            "jobs": total_jobs,
            "scored": job_counts.get("scored", 0),
            "rejected": job_counts.get("rejected", 0),
            "bid_decided": job_counts.get("bid_decided", 0),
            "proposal_drafted": job_counts.get("proposal_drafted", 0),
            "passed": job_counts.get("passed", 0),
        },
        "job_counts": job_counts,
        "proposal_counts": proposal_counts,
        "bid_counts": bid_counts,
        "score_distribution": {row["bucket"]: row["count"] for row in score_dist},
        "recent_jobs": recent_jobs,
        "win_stats": win_stats or {"total": 0, "won": 0, "lost": 0, "no_response": 0},
        "avg_scores": avg_scores or {
            "avg_final_score": None,
            "avg_win_probability": None,
            "avg_relevance": None,
        },
    }


@router.get("/pipeline")
async def pipeline_health(db: Database = Depends(get_db)) -> dict[str, Any]:
    """Pipeline funnel — how many jobs pass each stage."""
    row = await db.fetch_one(
        """
        SELECT
            COUNT(*) as discovered,
            COALESCE(SUM(CASE WHEN status != 'discovered' AND status != 'rejected' THEN 1 ELSE 0 END), 0) as passed_fast,
            COALESCE(SUM(CASE WHEN status IN ('scored','bid_decided','proposal_drafted','proposal_submitted','won','lost') THEN 1 ELSE 0 END), 0) as deep_scored,
            COALESCE(SUM(CASE WHEN status IN ('bid_decided','proposal_drafted','proposal_submitted','won','lost') THEN 1 ELSE 0 END), 0) as bid_decided,
            COALESCE(SUM(CASE WHEN status IN ('proposal_drafted','proposal_submitted','won','lost') THEN 1 ELSE 0 END), 0) as proposed,
            COALESCE(SUM(CASE WHEN status IN ('proposal_submitted','won','lost') THEN 1 ELSE 0 END), 0) as submitted,
            COALESCE(SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END), 0) as won
        FROM jobs
        """
    )
    return row or {}
