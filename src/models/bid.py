"""Bid strategy models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.core.types import JobId


@dataclass(frozen=True)
class WinRecord:
    """Historical bid outcome used by the pricing engine for calibration."""

    bid_amount: float   # actual bid submitted
    job_type: str       # "hourly" | "fixed"
    was_won: bool


class BidStrategy(BaseModel):
    """
    Decision record produced by the BizDev department for a scored job.

    should_bid=True  → the agency will submit a proposal; all bid fields set.
    should_bid=False → the agency skips this job; pass_reason explains why.
    """

    model_config = {"frozen": True}

    job_id: JobId
    should_bid: bool
    bid_type: Literal["fixed", "hourly"] | None = None      # None when passing
    proposed_rate: Decimal | None = None                    # None when passing
    rate_range: tuple[Decimal, Decimal] | None = None       # None when passing
    positioning_angle: str | None = None                    # None when passing
    urgency: Literal["immediate", "normal", "low"] | None = None  # None when passing
    confidence: float                                        # 0-100
    reasoning: str
    pass_reason: str | None = None                          # set when should_bid=False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
