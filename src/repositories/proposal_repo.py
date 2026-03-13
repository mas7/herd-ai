"""
Proposal repository — raw SQL data-access for the proposals table.

Convention: every function takes a Database instance as its first argument.

Schema (created by migration 001_initial.sql):
    CREATE TABLE proposals (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        platform TEXT NOT NULL,
        platform_job_id TEXT NOT NULL,
        platform_proposal_id TEXT,
        bid_type TEXT NOT NULL,
        bid_amount REAL NOT NULL,
        cover_letter TEXT NOT NULL,
        questions_answers TEXT,
        confidence REAL,
        positioning_angle TEXT,
        experiment_variants TEXT,
        connects_cost REAL,
        status TEXT NOT NULL DEFAULT 'drafted',
        created_at TEXT NOT NULL,
        submitted_at TEXT,
        outcome_at TEXT,
        error TEXT
    );
"""
from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal

from src.core.db import Database
from src.core.types import ProposalId
from src.models.proposal import ProposalDraft, ProposalResult, ProposalStatus

logger = logging.getLogger(__name__)

_INSERT_SQL = """
    INSERT INTO proposals (
        id, job_id, platform, platform_job_id,
        bid_type, bid_amount, cover_letter, questions_answers,
        confidence, positioning_angle, experiment_variants,
        connects_cost, status, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (id) DO UPDATE SET
        bid_type = excluded.bid_type,
        bid_amount = excluded.bid_amount,
        cover_letter = excluded.cover_letter,
        questions_answers = excluded.questions_answers,
        confidence = excluded.confidence,
        positioning_angle = excluded.positioning_angle,
        experiment_variants = excluded.experiment_variants,
        connects_cost = excluded.connects_cost,
        status = excluded.status,
        created_at = excluded.created_at
"""


def _draft_to_row(draft: ProposalDraft) -> tuple:
    return (
        str(draft.id),
        str(draft.job_id),
        draft.platform,
        draft.platform_job_id,
        draft.bid_type,
        float(draft.bid_amount),
        draft.cover_letter,
        json.dumps(draft.questions_answers) if draft.questions_answers else None,
        draft.confidence,
        draft.positioning_angle,
        json.dumps(draft.experiment_variants) if draft.experiment_variants else None,
        draft.connects_cost,
        ProposalStatus.DRAFTED.value,
        draft.created_at.isoformat(),
    )


def _row_to_draft(row: dict) -> ProposalDraft:
    from datetime import datetime, timezone

    def _dt(val: str | None) -> datetime:
        if not val:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(val)

    qa_raw = row.get("questions_answers")
    qa: dict[str, str] = json.loads(qa_raw) if qa_raw else {}

    ev_raw = row.get("experiment_variants")
    ev: dict[str, str] = json.loads(ev_raw) if ev_raw else {}

    bid_amount = row.get("bid_amount", 0.0)

    return ProposalDraft(
        id=ProposalId(row["id"]),
        job_id=row["job_id"],
        platform=row["platform"],
        platform_job_id=row["platform_job_id"],
        bid_type=row.get("bid_type", "hourly"),
        bid_amount=Decimal(str(bid_amount)),
        cover_letter=row.get("cover_letter", ""),
        questions_answers=qa,
        confidence=float(row.get("confidence") or 0.0),
        positioning_angle=row.get("positioning_angle") or "",
        experiment_variants=ev,
        connects_cost=row.get("connects_cost"),
        created_at=_dt(row.get("created_at")),
    )


async def save_proposal(db: Database, draft: ProposalDraft) -> None:
    """
    Persist a ProposalDraft to the database.

    Uses INSERT … ON CONFLICT DO UPDATE so that re-running the pipeline
    for the same draft ID overwrites the previous record.
    """
    row = _draft_to_row(draft)
    await db.execute(_INSERT_SQL, row)
    await db.commit()
    logger.debug("Saved proposal %s for job %s", draft.id, draft.job_id)


async def get_proposal(db: Database, proposal_id: str) -> ProposalDraft | None:
    """Retrieve a ProposalDraft by proposal ID."""
    row = await db.fetch_one(
        "SELECT * FROM proposals WHERE id = ?",
        (proposal_id,),
    )
    return _row_to_draft(row) if row else None


async def get_proposal_by_job(db: Database, job_id: str) -> ProposalDraft | None:
    """Retrieve the most recent ProposalDraft for a given job ID."""
    row = await db.fetch_one(
        "SELECT * FROM proposals WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
        (job_id,),
    )
    return _row_to_draft(row) if row else None


async def list_proposals(
    db: Database,
    status: str | None = None,
    limit: int = 50,
) -> list[ProposalDraft]:
    """
    Return ProposalDrafts ordered by created_at descending.

    Optionally filtered by status (e.g. 'drafted', 'submitted', 'won').
    """
    if status is not None:
        rows = await db.fetch_all(
            "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_draft(row) for row in rows]


async def update_proposal_status(
    db: Database,
    proposal_id: str,
    status: str,
    platform_proposal_id: str | None = None,
    submitted_at: str | None = None,
    error: str | None = None,
) -> None:
    """Update the status (and optional submission fields) of a proposal."""
    await db.execute(
        """
        UPDATE proposals
        SET status = ?,
            platform_proposal_id = COALESCE(?, platform_proposal_id),
            submitted_at = COALESCE(?, submitted_at),
            error = COALESCE(?, error)
        WHERE id = ?
        """,
        (status, platform_proposal_id, submitted_at, error, proposal_id),
    )
    await db.commit()
    logger.debug("Updated proposal %s status → %s", proposal_id, status)


async def update_proposal_outcome(
    db: Database,
    proposal_id: str,
    outcome: str,
    outcome_at: str,
) -> None:
    """Record the final outcome (won/lost/no_response) of a submitted proposal."""
    await db.execute(
        "UPDATE proposals SET status = ?, outcome_at = ? WHERE id = ?",
        (outcome, outcome_at, proposal_id),
    )
    await db.commit()
    logger.debug("Updated proposal %s outcome → %s", proposal_id, outcome)
