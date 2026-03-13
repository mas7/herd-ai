from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.core.config import UserProfile
from src.core.crewai import ToolOnlyLLM
from src.departments.bizdev.crew import BizDevTools, build_bizdev_crew
from src.departments.bizdev.tools import BidStrategyTool, PricingTool
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import CompositeScore, DeepScore, FastScore


class _StubPositioner:
    async def get_angle(self, **kwargs: object) -> str:
        return "Lead with FastAPI delivery experience and clear scope control."


def _make_job() -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        platform="upwork",
        platform_job_id="bizdev-job-001",
        url="https://www.upwork.com/jobs/~bizdev-job-001",
        title="Senior FastAPI Backend Developer",
        description="Build a FastAPI backend with PostgreSQL and Docker.",
        job_type=JobType.HOURLY,
        experience_level=ExperienceLevel.EXPERT,
        hourly_rate_min=Decimal("80"),
        hourly_rate_max=Decimal("120"),
        required_skills=["Python", "FastAPI", "PostgreSQL"],
        proposals_count=5,
        posted_at=now,
        discovered_at=now,
        status=JobStatus.SCORED,
    )


def _make_score(job_id: str) -> CompositeScore:
    return CompositeScore(
        job_id=job_id,
        fast_score=FastScore(
            job_id=job_id,
            total=82.0,
            breakdown={
                "skill_match": 100.0,
                "budget_fit": 85.0,
                "client_quality": 70.0,
                "competition": 80.0,
                "freshness": 90.0,
            },
            pass_threshold=True,
        ),
        deep_score=DeepScore(
            job_id=job_id,
            relevance=88.0,
            feasibility=84.0,
            profitability=79.0,
            win_probability=85.0,
            reasoning="Strong technical fit and healthy budget range.",
            red_flags=[],
        ),
        final_score=83.5,
        recommendation="strong_pursue",
    )


def _make_tools() -> BizDevTools:
    job = _make_job()
    score = _make_score(job.id)
    profile = UserProfile(
        name="Jane Dev",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
        hourly_rate_min=60.0,
        hourly_rate_max=120.0,
        experience_level="expert",
    )
    return BizDevTools(
        pricing=PricingTool(job=job, profile=profile, score=score, win_history=[]),
        strategy=BidStrategyTool(
            positioner=_StubPositioner(),
            job=job,
            profile=profile,
            score=score,
            win_history=[],
        ),
    )


def test_build_bizdev_crew_uses_tool_only_llms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_NAME", raising=False)

    crew = build_bizdev_crew(_make_tools())

    assert len(crew.agents) == 2
    assert all(isinstance(agent.llm, ToolOnlyLLM) for agent in crew.agents)


def test_bizdev_crew_runs_without_default_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_NAME", raising=False)

    crew = build_bizdev_crew(_make_tools())

    result = crew.kickoff()

    assert "Lead with FastAPI delivery experience" in str(result)
