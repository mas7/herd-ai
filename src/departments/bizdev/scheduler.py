"""
Event-driven scheduler for the BizDev department.

Subscribes to job_scored events. For each job that passed analyst scoring,
runs the two-step bid pipeline: rule-based pricing then LLM positioning.
Results are persisted to the bid_strategies table and emitted as BidDecided
or JobPassed events.

Lifecycle:
    scheduler = BizDevScheduler(event_bus, db, config, positioner)
    await scheduler.start()
    ...
    await scheduler.stop()
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from src.departments.bizdev.pricing import compute_bid_price
from src.models.bid import WinRecord
from src.models.bid import BidStrategy
from src.models.events import BidDecided, Event, JobPassed
from src.models.job import JobStatus

if TYPE_CHECKING:
    from src.core.config import HerdConfig
    from src.core.db import Database
    from src.core.events import EventBusProtocol
    from src.departments.bizdev.positioning import Positioner

logger = logging.getLogger(__name__)

_PASS_RECOMMENDATIONS = {"skip", "maybe"}  # maybe → manual review, not auto-bid


def _pricing_confidence(bid_amount: float, job_budget_max: float | None) -> float:
    """Score how competitive our bid is relative to the job's budget ceiling."""
    if job_budget_max is None:
        return 70.0
    ratio = bid_amount / job_budget_max
    if ratio <= 1.0:
        return 100.0
    if ratio <= 1.10:
        return 70.0
    return 50.0


def _compute_confidence(
    final_score: float,
    win_probability: float,
    bid_amount: float,
    job_budget_max: float | None,
) -> float:
    pricing_conf = _pricing_confidence(bid_amount, job_budget_max)
    return final_score * 0.5 + win_probability * 0.3 + pricing_conf * 0.2


def _urgency(final_score: float) -> str:
    if final_score >= 80:
        return "immediate"
    if final_score >= 60:
        return "normal"
    return "low"


class BizDevScheduler:
    """
    Event-driven scheduler that drives the bid strategy pipeline.

    Handles one job at a time, triggered by job_scored events.
    Each bid decision is fire-and-forget via asyncio.create_task so the
    event bus handler returns immediately without blocking.
    """

    def __init__(
        self,
        event_bus: EventBusProtocol,
        db: Database,
        config: HerdConfig,
        positioner: Positioner,
    ) -> None:
        self._event_bus = event_bus
        self._db = db
        self._config = config
        self._positioner = positioner
        self._running = False
        self._inflight: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Subscribe to job_scored events and begin processing."""
        if self._running:
            logger.warning("BizDevScheduler is already running")
            return
        self._running = True
        self._event_bus.subscribe("job_scored", self._on_job_scored)
        logger.info("BizDevScheduler started — subscribed to job_scored")

    async def stop(self) -> None:
        """Unsubscribe from events and wait for in-flight strategy tasks."""
        if not self._running:
            return
        self._running = False
        self._event_bus.unsubscribe("job_scored", self._on_job_scored)
        await asyncio.sleep(0)
        while self._inflight:
            logger.info(
                "BizDevScheduler stopping — waiting for %d in-flight tasks",
                len(self._inflight),
            )
            done, _ = await asyncio.wait(self._inflight)
            self._inflight -= done
            for task in done:
                if not task.cancelled():
                    task.exception()
        logger.info("BizDevScheduler stopped")

    async def _on_job_scored(self, event: Event) -> None:
        """Handle a job_scored event — enqueue bid decision as a background task."""
        job_id: str = event.payload.get("job_id", "")
        if not job_id:
            logger.warning("job_scored event missing job_id payload")
            return
        task = asyncio.create_task(
            self._decide_and_handle_errors(job_id),
            name=f"bizdev-decide-{job_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _decide_and_handle_errors(self, job_id: str) -> None:
        try:
            await self.decide_bid(job_id)
        except Exception:
            logger.exception("Unhandled error deciding bid for job %s", job_id)

    async def decide_bid(self, job_id: str) -> BidStrategy | None:
        """
        Full bid decision pipeline for a single job.

        Steps:
        1. Fetch job and score from DB.
        2. Check recommendation — pass immediately if score says skip.
        3. Compute rule-based bid price.
        4. If price not viable — pass with reason.
        5. Get LLM positioning angle.
        6. Build BidStrategy, compute confidence.
        7. Persist to bid_strategies table.
        8. Update job status.
        9. Emit BidDecided or JobPassed.
        """
        from src.repositories.bid_repo import get_win_history, save_bid_strategy
        from src.repositories.job_repo import get_job, update_job_status
        from src.repositories.score_repo import get_score_by_job_id

        job = await get_job(self._db, job_id)
        if job is None:
            logger.error("Cannot decide bid for job %s — not found in DB", job_id)
            return None

        score = await get_score_by_job_id(self._db, job_id)
        if score is None:
            logger.error("Cannot decide bid for job %s — score not found in DB", job_id)
            return None

        logger.info("Deciding bid for job %s: %s", job_id, job.title)

        # Pass low-scoring jobs immediately
        if score.recommendation in _PASS_RECOMMENDATIONS:
            strategy = BidStrategy(
                job_id=job.id,
                should_bid=False,
                confidence=score.final_score,
                reasoning=f"Analyst recommendation '{score.recommendation}' — not worth bidding.",
                pass_reason="low_analyst_score",
            )
            await save_bid_strategy(self._db, strategy)
            await update_job_status(self._db, job_id, JobStatus.PASSED.value)
            await self._event_bus.publish(
                JobPassed(payload={"job_id": job_id, "reason": "low_analyst_score"})
            )
            logger.info("Job %s passed (low analyst score)", job_id)
            return strategy

        # Fetch win history for pricing calibration
        win_history = await get_win_history(self._db, job.job_type.value)

        # Rule-based pricing
        bid_price = compute_bid_price(
            job=job,
            profile=self._config.user_profile,
            score=score,
            win_history=win_history,
        )

        if not bid_price.viable:
            strategy = BidStrategy(
                job_id=job.id,
                should_bid=False,
                confidence=20.0,
                reasoning=bid_price.reasoning,
                pass_reason="price_not_viable",
            )
            await save_bid_strategy(self._db, strategy)
            await update_job_status(self._db, job_id, JobStatus.PASSED.value)
            await self._event_bus.publish(
                JobPassed(payload={"job_id": job_id, "reason": "price_not_viable"})
            )
            logger.info("Job %s passed (price not viable: %s)", job_id, bid_price.reasoning)
            return strategy

        # LLM positioning
        angle = await self._positioner.get_angle(
            job=job,
            profile=self._config.user_profile,
            score=score,
            bid_price=bid_price,
        )

        # Compute confidence
        job_budget_max = (
            float(job.hourly_rate_max)
            if job.hourly_rate_max is not None
            else (float(job.budget_max) if job.budget_max is not None else None)
        )
        confidence = _compute_confidence(
            final_score=score.final_score,
            win_probability=score.deep_score.win_probability,
            bid_amount=bid_price.amount,
            job_budget_max=job_budget_max,
        )

        strategy = BidStrategy(
            job_id=job.id,
            should_bid=True,
            bid_type=bid_price.bid_type,  # type: ignore[arg-type]
            proposed_rate=Decimal(str(round(bid_price.amount, 2))),
            rate_range=(
                Decimal(str(bid_price.rate_range[0])),
                Decimal(str(bid_price.rate_range[1])),
            ),
            positioning_angle=angle,
            urgency=_urgency(score.final_score),  # type: ignore[arg-type]
            confidence=round(confidence, 1),
            reasoning=bid_price.reasoning,
        )

        await save_bid_strategy(self._db, strategy)
        await update_job_status(self._db, job_id, JobStatus.BID_DECIDED.value)
        await self._event_bus.publish(
            BidDecided(
                payload={
                    "job_id": job_id,
                    "bid_type": strategy.bid_type,
                    "proposed_rate": float(strategy.proposed_rate or 0),
                    "confidence": strategy.confidence,
                    "urgency": strategy.urgency,
                }
            )
        )
        logger.info(
            "Job %s bid decided: %s at %s (confidence=%.1f, urgency=%s)",
            job_id,
            strategy.bid_type,
            strategy.proposed_rate,
            strategy.confidence,
            strategy.urgency,
        )
        return strategy
