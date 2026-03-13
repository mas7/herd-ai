"""
CrewAI tools for the BizDev department.

Tools defined here:
  - PricingTool       wraps compute_bid_price()
  - BidStrategyTool   wraps Positioner.get_angle()
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.core.config import UserProfile
    from src.departments.bizdev.positioning import Positioner
    from src.models.bid import WinRecord
    from src.models.job import Job
    from src.models.score import CompositeScore

logger = logging.getLogger(__name__)


def _run_async(coro: object) -> object:
    """Run a coroutine from a synchronous CrewAI tool context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
            return future.result(timeout=120)
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]


class PricingInput(BaseModel):
    context: str = Field(
        description="Optional context — pricing uses pre-injected job/score/profile data",
        default="",
    )


class BidStrategyInput(BaseModel):
    context: str = Field(
        description="Optional context — strategy uses pre-injected job/score/bid data",
        default="",
    )


class PricingTool(BaseTool):
    """
    Compute the optimal bid price for a pre-loaded job.

    Returns a JSON object with bid_type, amount, rate_range, viable flag,
    and a human-readable reasoning string.
    """

    name: str = "pricing_strategy"
    description: str = (
        "Compute an optimal bid price from the loaded job, profile, and analyst "
        "scores. Returns JSON with bid_type, amount, rate_range, viable, reasoning."
    )
    args_schema: type[BaseModel] = PricingInput
    result_as_answer: bool = True

    _job: Job
    _profile: UserProfile
    _score: CompositeScore
    _win_history: list[WinRecord]

    def __init__(
        self,
        job: Job,
        profile: UserProfile,
        score: CompositeScore,
        win_history: list[WinRecord],
    ) -> None:
        super().__init__()
        self._job = job
        self._profile = profile
        self._score = score
        self._win_history = win_history

    def _run(self, **kwargs: object) -> str:
        from src.departments.bizdev.pricing import compute_bid_price

        bid_price = compute_bid_price(
            job=self._job,
            profile=self._profile,
            score=self._score,
            win_history=self._win_history,
        )
        return json.dumps({
            "bid_type": bid_price.bid_type,
            "amount": bid_price.amount,
            "rate_range": list(bid_price.rate_range),
            "viable": bid_price.viable,
            "reasoning": bid_price.reasoning,
        })


class BidStrategyTool(BaseTool):
    """
    Generate a positioning angle for a pre-loaded job bid.

    Computes the BidPrice at run-time from the injected job/profile/score/
    win_history so that the tool can be constructed before pricing runs —
    matching the PricingAnalyst → BidStrategist crew sequence.

    Returns a JSON object with the positioning angle string.
    """

    name: str = "bid_strategy"
    description: str = (
        "Generate a positioning angle for the proposal given the loaded job, "
        "analyst scores, and pricing recommendation. "
        "Returns JSON with angle string."
    )
    args_schema: type[BaseModel] = BidStrategyInput
    result_as_answer: bool = True

    _positioner: Positioner
    _job: Job
    _profile: UserProfile
    _score: CompositeScore
    _win_history: list[WinRecord]

    def __init__(
        self,
        positioner: Positioner,
        job: Job,
        profile: UserProfile,
        score: CompositeScore,
        win_history: list[WinRecord],
    ) -> None:
        super().__init__()
        self._positioner = positioner
        self._job = job
        self._profile = profile
        self._score = score
        self._win_history = win_history

    def _run(self, **kwargs: object) -> str:
        return str(_run_async(self._arun(**kwargs)))

    async def _arun(self, **kwargs: object) -> str:
        from src.departments.bizdev.pricing import compute_bid_price

        bid_price = compute_bid_price(
            job=self._job,
            profile=self._profile,
            score=self._score,
            win_history=self._win_history,
        )
        angle = await self._positioner.get_angle(
            job=self._job,
            profile=self._profile,
            score=self._score,
            bid_price=bid_price,
        )
        return json.dumps({"angle": angle})
