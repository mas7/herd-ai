"""Platform-agnostic job representation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from src.core.types import JobId


class JobType(StrEnum):
    FIXED = "fixed"
    HOURLY = "hourly"


class ExperienceLevel(StrEnum):
    ENTRY = "entry"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"


class JobStatus(StrEnum):
    DISCOVERED = "discovered"
    SCORING = "scoring"
    SCORED = "scored"
    REJECTED = "rejected"
    BID_DECIDED = "bid_decided"
    PASSED = "passed"
    PROPOSAL_DRAFTED = "proposal_drafted"
    PROPOSAL_SUBMITTED = "proposal_submitted"
    WON = "won"
    LOST = "lost"
    NO_RESPONSE = "no_response"


class Job(BaseModel):
    """Platform-agnostic job. The universal currency of Herd."""

    model_config = {"frozen": True}

    id: JobId = Field(default_factory=lambda: JobId(str(uuid.uuid4())))
    platform: str
    platform_job_id: str
    url: str

    title: str
    description: str
    job_type: JobType
    experience_level: ExperienceLevel | None = None

    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    hourly_rate_min: Decimal | None = None
    hourly_rate_max: Decimal | None = None

    required_skills: list[str] = Field(default_factory=list)
    optional_skills: list[str] = Field(default_factory=list)
    estimated_duration: str | None = None

    client_name: str | None = None
    client_country: str | None = None
    client_rating: float | None = None
    client_total_spent: Decimal | None = None
    client_hire_rate: float | None = None
    client_jobs_posted: int | None = None

    proposals_count: int | None = None
    interviewing_count: int | None = None

    posted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    status: JobStatus = JobStatus.DISCOVERED
    raw_data: dict | None = Field(default=None, exclude=True)


class JobFilter(BaseModel):
    """Search filters. Platform adapters translate to their native format."""

    keywords: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    job_type: JobType | None = None
    experience_level: ExperienceLevel | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    posted_within_hours: int = 24
    exclude_keywords: list[str] = Field(default_factory=list)
    platforms: list[str] | None = None
