"""Scoring models — two-stage architecture."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.core.types import JobId


class FastScore(BaseModel):
    """Stage 1: Rule-based, sub-100ms. No LLM calls."""

    model_config = {"frozen": True}

    job_id: JobId
    total: float
    breakdown: dict[str, float]
    pass_threshold: bool
    scored_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DeepScore(BaseModel):
    """Stage 2: LLM-powered semantic analysis."""

    model_config = {"frozen": True}

    job_id: JobId
    relevance: float
    feasibility: float
    profitability: float
    win_probability: float
    reasoning: str
    red_flags: list[str] = Field(default_factory=list)
    scored_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CompositeScore(BaseModel):
    """Combined score from both stages."""

    model_config = {"frozen": True}

    job_id: JobId
    fast_score: FastScore
    deep_score: DeepScore
    final_score: float
    rank: int | None = None
    recommendation: str  # "strong_pursue", "pursue", "maybe", "skip"
