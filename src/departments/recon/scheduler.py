"""
Async scheduler for periodic Recon scanning.

Runs the Recon crew on a fixed interval and emits a JobDiscovered event
for each new job the crew returns. Long-running crew kicks are non-blocking:
each scan cycle runs as an asyncio Task so the scheduler loop stays responsive.

Lifecycle:
    scheduler = ReconScheduler(crew, event_bus, db)
    await scheduler.start(interval_seconds=300)
    ...
    await scheduler.stop()
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.models.events import JobDiscovered
from src.models.job import Job, JobStatus

if TYPE_CHECKING:
    from crewai import Crew

    from src.core.db import Database
    from src.core.events import EventBusProtocol

logger = logging.getLogger(__name__)


class ReconScheduler:
    """
    Periodic scheduler that drives the Recon crew.

    Each completed scan emits one JobDiscovered event per new job found,
    then persists those jobs to the database.
    """

    def __init__(
        self,
        crew: Crew,
        event_bus: EventBusProtocol,
        db: Database,
    ) -> None:
        self._crew = crew
        self._event_bus = event_bus
        self._db = db
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self, interval_seconds: int = 300) -> None:
        """
        Start periodic scanning with the given interval.

        Each scan cycle is an independent asyncio Task. Overlapping runs
        are prevented — if the previous scan is still running when the
        interval fires, the new scan is skipped and a warning is logged.
        """
        if self._running:
            logger.warning("ReconScheduler is already running")
            return

        self._running = True
        logger.info(
            "ReconScheduler started (interval=%ds)", interval_seconds
        )
        self._task = asyncio.create_task(
            self._loop(interval_seconds), name="recon-scheduler"
        )

    async def stop(self) -> None:
        """Signal the scheduler to stop after the current cycle completes."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReconScheduler stopped")

    async def run_once(self) -> list[Job]:
        """
        Execute a single scan cycle and return the discovered jobs.

        This is the primary entry point for testing and one-shot runs.
        Persists discovered jobs and publishes events.
        """
        logger.info("Recon scan starting at %s", datetime.now(timezone.utc).isoformat())

        try:
            raw_output = await asyncio.get_event_loop().run_in_executor(
                None, self._crew.kickoff
            )
        except Exception:
            logger.exception("Recon crew kickoff failed")
            return []

        jobs = self._parse_crew_output(str(raw_output))
        if not jobs:
            logger.info("Recon scan found no new jobs")
            return []

        logger.info("Recon scan discovered %d new jobs", len(jobs))
        await self._persist_and_emit(jobs)
        return jobs

    async def _loop(self, interval_seconds: int) -> None:
        """Internal polling loop — cancellation-safe."""
        while self._running:
            scan_task = asyncio.create_task(self.run_once(), name="recon-scan")
            try:
                await scan_task
            except asyncio.CancelledError:
                scan_task.cancel()
                raise
            except Exception:
                logger.exception("Recon scan cycle raised an unhandled error")

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    def _parse_crew_output(self, output: str) -> list[Job]:
        """
        Convert the crew's final text output into Job objects.

        The DedupAgent is instructed to return a JSON array. We attempt
        to extract that array from the output, tolerating preamble text.
        """
        # Find the JSON array within the crew output
        start = output.find("[")
        end = output.rfind("]") + 1
        if start == -1 or end == 0:
            logger.debug("No JSON array found in crew output")
            return []

        try:
            items: list[dict] = json.loads(output[start:end])
        except json.JSONDecodeError:
            logger.warning("Failed to parse crew output as JSON: %s", output[:200])
            return []

        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(_dict_to_job(item))
            except Exception:
                logger.debug("Skipping malformed job item from crew output: %s", item)
        return jobs

    async def _persist_and_emit(self, jobs: list[Job]) -> None:
        """Save jobs to DB and publish JobDiscovered events for each one."""
        from src.repositories.job_repo import save_job

        for job in jobs:
            try:
                await save_job(self._db, job)
            except Exception:
                logger.exception("Failed to save job %s", job.id)
                continue

            event = JobDiscovered(
                payload={
                    "job_id": job.id,
                    "platform": job.platform,
                    "platform_job_id": job.platform_job_id,
                    "title": job.title,
                    "url": job.url,
                    "job_type": job.job_type.value,
                },
            )
            await self._event_bus.publish(event)


def _dict_to_job(data: dict) -> Job:
    """
    Reconstruct a Job from a plain dict (as emitted by the crew).

    Handles string-encoded decimals and ISO datetime strings.
    """
    from decimal import Decimal

    from src.models.job import ExperienceLevel, JobType

    def _dec(v: str | None) -> Decimal | None:
        return Decimal(v) if v else None

    def _dt(v: str | None):
        if not v:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(v)

    return Job(
        platform=data.get("platform", "upwork"),
        platform_job_id=data["platform_job_id"],
        url=data.get("url", ""),
        title=data.get("title", "Unknown"),
        description=data.get("description", ""),
        job_type=JobType(data.get("job_type", "fixed")),
        experience_level=ExperienceLevel(data["experience_level"]) if data.get("experience_level") else None,
        budget_min=_dec(data.get("budget_min")),
        budget_max=_dec(data.get("budget_max")),
        hourly_rate_min=_dec(data.get("hourly_rate_min")),
        hourly_rate_max=_dec(data.get("hourly_rate_max")),
        required_skills=data.get("required_skills", []),
        client_country=data.get("client_country"),
        client_rating=data.get("client_rating"),
        client_total_spent=_dec(data.get("client_total_spent")),
        proposals_count=data.get("proposals_count"),
        posted_at=_dt(data.get("posted_at")),
        status=JobStatus.DISCOVERED,
    )
