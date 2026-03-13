"""A/B testing models for the Learning department."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Variant(BaseModel):
    key: str
    description: str
    weight: float = 0.5


class Experiment(BaseModel):
    id: str
    name: str
    hypothesis: str
    department: str
    parameter: str
    variants: list[Variant]
    primary_metric: str
    status: ExperimentStatus = ExperimentStatus.DRAFT
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExperimentResult(BaseModel):
    experiment_id: str
    variant_key: str
    sample_size: int
    metric_value: float
    confidence_interval: tuple[float, float]
    is_significant: bool
    p_value: float | None = None
