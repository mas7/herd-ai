"""
Recon department agent factory functions.

Each function returns a fully configured CrewAI Agent. Agents are
stateless value objects — all state lives in the database or event bus.

Agents defined here:
  - create_recon_scout()  — monitors feeds and applies initial filters
  - create_dedup_agent()  — ensures no duplicate jobs enter the pipeline
"""
from __future__ import annotations

from crewai import Agent

from src.departments.recon.tools import (
    DeduplicationTool,
    JobDetailsTool,
    PlatformSearchTool,
)


def create_recon_scout(
    search_tool: PlatformSearchTool,
    details_tool: JobDetailsTool,
) -> Agent:
    """
    Build the Recon Scout agent.

    The Scout's role is to discover relevant job listings by querying
    the platform with configured filters, fetching full details for
    high-signal results, and passing a curated shortlist to the dedup
    agent for uniqueness verification.
    """
    return Agent(
        role="Recon Scout",
        goal=(
            "Discover high-quality freelance job opportunities on the platform "
            "that match the agency's skill profile and rate requirements. "
            "Retrieve full job details for promising listings."
        ),
        backstory=(
            "You are a highly disciplined intelligence operative with years of "
            "experience scanning freelancing platforms for the right contracts. "
            "You know how to spot genuine opportunities from noise: you look for "
            "clear scopes, reasonable budgets, and verified clients. You are fast, "
            "methodical, and never miss a relevant listing within your watch window."
        ),
        tools=[search_tool, details_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def create_dedup_agent(
    dedup_tool: DeduplicationTool,
) -> Agent:
    """
    Build the Deduplication Agent.

    This agent receives the Scout's shortlist and ensures only net-new
    jobs proceed. It checks each platform_job_id against the database
    and filters out anything already in the pipeline.
    """
    return Agent(
        role="Deduplication Analyst",
        goal=(
            "Ensure that only genuinely new job opportunities enter the pipeline. "
            "Cross-reference every discovered job against the database and discard "
            "any that have already been processed."
        ),
        backstory=(
            "You are a meticulous data quality officer responsible for pipeline "
            "integrity. You have seen what happens when duplicate bids are submitted "
            "— it looks unprofessional and wastes Connects. Your job is to act as "
            "the gatekeeper: nothing gets through that has been seen before. "
            "You operate with zero tolerance for duplicates."
        ),
        tools=[dedup_tool],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )
