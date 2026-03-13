"""
Event-driven scheduler for the Content department.

Subscribes to bid_decided events. For each job where BizDev decided to
bid, retrieves all context, generates a proposal via the ProposalWriter,
persists it, and emits a ProposalDrafted event.

Lifecycle:
    scheduler = ContentScheduler(event_bus, db, config, writer)
    await scheduler.start()
    ...
    await scheduler.stop()
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.models.events import Event, ProposalDrafted
from src.models.job import JobStatus

if TYPE_CHECKING:
    from src.core.config import HerdConfig
    from src.core.db import Database
    from src.core.events import EventBusProtocol
    from src.departments.content.writer import ProposalWriter

logger = logging.getLogger(__name__)


class ContentScheduler:
    """
    Event-driven scheduler that drives the proposal generation pipeline.

    Handles one bid at a time, triggered by bid_decided events.
    Each proposal generation is fire-and-forget via asyncio.create_task
    so the event bus handler returns immediately without blocking.
    """

    def __init__(
        self,
        event_bus: "EventBusProtocol",
        db: "Database",
        config: "HerdConfig",
        writer: "ProposalWriter",
    ) -> None:
        self._event_bus = event_bus
        self._db = db
        self._config = config
        self._writer = writer
        self._running = False
        self._inflight: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Subscribe to bid_decided events and begin processing."""
        if self._running:
            logger.warning("ContentScheduler is already running")
            return
        self._running = True
        self._event_bus.subscribe("bid_decided", self._on_bid_decided)
        logger.info("ContentScheduler started — subscribed to bid_decided")

    async def stop(self) -> None:
        """Unsubscribe from events and wait for in-flight generation tasks."""
        if not self._running:
            return
        self._running = False
        self._event_bus.unsubscribe("bid_decided", self._on_bid_decided)
        await asyncio.sleep(0)
        while self._inflight:
            logger.info(
                "ContentScheduler stopping — waiting for %d in-flight tasks",
                len(self._inflight),
            )
            done, _ = await asyncio.wait(self._inflight)
            self._inflight -= done
            for task in done:
                if not task.cancelled():
                    task.exception()
        logger.info("ContentScheduler stopped")

    async def _on_bid_decided(self, event: Event) -> None:
        """Handle a bid_decided event — enqueue proposal generation as a background task."""
        job_id: str = event.payload.get("job_id", "")
        if not job_id:
            logger.warning("bid_decided event missing job_id payload")
            return
        task = asyncio.create_task(
            self._draft_and_handle_errors(job_id),
            name=f"content-draft-{job_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _draft_and_handle_errors(self, job_id: str) -> None:
        try:
            await self.draft_proposal(job_id)
        except Exception:
            logger.exception("Unhandled error drafting proposal for job %s", job_id)

    async def draft_proposal(self, job_id: str) -> None:
        """
        Full proposal generation pipeline for a single job.

        Steps:
        1. Fetch job, score, and bid strategy from DB.
        2. Verify bid strategy says should_bid=True.
        3. Generate proposal via ProposalWriter (RAG + LLM).
        4. Persist ProposalDraft to proposals table.
        5. Update job status to PROPOSAL_DRAFTED.
        6. Emit ProposalDrafted event.
        """
        from src.repositories.bid_repo import get_bid_strategy
        from src.repositories.job_repo import get_job, update_job_status
        from src.repositories.proposal_repo import save_proposal
        from src.repositories.score_repo import get_score_by_job_id

        job = await get_job(self._db, job_id)
        if job is None:
            logger.error("Cannot draft proposal for job %s — not found in DB", job_id)
            return

        score = await get_score_by_job_id(self._db, job_id)
        if score is None:
            logger.error("Cannot draft proposal for job %s — score not found", job_id)
            return

        strategy = await get_bid_strategy(self._db, job_id)
        if strategy is None:
            logger.error("Cannot draft proposal for job %s — bid strategy not found", job_id)
            return

        if not strategy.should_bid:
            logger.info("Job %s bid strategy is pass — skipping proposal generation", job_id)
            return

        logger.info("Drafting proposal for job %s: %s", job_id, job.title)

        draft = await self._writer.write(
            job=job,
            profile=self._config.user_profile,
            strategy=strategy,
            score=score,
        )

        await save_proposal(self._db, draft)
        await update_job_status(self._db, job_id, JobStatus.PROPOSAL_DRAFTED.value)

        await self._event_bus.publish(
            ProposalDrafted(
                payload={
                    "job_id": job_id,
                    "proposal_id": str(draft.id),
                    "confidence": draft.confidence,
                }
            )
        )
        logger.info(
            "Proposal drafted for job %s (proposal_id=%s, confidence=%.1f)",
            job_id,
            draft.id,
            draft.confidence,
        )
