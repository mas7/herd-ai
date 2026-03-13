"""
BizDev department agent factory functions.

Agents defined here:
  - create_pricing_analyst()  — rule-based bid price calculator
  - create_bid_strategist()   — LLM strategist that sets angle and urgency
"""
from __future__ import annotations

from crewai import Agent

from src.departments.bizdev.tools import BidStrategyTool, PricingTool


def create_pricing_analyst(pricing_tool: PricingTool) -> Agent:
    """
    Build the Pricing Analyst agent.

    Computes an optimal bid price from job data, freelancer profile, and
    analyst scores. Uses rule-based logic — no LLM calls — so it runs fast
    and deterministically for every job that passes analyst scoring.
    """
    return Agent(
        role="Pricing Analyst",
        goal=(
            "Determine the optimal bid price for each job opportunity. "
            "Analyse the job's budget, the freelancer's rate expectations, "
            "competition level, and historical win data. Output a concrete "
            "price recommendation with a floor and ceiling range."
        ),
        backstory=(
            "You are a seasoned freelance pricing expert with years of market "
            "data at your fingertips. You know exactly how to price for maximum "
            "win rate without leaving money on the table. You weigh competition "
            "signals, budget indicators, and win probability to arrive at a "
            "number that the client will seriously consider while still making "
            "the project worth the freelancer's time."
        ),
        tools=[pricing_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


def create_bid_strategist(strategy_tool: BidStrategyTool) -> Agent:
    """
    Build the Bid Strategist agent.

    Combines the pricing analyst's output with deep job context to craft a
    positioning angle and urgency level for the proposal. The strategist's
    angle becomes the opening of the cover letter in the Content department.
    """
    return Agent(
        role="Bid Strategist",
        goal=(
            "Craft a compelling positioning angle and determine the urgency "
            "for each bid. The angle must be specific to the job, lead with "
            "the freelancer's strongest credential match, and proactively "
            "address any red flags surfaced by the analyst."
        ),
        backstory=(
            "You are an elite proposal strategist who has helped freelancers "
            "win hundreds of competitive contracts. You read job postings the "
            "way a detective reads a crime scene — finding the hidden signals "
            "about what the client actually needs versus what they wrote. "
            "Your positioning angles are never generic. Every angle you craft "
            "makes the client feel like the freelancer was built specifically "
            "for their project."
        ),
        tools=[strategy_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
