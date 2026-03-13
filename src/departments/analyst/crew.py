"""
Analyst crew assembly.

Composes agents and tasks into a sequential CrewAI Crew.

Pipeline:
  1. FastScorer applies rule-based scoring; jobs below threshold are marked skip.
  2. DeepScorer performs LLM analysis on jobs that passed fast scoring.

The crew produces a JSON string that the scheduler consumes to build
CompositeScore records and emit events into the event bus.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from crewai import Agent, Crew, Process, Task

from src.core.config import HerdConfig
from src.departments.analyst.tools import DeepScoreTool, FastScoreTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalystTools:
    """Grouped tool instances injected into the crew builder."""

    fast_score: FastScoreTool
    deep_score: DeepScoreTool


def _build_fast_score_task(fast_scorer: Agent, job_json: str) -> Task:
    """Create the fast-scoring task."""
    return Task(
        description=(
            f"Score this job using rule-based fast scoring criteria. "
            f"Use the fast_score tool with the following job JSON:\n{job_json}\n\n"
            f"If the job does not pass the threshold (pass_threshold is false), "
            f"include that clearly in your output so the next agent knows to skip "
            f"the deep analysis. Return the full JSON result from the tool."
        ),
        expected_output=(
            "A JSON object from the fast_score tool containing: "
            "job_id, total (float), breakdown (dict of dimension scores), "
            "pass_threshold (bool), and scored_at."
        ),
        agent=fast_scorer,
    )


def _build_deep_score_task(deep_scorer: Agent, fast_score_task: Task) -> Task:
    """Create the deep-scoring task, dependent on the fast-score result."""
    return Task(
        description=(
            "Review the fast score result from the previous task. "
            "If pass_threshold is false, return the fast score result as-is with "
            "a note that deep scoring was skipped. "
            "If pass_threshold is true, use the deep_score tool with the same job JSON "
            "to perform a thorough LLM-based analysis. "
            "Return the deep score JSON result."
        ),
        expected_output=(
            "A JSON object from the deep_score tool (if pass_threshold was true) "
            "containing: job_id, relevance, feasibility, profitability, "
            "win_probability, reasoning, red_flags, and scored_at. "
            "Or a note that deep scoring was skipped if pass_threshold was false."
        ),
        agent=deep_scorer,
        context=[fast_score_task],
    )


def build_analyst_crew(tools: AnalystTools, config: HerdConfig, job_json: str) -> Crew:
    """
    Assemble and return the Analyst Crew for a single job.

    The crew runs sequentially: FastScorer -> DeepScorer.
    The final output is the DeepScorer's analysis JSON.

    Must be called once per job — the job_json is baked into the
    fast-score task description so the agent knows what to score.
    """
    from src.departments.analyst.agent import create_deep_scorer, create_fast_scorer

    fast_scorer = create_fast_scorer(fast_score_tool=tools.fast_score)
    deep_scorer = create_deep_scorer(deep_score_tool=tools.deep_score)

    fast_score_task = _build_fast_score_task(fast_scorer, job_json=job_json)
    deep_score_task = _build_deep_score_task(deep_scorer, fast_score_task)

    crew = Crew(
        agents=[fast_scorer, deep_scorer],
        tasks=[fast_score_task, deep_score_task],
        process=Process.sequential,
        verbose=False,
    )

    logger.info("Analyst crew assembled with %d agents", len(crew.agents))
    return crew
