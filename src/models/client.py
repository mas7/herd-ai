"""Platform-agnostic client profile."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ClientSignals(BaseModel):
    """Derived signals about client quality and behavior."""

    is_verified_payment: bool = False
    avg_review_score: float | None = None
    typical_project_size: Decimal | None = None
    response_rate: float | None = None
    repeat_hire_rate: float | None = None
    risk_level: str = "unknown"


class Client(BaseModel):
    model_config = {"frozen": True}

    platform: str
    platform_client_id: str
    name: str | None = None
    country: str | None = None
    member_since: datetime | None = None
    total_spent: Decimal | None = None
    total_jobs_posted: int | None = None
    hire_rate: float | None = None
    rating: float | None = None
    signals: ClientSignals = Field(default_factory=ClientSignals)
