"""
CrewAI tools that wrap platform scrapers for the Recon department.

Each tool is a thin async-safe adapter between CrewAI's synchronous
tool-call interface and our async platform protocols.

Tools defined here:
  - PlatformSearchTool   wraps JobScraper.search_jobs()
  - JobDetailsTool       wraps JobScraper.get_job_details()
  - DeduplicationTool    checks the DB for an existing job record
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from src.models.job import JobFilter, JobType

if TYPE_CHECKING:
    from src.core.db import Database
    from src.platform.contracts import JobScraper

logger = logging.getLogger(__name__)


def _run_async(coro) -> object:
    """
    Run a coroutine from a synchronous context (CrewAI tool execute).

    Uses the running loop if one exists (via asyncio.run_coroutine_threadsafe)
    otherwise creates a fresh event loop. This bridges CrewAI's sync
    executor with our async I/O layer.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=120)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class SearchJobsInput(BaseModel):
    keywords: list[str] = Field(description="Search keywords for job titles/descriptions")
    skills: list[str] = Field(default_factory=list, description="Required skill tags")
    job_type: str = Field(default="", description="'hourly' or 'fixed', empty for any")
    posted_within_hours: int = Field(default=24, description="Only jobs posted within N hours")
    budget_min: float | None = Field(default=None, description="Minimum budget in USD")


class JobDetailsInput(BaseModel):
    platform_job_id: str = Field(description="Upwork job ciphertext or ID")


class DeduplicationInput(BaseModel):
    platform: str = Field(description="Platform name, e.g. 'upwork'")
    platform_job_id: str = Field(description="Platform-native job identifier")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class PlatformSearchTool(BaseTool):
    """
    Search for jobs on the configured platform.

    Returns a JSON-serialised list of job summaries (title, url, budget,
    skills) so the Recon Scout agent can evaluate and filter them.
    """

    name: str = "platform_search"
    description: str = (
        "Search for freelance jobs on the platform. "
        "Input: keywords, optional skills, job_type, posted_within_hours. "
        "Returns a JSON list of matching job summaries."
    )
    args_schema: type[BaseModel] = SearchJobsInput

    # Injected via constructor — not part of the Pydantic schema
    _scraper: JobScraper

    def __init__(self, scraper: JobScraper) -> None:
        super().__init__()
        self._scraper = scraper

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        parsed = SearchJobsInput(**kwargs)

        job_type = None
        if parsed.job_type == "hourly":
            job_type = JobType.HOURLY
        elif parsed.job_type == "fixed":
            job_type = JobType.FIXED

        from decimal import Decimal
        filters = JobFilter(
            keywords=parsed.keywords,
            skills=parsed.skills,
            job_type=job_type,
            posted_within_hours=parsed.posted_within_hours,
            budget_min=Decimal(str(parsed.budget_min)) if parsed.budget_min is not None else None,
        )

        summaries: list[dict] = []
        async for job in await self._scraper.search_jobs(filters):
            summaries.append({
                "id": job.id,
                "platform_job_id": job.platform_job_id,
                "title": job.title,
                "url": job.url,
                "job_type": job.job_type.value,
                "budget_min": str(job.budget_min) if job.budget_min else None,
                "budget_max": str(job.budget_max) if job.budget_max else None,
                "hourly_rate_min": str(job.hourly_rate_min) if job.hourly_rate_min else None,
                "hourly_rate_max": str(job.hourly_rate_max) if job.hourly_rate_max else None,
                "required_skills": job.required_skills,
                "proposals_count": job.proposals_count,
                "experience_level": job.experience_level.value if job.experience_level else None,
                "posted_at": job.posted_at.isoformat(),
            })

        logger.info("PlatformSearchTool found %d jobs", len(summaries))
        return json.dumps(summaries, ensure_ascii=False)


class JobDetailsTool(BaseTool):
    """
    Fetch the full details of a single job by its platform ID.

    Returns a JSON object with all fields extracted from the job detail page,
    including the full description, client signals, and current bid counts.
    """

    name: str = "job_details"
    description: str = (
        "Fetch full details of a specific job by its platform job ID. "
        "Returns a JSON object with title, description, budget, client info, etc."
    )
    args_schema: type[BaseModel] = JobDetailsInput

    _scraper: JobScraper

    def __init__(self, scraper: JobScraper) -> None:
        super().__init__()
        self._scraper = scraper

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        parsed = JobDetailsInput(**kwargs)
        job = await self._scraper.get_job_details(parsed.platform_job_id)
        return json.dumps({
            "id": job.id,
            "platform_job_id": job.platform_job_id,
            "title": job.title,
            "description": job.description,
            "url": job.url,
            "job_type": job.job_type.value,
            "experience_level": job.experience_level.value if job.experience_level else None,
            "budget_min": str(job.budget_min) if job.budget_min else None,
            "budget_max": str(job.budget_max) if job.budget_max else None,
            "hourly_rate_min": str(job.hourly_rate_min) if job.hourly_rate_min else None,
            "hourly_rate_max": str(job.hourly_rate_max) if job.hourly_rate_max else None,
            "required_skills": job.required_skills,
            "client_country": job.client_country,
            "client_rating": job.client_rating,
            "client_total_spent": str(job.client_total_spent) if job.client_total_spent else None,
            "proposals_count": job.proposals_count,
            "posted_at": job.posted_at.isoformat(),
        }, ensure_ascii=False)


class DeduplicationTool(BaseTool):
    """
    Check whether a job already exists in the database.

    Returns JSON: {"exists": true/false, "job_id": "<uuid or null>"}.
    The Recon dedup agent uses this to prevent the same job from
    entering the pipeline twice.
    """

    name: str = "check_duplicate"
    description: str = (
        "Check if a job has already been discovered and stored. "
        "Input: platform name and platform_job_id. "
        "Returns JSON with 'exists' boolean and 'job_id' if found."
    )
    args_schema: type[BaseModel] = DeduplicationInput

    _db: Database

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        from src.repositories.job_repo import get_job_by_platform_id

        parsed = DeduplicationInput(**kwargs)
        job = await get_job_by_platform_id(self._db, parsed.platform, parsed.platform_job_id)
        return json.dumps({
            "exists": job is not None,
            "job_id": job.id if job else None,
        })
