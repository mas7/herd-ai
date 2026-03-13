"""
Analyst department agent factory functions.

Each function returns a fully configured CrewAI Agent. Agents are
stateless value objects — all state lives in the database or event bus.

Agents defined here:
  - create_fast_scorer()  — rule-based filter to quickly discard weak jobs
  - create_deep_scorer()  — LLM analyst that evaluates promising jobs deeply
"""
from __future__ import annotations

from crewai import Agent

from src.departments.analyst.tools import DeepScoreTool, FastScoreTool


def create_fast_scorer(fast_score_tool: FastScoreTool) -> Agent:
    """
    Build the Fast Scorer agent.

    This agent applies deterministic, rule-based scoring to every discovered
    job. Its goal is to immediately discard weak opportunities so that
    expensive LLM calls are reserved for genuinely promising jobs.
    """
    return Agent(
        role="Fast Scoring Analyst",
        goal=(
            "Rapidly evaluate each job opportunity using rule-based criteria. "
            "Score every job on skill match, budget fit, client quality, "
            "competition level, and freshness. Discard jobs that fall below "
            "the configured score threshold immediately."
        ),
        backstory=(
            "You are a meticulous numbers analyst who evaluates jobs in "
            "milliseconds using data-driven rules. You have processed thousands "
            "of freelance postings and developed a razor-sharp instinct for "
            "spotting weak opportunities before they waste anyone's time. "
            "You don't get emotional about jobs — you follow the numbers "
            "and apply the criteria with machine-like precision."
        ),
        tools=[fast_score_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def create_deep_scorer(deep_score_tool: DeepScoreTool) -> Agent:
    """
    Build the Deep Scorer agent.

    This agent performs a thorough semantic analysis of jobs that passed
    the fast filter. It uses LLM reasoning to assess strategic fit,
    feasibility, and win probability beyond what rules can capture.
    """
    return Agent(
        role="Deep Scoring Strategist",
        goal=(
            "Perform deep strategic analysis on jobs that passed the fast filter. "
            "Evaluate relevance, delivery feasibility, revenue potential, and "
            "win probability. Surface red flags that rule-based scoring misses. "
            "Produce a detailed reasoning summary for each evaluated job."
        ),
        backstory=(
            "You are a strategic advisor with deep expertise in freelance market "
            "dynamics. You go beyond surface-level signals to understand what a "
            "job truly demands and whether this agency can win and deliver it "
            "profitably. You have a nose for scope creep, underpaying clients, "
            "and unrealistic expectations — and you flag them before they become "
            "problems. Your analysis shapes which jobs the agency pursues."
        ),
        tools=[deep_score_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
