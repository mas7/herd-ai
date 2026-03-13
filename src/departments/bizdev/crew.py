"""
BizDev crew assembly.

Composes agents and tasks into a sequential CrewAI Crew.

Pipeline:
  1. PricingAnalyst computes the optimal bid price from job + profile + score data.
  2. BidStrategist crafts a positioning angle from the pricing result.

The crew is assembled once per job with the full job/score context baked in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from crewai import Agent, Crew, Process, Task

if TYPE_CHECKING := False:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.config import HerdConfig
    from src.departments.bizdev.positioning import Positioner
    from src.departments.bizdev.pricing import BidPrice, WinRecord
    from src.models.job import Job
    from src.models.score import CompositeScore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BizDevTools:
    """Grouped tool instances injected into the crew builder."""

    from src.departments.bizdev.tools import BidStrategyTool, PricingTool

    pricing: PricingTool
    strategy: BidStrategyTool


def _build_pricing_task(pricing_analyst: Agent) -> Task:
    return Task(
        description=(
            "Compute the optimal bid price for the loaded job opportunity. "
            "Use the pricing_strategy tool (no input needed — context is pre-loaded). "
            "Return the full JSON result including bid_type, amount, rate_range, "
            "viable flag, and reasoning."
        ),
        expected_output=(
            "A JSON object with: bid_type (str), amount (float), "
            "rate_range ([floor, ceiling]), viable (bool), reasoning (str)."
        ),
        agent=pricing_analyst,
    )


def _build_strategy_task(bid_strategist: Agent, pricing_task: Task) -> Task:
    return Task(
        description=(
            "Review the pricing result from the previous task. "
            "If viable is false, return a pass decision with the pricing reasoning. "
            "If viable is true, use the bid_strategy tool to generate a positioning angle. "
            "Return the angle JSON."
        ),
        expected_output=(
            "A JSON object with: angle (str — the 1-2 sentence proposal opening). "
            "Or a pass note if the pricing was not viable."
        ),
        agent=bid_strategist,
        context=[pricing_task],
    )


def build_bizdev_crew(
    tools: BizDevTools,
) -> Crew:
    """
    Assemble and return the BizDev Crew for a single job.

    The crew runs sequentially: PricingAnalyst -> BidStrategist.
    Context (job, score, profile) is baked into the tool instances at
    construction time, so no free-text job data needs to be passed here.
    """
    from src.departments.bizdev.agent import create_bid_strategist, create_pricing_analyst

    pricing_analyst = create_pricing_analyst(pricing_tool=tools.pricing)
    bid_strategist = create_bid_strategist(strategy_tool=tools.strategy)

    pricing_task = _build_pricing_task(pricing_analyst)
    strategy_task = _build_strategy_task(bid_strategist, pricing_task)

    crew = Crew(
        agents=[pricing_analyst, bid_strategist],
        tasks=[pricing_task, strategy_task],
        process=Process.sequential,
        verbose=False,
    )

    logger.info("BizDev crew assembled with %d agents", len(crew.agents))
    return crew
