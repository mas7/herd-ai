"""
Platform abstraction contracts.

Every freelancing platform implements PlatformAdapter.
Adding a new platform = one new directory with one adapter class.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from src.models.client import Client
from src.models.job import Job, JobFilter
from src.models.proposal import ProposalDraft, ProposalResult


@runtime_checkable
class JobScraper(Protocol):
    """Scrapes job listings from a platform."""

    async def search_jobs(self, filters: JobFilter) -> AsyncIterator[Job]: ...

    async def get_job_details(self, platform_job_id: str) -> Job: ...


@runtime_checkable
class ClientInspector(Protocol):
    """Extracts client signals from a platform."""

    async def get_client_profile(self, platform_client_id: str) -> Client: ...


@runtime_checkable
class ProposalSubmitter(Protocol):
    """Submits proposals on a platform."""

    async def submit_proposal(self, draft: ProposalDraft) -> ProposalResult: ...

    async def withdraw_proposal(self, platform_proposal_id: str) -> bool: ...


@runtime_checkable
class MessageSender(Protocol):
    """Sends follow-up messages on a platform."""

    async def send_message(
        self, platform_client_id: str, message: str
    ) -> bool: ...


@runtime_checkable
class PlatformAdapter(
    JobScraper, ClientInspector, ProposalSubmitter, MessageSender, Protocol
):
    """
    Full platform integration.

    Sub-protocols exist for Interface Segregation:
    Recon only needs JobScraper, Execution only needs ProposalSubmitter.
    """

    @property
    def platform_name(self) -> str: ...

    async def healthcheck(self) -> bool: ...
