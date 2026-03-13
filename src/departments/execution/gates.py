"""
Safety gates for Execution department.

Each gate is a single-responsibility callable that returns a GateResult.
Gates are evaluated in order; the first BLOCK stops the pipeline.

Gate evaluation order:
    1. ConfidenceGate  — cheapest, no DB I/O
    2. DailyCapGate    — one COUNT query
    3. SpendLimitGate  — one SUM query
    4. HumanApprovalGate — status transition, blocks until human acts via API
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from src.core.config import SafetyConfig
    from src.core.db import Database
    from src.models.proposal import ProposalDraft

logger = logging.getLogger(__name__)


class GateVerdict(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    PENDING = "pending"  # human review — not a hard block, but pauses auto-flow


class GateResult(BaseModel):
    """Outcome of a single safety gate evaluation."""

    model_config = {"frozen": True}

    gate: str
    verdict: GateVerdict
    reason: str


# ── Individual Gates ───────────────────────────────────────────────────────


class ConfidenceGate:
    """
    Block proposals whose LLM confidence score is below the configured threshold.

    This is the cheapest gate (no I/O) so it runs first.
    """

    def __init__(self, safety: "SafetyConfig") -> None:
        self._threshold = safety.min_confidence_auto_submit

    def evaluate(self, draft: "ProposalDraft") -> GateResult:
        if draft.confidence >= self._threshold:
            return GateResult(
                gate="confidence",
                verdict=GateVerdict.PASS,
                reason=f"confidence={draft.confidence:.2f} >= threshold={self._threshold:.2f}",
            )
        return GateResult(
            gate="confidence",
            verdict=GateVerdict.BLOCK,
            reason=(
                f"confidence={draft.confidence:.2f} below threshold={self._threshold:.2f}"
            ),
        )


class DailyCapGate:
    """
    Block submission when today's submitted proposal count hits the daily cap.
    """

    def __init__(self, safety: "SafetyConfig") -> None:
        self._cap = safety.daily_submission_cap

    async def evaluate(self, db: "Database") -> GateResult:
        today = datetime.now(timezone.utc).date().isoformat()
        row = await db.fetch_one(
            """
            SELECT COUNT(*) as count FROM proposals
            WHERE status = 'submitted'
              AND DATE(submitted_at) = ?
            """,
            (today,),
        )
        count = row["count"] if row else 0
        if count < self._cap:
            return GateResult(
                gate="daily_cap",
                verdict=GateVerdict.PASS,
                reason=f"submissions today={count} < cap={self._cap}",
            )
        return GateResult(
            gate="daily_cap",
            verdict=GateVerdict.BLOCK,
            reason=f"daily cap reached: {count}/{self._cap} submissions today",
        )


class SpendLimitGate:
    """
    Block when today's connects spend exceeds the daily USD spend cap.

    Connects cost is stored in proposals.connects_cost.
    If connects_cost is NULL for a proposal, it is treated as zero.
    """

    def __init__(self, safety: "SafetyConfig") -> None:
        self._limit = safety.daily_spend_cap_usd

    async def evaluate(self, db: "Database") -> GateResult:
        today = datetime.now(timezone.utc).date().isoformat()
        row = await db.fetch_one(
            """
            SELECT COALESCE(SUM(connects_cost), 0.0) as total FROM proposals
            WHERE status = 'submitted'
              AND DATE(submitted_at) = ?
            """,
            (today,),
        )
        total = float(row["total"]) if row else 0.0
        if total < self._limit:
            return GateResult(
                gate="spend_limit",
                verdict=GateVerdict.PASS,
                reason=f"spend today=${total:.2f} < limit=${self._limit:.2f}",
            )
        return GateResult(
            gate="spend_limit",
            verdict=GateVerdict.BLOCK,
            reason=f"daily spend limit reached: ${total:.2f} >= ${self._limit:.2f}",
        )


class HumanApprovalGate:
    """
    Route proposals to pending_review when human-in-the-loop is enabled.

    Returns PENDING — the proposal is not blocked forever, but auto-submission
    is halted. A human must call POST /api/proposals/{id}/approve to resume,
    or POST /api/proposals/{id}/reject to discard.
    """

    def __init__(self, safety: "SafetyConfig") -> None:
        self._enabled = safety.human_in_the_loop

    def evaluate(self) -> GateResult:
        if not self._enabled:
            return GateResult(
                gate="human_approval",
                verdict=GateVerdict.PASS,
                reason="human_in_the_loop disabled — auto-submitting",
            )
        return GateResult(
            gate="human_approval",
            verdict=GateVerdict.PENDING,
            reason="human_in_the_loop enabled — routed to pending_review queue",
        )


# ── Gate Pipeline ──────────────────────────────────────────────────────────


class GatePipeline:
    """
    Runs all gates in order and returns the final aggregated result.

    Short-circuits on the first BLOCK. PENDING stops auto-submission
    but does not trigger a ProposalBlocked event — it's a soft pause.
    """

    def __init__(self, safety: "SafetyConfig") -> None:
        self._confidence = ConfidenceGate(safety)
        self._daily_cap = DailyCapGate(safety)
        self._spend = SpendLimitGate(safety)
        self._human = HumanApprovalGate(safety)

    async def run(
        self, draft: "ProposalDraft", db: "Database"
    ) -> list[GateResult]:
        """
        Evaluate all gates and return the list of results.

        The caller checks the last result's verdict to decide what to do.
        Evaluation stops on the first BLOCK.
        """
        results: list[GateResult] = []

        # 1. Confidence (sync — no I/O)
        r = self._confidence.evaluate(draft)
        results.append(r)
        if r.verdict == GateVerdict.BLOCK:
            logger.info(
                "Gate BLOCKED [%s]: %s — proposal %s",
                r.gate, r.reason, draft.id,
            )
            return results

        # 2. Daily cap (async)
        r = await self._daily_cap.evaluate(db)
        results.append(r)
        if r.verdict == GateVerdict.BLOCK:
            logger.info(
                "Gate BLOCKED [%s]: %s — proposal %s",
                r.gate, r.reason, draft.id,
            )
            return results

        # 3. Spend limit (async)
        r = await self._spend.evaluate(db)
        results.append(r)
        if r.verdict == GateVerdict.BLOCK:
            logger.info(
                "Gate BLOCKED [%s]: %s — proposal %s",
                r.gate, r.reason, draft.id,
            )
            return results

        # 4. Human approval (sync — just config check)
        r = self._human.evaluate()
        results.append(r)
        logger.info(
            "Gate [%s] %s: %s — proposal %s",
            r.gate, r.verdict, r.reason, draft.id,
        )
        return results
