"""
Event-driven scheduler for the Analyst department.

Subscribes to job_discovered events and scores each job through the
two-stage pipeline: fast filter first, then LLM deep analysis for jobs
that pass. Results are persisted to the scores table and emitted as
JobScored or JobRejected events.

Lifecycle:
    scheduler = AnalystScheduler(event_bus, db, config, deep_scorer)
    await scheduler.start()
    ...
    await scheduler.stop()
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.departments.analyst.fast_score import compute_fast_score
from src.models.events import Event, JobRejected, JobScored
from src.models.job import JobStatus
from src.models.score import CompositeScore, DeepScore, FastScore

if TYPE_CHECKING:
    from src.core.config import HerdConfig
    from src.core.db import Database
    from src.core.events import EventBusProtocol
    from src.departments.analyst.deep_score import DeepScorer

logger = logging.getLogger(__name__)

_STRONG_PURSUE_THRESHOLD = 80.0
_PURSUE_THRESHOLD = 65.0
_MAYBE_THRESHOLD = 50.0


def _recommendation(final_score: float) -> str:
    if final_score >= _STRONG_PURSUE_THRESHOLD:
        return "strong_pursue"
    if final_score >= _PURSUE_THRESHOLD:
        return "pursue"
    if final_score >= _MAYBE_THRESHOLD:
        return "maybe"
    return "skip"


def _compute_final_score(fast_score: FastScore, deep_score: DeepScore) -> float:
    deep_avg = (
        deep_score.relevance
        + deep_score.feasibility
        + deep_score.profitability
        + deep_score.win_probability
    ) / 4.0
    return fast_score.total * 0.3 + deep_avg * 0.7


def _make_skip_deep_score(fast_score: FastScore) -> DeepScore:
    """Placeholder deep score when fast filter rejects a job."""
    return DeepScore(
        job_id=fast_score.job_id,
        relevance=0.0,
        feasibility=0.0,
        profitability=0.0,
        win_probability=0.0,
        reasoning="Job did not pass fast score threshold — deep analysis skipped.",
        red_flags=["Did not pass fast score threshold"],
    )


class AnalystScheduler:
    """
    Event-driven scheduler that drives the two-stage scoring pipeline.

    Handles one job at a time, triggered by job_discovered events.
    Each scoring run is fire-and-forget via asyncio.create_task so the
    event bus handler returns immediately without blocking.
    """

    def __init__(
        self,
        event_bus: EventBusProtocol,
        db: Database,
        config: HerdConfig,
        deep_scorer: DeepScorer,
    ) -> None:
        self._event_bus = event_bus
        self._db = db
        self._config = config
        self._deep_scorer = deep_scorer
        self._running = False
        self._inflight: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Subscribe to job_discovered events and begin processing."""
        if self._running:
            logger.warning("AnalystScheduler is already running")
            return
        self._running = True
        self._event_bus.subscribe("job_discovered", self._on_job_discovered)
        logger.info("AnalystScheduler started — subscribed to job_discovered")

    async def stop(self) -> None:
        """Unsubscribe from events and wait for in-flight scoring tasks."""
        self._running = False
        self._event_bus.unsubscribe("job_discovered", self._on_job_discovered)
        if self._inflight:
            logger.info(
                "AnalystScheduler stopping — waiting for %d in-flight tasks",
                len(self._inflight),
            )
            await asyncio.gather(*self._inflight, return_exceptions=True)
        logger.info("AnalystScheduler stopped")

    async def _on_job_discovered(self, event: Event) -> None:
        """Handle a job_discovered event — enqueue scoring as a background task."""
        if not self._running:
            return
        job_id: str = event.payload.get("job_id", "")
        if not job_id:
            logger.warning("job_discovered event missing job_id payload")
            return
        task = asyncio.create_task(
            self._score_and_handle_errors(job_id),
            name=f"analyst-score-{job_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _score_and_handle_errors(self, job_id: str) -> None:
        try:
            await self.score_job(job_id)
        except Exception:
            logger.exception("Unhandled error scoring job %s", job_id)

    async def score_job(self, job_id: str) -> CompositeScore | None:
        """
        Full scoring pipeline for a single job.

        Steps:
        1. Fetch job from DB.
        2. Compute fast score.
        3. If pass_threshold: compute deep score.
        4. Build CompositeScore with recommendation.
        5. Persist to scores table.
        6. Update job status.
        7. Emit JobScored or JobRejected.
        """
        from src.repositories.job_repo import get_job, update_job_status
        from src.repositories.score_repo import save_score

        job = await get_job(self._db, job_id)
        if job is None:
            logger.error("Cannot score job %s — not found in DB", job_id)
            return None

        logger.info("Scoring job %s: %s", job_id, job.title)

        scoring_cfg = self._config.scoring
        fast_score = compute_fast_score(
            job=job,
            profile=self._config.user_profile,
            weights=scoring_cfg.fast_score.weights,
            threshold=scoring_cfg.fast_score.threshold,
        )

        if not fast_score.pass_threshold:
            logger.info(
                "Job %s failed fast score (%.1f < %.1f) — rejected",
                job_id,
                fast_score.total,
                scoring_cfg.fast_score.threshold,
            )
            deep_score = _make_skip_deep_score(fast_score)
            final_score = fast_score.total
            recommendation = "skip"
        else:
            deep_score = await self._deep_scorer.score(
                job=job, profile=self._config.user_profile
            )
            final_score = _compute_final_score(fast_score, deep_score)
            recommendation = _recommendation(final_score)

        composite = CompositeScore(
            job_id=job.id,
            fast_score=fast_score,
            deep_score=deep_score,
            final_score=final_score,
            recommendation=recommendation,
        )

        try:
            await save_score(self._db, composite)
        except Exception:
            logger.exception("Failed to persist score for job %s", job_id)
            return None

        new_status = (
            JobStatus.REJECTED if not fast_score.pass_threshold else JobStatus.SCORED
        )
        await update_job_status(self._db, job_id, new_status.value)

        if not fast_score.pass_threshold:
            event: Event = JobRejected(
                payload={
                    "job_id": job_id,
                    "fast_score": fast_score.total,
                    "reason": "below_fast_threshold",
                },
            )
        else:
            event = JobScored(
                payload={
                    "job_id": job_id,
                    "final_score": final_score,
                    "recommendation": recommendation,
                },
            )

        await self._event_bus.publish(event)
        logger.info(
            "Job %s scored: final=%.1f recommendation=%s",
            job_id,
            final_score,
            recommendation,
        )
        return composite
