"""
CrewAI tools for the Analyst department.

Each tool wraps a scoring function behind the synchronous BaseTool interface
using the same _run_async bridge as the Recon department.

Tools defined here:
  - FastScoreTool   wraps compute_fast_score()
  - DeepScoreTool   wraps DeepScorer.score()
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.core.config import FastScoreConfig, UserProfile
    from src.departments.analyst.deep_score import DeepScorer

logger = logging.getLogger(__name__)


def _run_async(coro: object) -> object:
    """
    Run a coroutine from a synchronous context (CrewAI tool execute).

    Uses the running loop if one exists (via asyncio.run_coroutine_threadsafe),
    otherwise creates a fresh event loop. Bridges CrewAI's sync executor with
    our async I/O layer.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
            return future.result(timeout=120)
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class FastScoreInput(BaseModel):
    job_json: str = Field(description="JSON string of the job to score")


class DeepScoreInput(BaseModel):
    job_json: str = Field(description="JSON string of the job to deep-score")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _job_from_json(job_json: str) -> object:
    """Deserialize a job from its JSON representation."""
    from datetime import datetime, timezone

    from src.models.job import ExperienceLevel, Job, JobStatus, JobType

    data = json.loads(job_json)

    def _dec(v: str | None) -> Decimal | None:
        return Decimal(v) if v else None

    def _dt(v: str | None) -> datetime:
        if not v:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(v)

    return Job(
        id=data["id"],
        platform=data.get("platform", "upwork"),
        platform_job_id=data["platform_job_id"],
        url=data.get("url", ""),
        title=data.get("title", ""),
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
        client_hire_rate=data.get("client_hire_rate"),
        client_jobs_posted=data.get("client_jobs_posted"),
        proposals_count=data.get("proposals_count"),
        posted_at=_dt(data.get("posted_at")),
        status=JobStatus(data.get("status", "discovered")),
    )


class FastScoreTool(BaseTool):
    """
    Run the rule-based fast scorer on a job.

    Returns a JSON object with total score, per-dimension breakdown,
    and whether the job passed the configured threshold.
    """

    name: str = "fast_score"
    description: str = (
        "Score a job using rule-based fast scoring. "
        "Input: JSON string of a job object. "
        "Returns JSON with total score, breakdown, and pass_threshold flag."
    )
    args_schema: type[BaseModel] = FastScoreInput

    _fast_score_config: FastScoreConfig
    _profile: UserProfile

    def __init__(self, fast_score_config: FastScoreConfig, profile: UserProfile) -> None:
        super().__init__()
        self._fast_score_config = fast_score_config
        self._profile = profile

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        from src.departments.analyst.fast_score import compute_fast_score

        parsed = FastScoreInput(**kwargs)
        job = _job_from_json(parsed.job_json)

        score = compute_fast_score(
            job=job,  # type: ignore[arg-type]
            profile=self._profile,
            weights=self._fast_score_config.weights,
            threshold=self._fast_score_config.threshold,
        )
        return json.dumps({
            "job_id": score.job_id,
            "total": score.total,
            "breakdown": score.breakdown,
            "pass_threshold": score.pass_threshold,
            "scored_at": score.scored_at.isoformat(),
        })


class DeepScoreTool(BaseTool):
    """
    Run the LLM-powered deep scorer on a job.

    Returns a JSON object with relevance, feasibility, profitability,
    win_probability, reasoning, and any identified red flags.
    """

    name: str = "deep_score"
    description: str = (
        "Perform deep LLM analysis on a job opportunity. "
        "Input: JSON string of a job object. "
        "Returns JSON with relevance, feasibility, profitability, win_probability, "
        "reasoning, and red_flags."
    )
    args_schema: type[BaseModel] = DeepScoreInput

    _deep_scorer: DeepScorer
    _profile: UserProfile

    def __init__(self, deep_scorer: DeepScorer, profile: UserProfile) -> None:
        super().__init__()
        self._deep_scorer = deep_scorer
        self._profile = profile

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        parsed = DeepScoreInput(**kwargs)
        job = _job_from_json(parsed.job_json)

        score = await self._deep_scorer.score(job=job, profile=self._profile)  # type: ignore[arg-type]
        return json.dumps({
            "job_id": score.job_id,
            "relevance": score.relevance,
            "feasibility": score.feasibility,
            "profitability": score.profitability,
            "win_probability": score.win_probability,
            "reasoning": score.reasoning,
            "red_flags": score.red_flags,
            "scored_at": score.scored_at.isoformat(),
        })
