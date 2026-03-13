"""
Recon crew assembly.

Composes agents and tasks into a sequential CrewAI Crew.

Pipeline:
  1. Scout discovers and fetches jobs matching the filters.
  2. DedupAgent cross-references against the DB and returns only new jobs.

The crew produces a JSON string that the scheduler consumes to emit
job_discovered events into the event bus.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from crewai import Agent, Crew, Process, Task

from src.core.config import HerdConfig
from src.departments.recon.tools import (
    DeduplicationTool,
    JobDetailsTool,
    PlatformSearchTool,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconTools:
    """Grouped tool instances injected into the crew builder."""

    search: PlatformSearchTool
    details: JobDetailsTool
    dedup: DeduplicationTool


def _build_scout_task(scout: Agent, config: HerdConfig) -> Task:
    """Create the job discovery task for the Scout agent."""
    skills_str = ", ".join(config.user_profile.skills) if config.user_profile.skills else "general freelancing"
    return Task(
        description=(
            f"Search for new freelance job opportunities posted within the last "
            f"{24} hours. Focus on jobs requiring these skills: {skills_str}. "
            f"Use the platform_search tool with appropriate keywords and filters. "
            f"For each promising result, use the job_details tool to fetch the "
            f"full job description and client information. "
            f"Return a JSON list of job objects with all available fields."
        ),
        expected_output=(
            "A JSON array of job objects. Each object must include: "
            "platform_job_id, title, url, description, job_type, "
            "budget information, required_skills, client signals, and posted_at."
        ),
        agent=scout,
    )


def _build_dedup_task(dedup_agent: Agent, scout_task: Task) -> Task:
    """Create the deduplication task that filters the Scout's output."""
    return Task(
        description=(
            "Review the list of jobs discovered by the Scout. "
            "For each job in the list, use the check_duplicate tool with the "
            "platform name ('upwork') and the platform_job_id. "
            "Remove any jobs where 'exists' is true. "
            "Return only the net-new jobs as a JSON array, preserving all fields."
        ),
        expected_output=(
            "A JSON array containing only net-new jobs (not previously seen). "
            "Empty array [] if all jobs are duplicates. "
            "Each object must retain all fields from the Scout's output."
        ),
        agent=dedup_agent,
        context=[scout_task],
    )


def build_recon_crew(tools: ReconTools, config: HerdConfig) -> Crew:
    """
    Assemble and return the Recon Crew.

    The crew runs sequentially: Scout -> DedupAgent.
    The final output is the DedupAgent's JSON array of new jobs.
    """
    from src.departments.recon.agent import create_dedup_agent, create_recon_scout

    scout = create_recon_scout(
        search_tool=tools.search,
        details_tool=tools.details,
    )
    dedup_agent = create_dedup_agent(dedup_tool=tools.dedup)

    scout_task = _build_scout_task(scout, config)
    dedup_task = _build_dedup_task(dedup_agent, scout_task)

    crew = Crew(
        agents=[scout, dedup_agent],
        tasks=[scout_task, dedup_task],
        process=Process.sequential,
        verbose=False,
    )

    logger.info("Recon crew assembled with %d agents", len(crew.agents))
    return crew
