"""Bid strategy models."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from src.core.types import JobId


class BidStrategy(BaseModel):
    model_config = {"frozen": True}

    job_id: JobId
    should_bid: bool
    bid_type: Literal["fixed", "hourly"]
    proposed_rate: Decimal
    rate_range: tuple[Decimal, Decimal]
    positioning_angle: str
    urgency: Literal["immediate", "normal", "low"]
    confidence: float
    reasoning: str
