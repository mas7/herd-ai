"""Proposal lifecycle models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from src.core.types import JobId, ProposalId


class ProposalStatus(StrEnum):
    DRAFTED = "drafted"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    VIEWED = "viewed"
    SHORTLISTED = "shortlisted"
    WON = "won"
    LOST = "lost"
    WITHDRAWN = "withdrawn"
    NO_RESPONSE = "no_response"


class ProposalDraft(BaseModel):
    """What Content department produces."""

    id: ProposalId = Field(
        default_factory=lambda: ProposalId(str(uuid.uuid4()))
    )
    job_id: JobId
    platform: str
    platform_job_id: str

    bid_type: str
    bid_amount: Decimal
    estimated_duration: str | None = None

    cover_letter: str
    questions_answers: dict[str, str] = Field(default_factory=dict)

    confidence: float
    positioning_angle: str
    experiment_variants: dict[str, str] = Field(default_factory=dict)

    connects_cost: float | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ProposalResult(BaseModel):
    """What Execution department produces after submission."""

    proposal_id: ProposalId
    job_id: JobId
    platform: str
    platform_proposal_id: str | None = None
    status: ProposalStatus
    submitted_at: datetime | None = None
    error: str | None = None
    bid_amount: Decimal
    connects_spent: float | None = None
