"""
Score repository — raw SQL data-access functions for the scores table.

Convention: every function takes a Database instance as its first
argument. No class needed; the module is the namespace.

Schema expected (run migration before use):
    CREATE TABLE scores (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        fast_score_total REAL,
        fast_score_breakdown TEXT,        -- JSON string
        fast_score_pass INTEGER,          -- boolean (0/1)
        deep_score_relevance REAL,
        deep_score_feasibility REAL,
        deep_score_profitability REAL,
        deep_score_win_probability REAL,
        deep_score_reasoning TEXT,
        deep_score_red_flags TEXT,        -- JSON string
        final_score REAL,
        recommendation TEXT,
        scored_at TEXT NOT NULL
    );
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from src.core.db import Database
from src.core.types import JobId
from src.models.score import CompositeScore, DeepScore, FastScore

logger = logging.getLogger(__name__)


def _score_to_row(score: CompositeScore) -> tuple:
    """Serialize a CompositeScore to a flat tuple for INSERT."""
    return (
        str(uuid.uuid4()),
        score.job_id,
        score.fast_score.total,
        json.dumps(score.fast_score.breakdown),
        1 if score.fast_score.pass_threshold else 0,
        score.deep_score.relevance,
        score.deep_score.feasibility,
        score.deep_score.profitability,
        score.deep_score.win_probability,
        score.deep_score.reasoning,
        json.dumps(score.deep_score.red_flags),
        score.final_score,
        score.recommendation,
        score.fast_score.scored_at.isoformat(),
    )


def _row_to_composite(row: dict) -> CompositeScore:
    """Deserialize a DB row dict back into a CompositeScore."""
    def _dt(val: str | None) -> datetime:
        if not val:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(val)

    job_id = JobId(row["job_id"])
    scored_at = _dt(row.get("scored_at"))

    fast_score = FastScore(
        job_id=job_id,
        total=float(row["fast_score_total"]),
        breakdown=json.loads(row.get("fast_score_breakdown") or "{}"),
        pass_threshold=bool(row["fast_score_pass"]),
        scored_at=scored_at,
    )

    deep_score = DeepScore(
        job_id=job_id,
        relevance=float(row["deep_score_relevance"]),
        feasibility=float(row["deep_score_feasibility"]),
        profitability=float(row["deep_score_profitability"]),
        win_probability=float(row["deep_score_win_probability"]),
        reasoning=row.get("deep_score_reasoning") or "",
        red_flags=json.loads(row.get("deep_score_red_flags") or "[]"),
        scored_at=scored_at,
    )

    return CompositeScore(
        job_id=job_id,
        fast_score=fast_score,
        deep_score=deep_score,
        final_score=float(row["final_score"]),
        recommendation=row.get("recommendation") or "skip",
    )


_INSERT_SQL = """
    INSERT INTO scores (
        id, job_id,
        fast_score_total, fast_score_breakdown, fast_score_pass,
        deep_score_relevance, deep_score_feasibility,
        deep_score_profitability, deep_score_win_probability,
        deep_score_reasoning, deep_score_red_flags,
        final_score, recommendation, scored_at
    ) VALUES (
        ?, ?,
        ?, ?, ?,
        ?, ?,
        ?, ?,
        ?, ?,
        ?, ?, ?
    )
    ON CONFLICT (id) DO NOTHING
"""


async def save_score(db: Database, score: CompositeScore) -> None:
    """
    Persist a CompositeScore to the database.

    Breakdown and red_flags are stored as JSON strings.
    """
    row = _score_to_row(score)
    await db.execute(_INSERT_SQL, row)
    await db.commit()
    logger.debug("Saved score for job %s (final=%.1f)", score.job_id, score.final_score)


async def get_score_by_job_id(db: Database, job_id: str) -> CompositeScore | None:
    """Retrieve the most recent CompositeScore for a given job ID."""
    row = await db.fetch_one(
        "SELECT * FROM scores WHERE job_id = ? ORDER BY scored_at DESC LIMIT 1",
        (job_id,),
    )
    return _row_to_composite(row) if row else None


async def list_scores(
    db: Database,
    recommendation: str | None = None,
    limit: int = 50,
) -> list[CompositeScore]:
    """
    Return CompositeScores ordered by final_score descending.

    Optionally filtered by recommendation (e.g., 'strong_pursue', 'pursue').
    """
    if recommendation is not None:
        rows = await db.fetch_all(
            "SELECT * FROM scores WHERE recommendation = ? ORDER BY final_score DESC LIMIT ?",
            (recommendation, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM scores ORDER BY final_score DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_composite(row) for row in rows]
