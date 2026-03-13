"""
Event-driven scheduler for the Execution department.

Subscribes to proposal_drafted events. For each drafted proposal,
runs the safety gate pipeline and either:
  - AUTO-SUBMITS: all gates pass → submit via platform, emit ProposalSubmitted
  - PENDING REVIEW: human gate routes to pending_review → emit ProposalBlocked
  - BLOCKS: a hard gate fires → emit ProposalBlocked with reason

Human approval flow:
    POST /api/proposals/{id}/approve → update DB status → calls submit_proposal()
    POST /api/proposals/{id}/reject  → update DB status → no submission

Lifecycle:
    scheduler = ExecutionScheduler(event_bus, db, config, submitter)
    await scheduler.start()
    ...
    await scheduler.stop()
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.departments.execution.gates import GatePipeline, GateVerdict
from src.models.events import Event, ProposalBlocked, ProposalSubmitted
from src.models.job import JobStatus
from src.models.proposal import ProposalStatus

if TYPE_CHECKING:
    from src.core.config import HerdConfig
    from src.core.db import Database
    from src.core.events import EventBusProtocol
    from src.platform.upwork.submitter import UpworkSubmitter

logger = logging.getLogger(__name__)


class ExecutionScheduler:
    """
    Event-driven scheduler that drives the proposal submission pipeline.

    Handles one proposal at a time, triggered by proposal_drafted events.
    Each submission attempt is fire-and-forget via asyncio.create_task.
    """

    def __init__(
        self,
        event_bus: "EventBusProtocol",
        db: "Database",
        config: "HerdConfig",
        submitter: "UpworkSubmitter",
    ) -> None:
        self._event_bus = event_bus
        self._db = db
        self._config = config
        self._submitter = submitter
        self._gates = GatePipeline(config.safety)
        self._running = False
        self._inflight: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Subscribe to proposal_drafted and proposal_approved events."""
        if self._running:
            logger.warning("ExecutionScheduler is already running")
            return
        self._running = True
        self._event_bus.subscribe("proposal_drafted", self._on_proposal_drafted)
        self._event_bus.subscribe("proposal_approved", self._on_proposal_approved)
        logger.info(
            "ExecutionScheduler started — subscribed to proposal_drafted, proposal_approved"
        )

    async def stop(self) -> None:
        """Drain in-flight tasks and unsubscribe."""
        if not self._running:
            return
        self._running = False
        self._event_bus.unsubscribe("proposal_drafted", self._on_proposal_drafted)
        self._event_bus.unsubscribe("proposal_approved", self._on_proposal_approved)
        await asyncio.sleep(0)
        while self._inflight:
            logger.info(
                "ExecutionScheduler stopping — waiting for %d in-flight tasks",
                len(self._inflight),
            )
            done, _ = await asyncio.wait(self._inflight)
            self._inflight -= done
            for task in done:
                if not task.cancelled():
                    task.exception()
        logger.info("ExecutionScheduler stopped")

    # ── Event handlers ────────────────────────────────────────────────────

    async def _on_proposal_drafted(self, event: Event) -> None:
        proposal_id: str = event.payload.get("proposal_id", "")
        if not proposal_id:
            logger.warning("proposal_drafted event missing proposal_id payload")
            return
        task = asyncio.create_task(
            self._process_and_handle_errors(proposal_id),
            name=f"execution-submit-{proposal_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _on_proposal_approved(self, event: Event) -> None:
        """Handle human approval — directly submit the proposal."""
        proposal_id: str = event.payload.get("proposal_id", "")
        if not proposal_id:
            logger.warning("proposal_approved event missing proposal_id payload")
            return
        task = asyncio.create_task(
            self._submit_approved_and_handle_errors(proposal_id),
            name=f"execution-approved-{proposal_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _process_and_handle_errors(self, proposal_id: str) -> None:
        try:
            await self.process_proposal(proposal_id)
        except Exception:
            logger.exception(
                "Unhandled error processing proposal %s", proposal_id
            )

    async def _submit_approved_and_handle_errors(self, proposal_id: str) -> None:
        try:
            await self._submit_proposal(proposal_id)
        except Exception:
            logger.exception(
                "Unhandled error submitting approved proposal %s", proposal_id
            )

    # ── Core pipeline ─────────────────────────────────────────────────────

    async def process_proposal(self, proposal_id: str) -> None:
        """
        Full execution pipeline for a single drafted proposal.

        Steps:
        1. Fetch ProposalDraft from DB.
        2. Run safety gate pipeline.
        3a. All PASS  → submit via platform adapter, emit ProposalSubmitted.
        3b. PENDING   → update status to pending_review, emit ProposalBlocked.
        3c. BLOCK     → update status to drafted (with error), emit ProposalBlocked.
        """
        from src.repositories.proposal_repo import (
            get_proposal,
            update_proposal_status,
        )

        draft = await get_proposal(self._db, proposal_id)
        if draft is None:
            logger.error(
                "ExecutionScheduler: proposal %s not found in DB", proposal_id
            )
            return

        logger.info(
            "Running gate pipeline for proposal %s (confidence=%.2f)",
            proposal_id,
            draft.confidence,
        )

        gate_results = await self._gates.run(draft, self._db)
        last = gate_results[-1]

        if last.verdict == GateVerdict.PENDING:
            # Human-in-the-loop: route to review queue
            await update_proposal_status(
                self._db,
                proposal_id,
                ProposalStatus.PENDING_REVIEW.value,
            )
            await self._event_bus.publish(
                ProposalBlocked(
                    payload={
                        "proposal_id": proposal_id,
                        "job_id": str(draft.job_id),
                        "reason": last.reason,
                        "gate": last.gate,
                        "verdict": "pending_review",
                    }
                )
            )
            logger.info(
                "Proposal %s routed to pending_review — awaiting human approval",
                proposal_id,
            )
            return

        if last.verdict == GateVerdict.BLOCK:
            # Hard block — do not submit
            await update_proposal_status(
                self._db,
                proposal_id,
                ProposalStatus.DRAFTED.value,
                error=last.reason,
            )
            await self._event_bus.publish(
                ProposalBlocked(
                    payload={
                        "proposal_id": proposal_id,
                        "job_id": str(draft.job_id),
                        "reason": last.reason,
                        "gate": last.gate,
                        "verdict": "blocked",
                    }
                )
            )
            logger.warning(
                "Proposal %s BLOCKED by [%s]: %s", proposal_id, last.gate, last.reason
            )
            return

        # All gates passed — submit
        await self._submit_proposal(proposal_id)

    async def _submit_proposal(self, proposal_id: str) -> None:
        """
        Submit a proposal via the platform adapter and record the result.

        Updates proposal status and job status in DB, emits ProposalSubmitted.
        """
        from src.repositories.job_repo import update_job_status
        from src.repositories.proposal_repo import (
            get_proposal,
            update_proposal_status,
        )

        draft = await get_proposal(self._db, proposal_id)
        if draft is None:
            logger.error("_submit_proposal: proposal %s not found", proposal_id)
            return

        logger.info(
            "Submitting proposal %s for job %s via platform adapter",
            proposal_id,
            draft.job_id,
        )

        result = await self._submitter.submit_proposal(draft)
        submitted_at = datetime.now(timezone.utc).isoformat()

        if result.error:
            logger.error(
                "Submission failed for proposal %s: %s", proposal_id, result.error
            )
            await update_proposal_status(
                self._db,
                proposal_id,
                ProposalStatus.DRAFTED.value,
                error=result.error,
            )
            await self._event_bus.publish(
                ProposalBlocked(
                    payload={
                        "proposal_id": proposal_id,
                        "job_id": str(draft.job_id),
                        "reason": result.error,
                        "gate": "platform_submission",
                        "verdict": "blocked",
                    }
                )
            )
            return

        await update_proposal_status(
            self._db,
            proposal_id,
            ProposalStatus.SUBMITTED.value,
            platform_proposal_id=result.platform_proposal_id,
            submitted_at=submitted_at,
        )
        await update_job_status(
            self._db, str(draft.job_id), JobStatus.PROPOSAL_SUBMITTED.value
        )

        await self._event_bus.publish(
            ProposalSubmitted(
                payload={
                    "proposal_id": proposal_id,
                    "job_id": str(draft.job_id),
                    "platform_proposal_id": result.platform_proposal_id,
                    "submitted_at": submitted_at,
                    "connects_spent": result.connects_spent,
                }
            )
        )
        logger.info(
            "Proposal %s submitted (platform_id=%s, connects=%.1f)",
            proposal_id,
            result.platform_proposal_id,
            result.connects_spent or 0.0,
        )
