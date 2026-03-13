"""
Bid strategy repository — raw SQL data-access for the bid_strategies table.

Convention: every function takes a Database instance as its first argument.

Schema expected (run migration 002 before use):
    CREATE TABLE bid_strategies (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        decision TEXT NOT NULL,
        bid_type TEXT,
        bid_amount REAL,
        positioning_angle TEXT,
        confidence REAL NOT NULL,
        reasoning TEXT NOT NULL,
        pass_reason TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (job_id)
    );
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal

from src.core.db import Database
from src.core.types import JobId
from src.models.bid import BidStrategy, WinRecord

logger = logging.getLogger(__name__)

_INSERT_SQL = """
    INSERT INTO bid_strategies (
        id, job_id, decision, bid_type, bid_amount,
        rate_floor, rate_ceil, urgency,
        positioning_angle, confidence, reasoning, pass_reason, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (job_id) DO UPDATE SET
        decision = excluded.decision,
        bid_type = excluded.bid_type,
        bid_amount = excluded.bid_amount,
        rate_floor = excluded.rate_floor,
        rate_ceil = excluded.rate_ceil,
        urgency = excluded.urgency,
        positioning_angle = excluded.positioning_angle,
        confidence = excluded.confidence,
        reasoning = excluded.reasoning,
        pass_reason = excluded.pass_reason,
        created_at = excluded.created_at
"""


def _strategy_to_row(strategy: BidStrategy) -> tuple:
    rate_floor = (
        float(strategy.rate_range[0]) if strategy.rate_range is not None else None
    )
    rate_ceil = (
        float(strategy.rate_range[1]) if strategy.rate_range is not None else None
    )
    return (
        str(uuid.uuid4()),
        strategy.job_id,
        "bid" if strategy.should_bid else "pass",
        strategy.bid_type,
        float(strategy.proposed_rate) if strategy.proposed_rate is not None else None,
        rate_floor,
        rate_ceil,
        strategy.urgency,
        strategy.positioning_angle,
        strategy.confidence,
        strategy.reasoning,
        strategy.pass_reason,
        strategy.created_at.isoformat(),
    )


def _row_to_strategy(row: dict) -> BidStrategy:
    from datetime import datetime, timezone

    def _dt(val: str | None) -> datetime:
        if not val:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(val)

    decision = row.get("decision", "pass")
    should_bid = decision == "bid"
    proposed_rate = row.get("bid_amount")
    bid_type = row.get("bid_type")
    rate_floor = row.get("rate_floor")
    rate_ceil = row.get("rate_ceil")
    rate_range = (
        (Decimal(str(rate_floor)), Decimal(str(rate_ceil)))
        if rate_floor is not None and rate_ceil is not None
        else None
    )

    return BidStrategy(
        job_id=JobId(row["job_id"]),
        should_bid=should_bid,
        bid_type=bid_type,  # type: ignore[arg-type]
        proposed_rate=Decimal(str(proposed_rate)) if proposed_rate is not None else None,
        rate_range=rate_range,
        positioning_angle=row.get("positioning_angle"),
        urgency=row.get("urgency"),  # type: ignore[arg-type]
        confidence=float(row["confidence"]),
        reasoning=row.get("reasoning") or "",
        pass_reason=row.get("pass_reason"),
        created_at=_dt(row.get("created_at")),
    )


async def save_bid_strategy(db: Database, strategy: BidStrategy) -> None:
    """
    Persist a BidStrategy to the database.

    Uses INSERT … ON CONFLICT DO UPDATE so that re-running the pipeline
    for the same job overwrites the previous strategy.
    """
    row = _strategy_to_row(strategy)
    await db.execute(_INSERT_SQL, row)
    await db.commit()
    logger.debug(
        "Saved bid strategy for job %s (should_bid=%s)",
        strategy.job_id,
        strategy.should_bid,
    )


async def get_bid_strategy(db: Database, job_id: str) -> BidStrategy | None:
    """Retrieve the most recent BidStrategy for a given job ID."""
    row = await db.fetch_one(
        "SELECT * FROM bid_strategies WHERE job_id = ?",
        (job_id,),
    )
    return _row_to_strategy(row) if row else None


async def list_bid_strategies(
    db: Database,
    decision: str | None = None,
    limit: int = 50,
) -> list[BidStrategy]:
    """
    Return BidStrategies ordered by created_at descending.

    Optionally filtered by decision ('bid' or 'pass').
    """
    if decision is not None:
        rows = await db.fetch_all(
            "SELECT * FROM bid_strategies WHERE decision = ? ORDER BY created_at DESC LIMIT ?",
            (decision, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM bid_strategies ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_strategy(row) for row in rows]


_WIN_SQL = """
    SELECT p.bid_amount, j.job_type, 1 AS was_won
    FROM proposals p
    JOIN jobs j ON j.id = p.job_id
    WHERE j.job_type = ?
      AND p.status = 'won'
      AND p.bid_amount IS NOT NULL
    ORDER BY p.created_at DESC
    LIMIT 50
"""

_LOSS_SQL = """
    SELECT p.bid_amount, j.job_type, 0 AS was_won
    FROM proposals p
    JOIN jobs j ON j.id = p.job_id
    WHERE j.job_type = ?
      AND p.status = 'lost'
      AND p.bid_amount IS NOT NULL
    ORDER BY p.created_at DESC
    LIMIT 50
"""


async def get_win_history(db: Database, job_type: str) -> list[WinRecord]:
    """
    Retrieve historical bid outcomes from the proposals table.

    Fetches up to 50 wins and 50 losses independently so that a long recent
    loss streak cannot crowd out winning bids from the anchor sample.
    """
    won_rows, lost_rows = await asyncio.gather(
        db.fetch_all(_WIN_SQL, (job_type,)),
        db.fetch_all(_LOSS_SQL, (job_type,)),
    )
    rows = [*won_rows, *lost_rows]
    return [
        WinRecord(
            bid_amount=float(row["bid_amount"]),
            job_type=row["job_type"],
            was_won=bool(row["was_won"]),
        )
        for row in rows
    ]
