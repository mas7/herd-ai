"""
Event payload models. Each event is a frozen Pydantic model.
Events are the ONLY way departments communicate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base event. All events inherit from this."""

    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_department: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


# --- Recon Events ---


class JobDiscovered(Event):
    event_type: str = "job_discovered"
    source_department: str = "recon"


# --- Analyst Events ---


class JobScored(Event):
    event_type: str = "job_scored"
    source_department: str = "analyst"


class JobRejected(Event):
    event_type: str = "job_rejected"
    source_department: str = "analyst"


# --- BizDev Events ---


class BidDecided(Event):
    event_type: str = "bid_decided"
    source_department: str = "bizdev"


class JobPassed(Event):
    event_type: str = "job_passed"
    source_department: str = "bizdev"


# --- Content Events ---


class ProposalDrafted(Event):
    event_type: str = "proposal_drafted"
    source_department: str = "content"


# --- Execution Events ---


class ProposalSubmitted(Event):
    event_type: str = "proposal_submitted"
    source_department: str = "execution"


class ProposalBlocked(Event):
    event_type: str = "proposal_blocked"
    source_department: str = "execution"


# --- Learning Events ---


class InsightGenerated(Event):
    event_type: str = "insight_generated"
    source_department: str = "learning"


# --- Outcome Events ---


class ProposalWon(Event):
    event_type: str = "proposal_won"
    source_department: str = "external"


class ProposalLost(Event):
    event_type: str = "proposal_lost"
    source_department: str = "external"


class ProposalNoResponse(Event):
    event_type: str = "proposal_no_response"
    source_department: str = "external"


# --- CEO Events ---


class StrategyUpdated(Event):
    event_type: str = "strategy_updated"
    source_department: str = "ceo"


class PipelineStarted(Event):
    event_type: str = "pipeline_started"
    source_department: str = "ceo"


class PipelineCompleted(Event):
    event_type: str = "pipeline_completed"
    source_department: str = "ceo"
