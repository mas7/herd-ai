"""
UpworkAdapter — the single entry point for all Upwork platform operations.

Composes auth, scraper, and submitter into one object that satisfies
the full PlatformAdapter protocol. Callers only depend on the protocol;
the concrete class lives entirely within the upwork/ directory.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from src.models.client import Client
from src.models.job import Job, JobFilter
from src.models.proposal import ProposalDraft, ProposalResult
from src.platform.upwork.auth import UpworkAuth
from src.platform.upwork.scraper import UpworkScraper
from src.platform.upwork.submitter import UpworkSubmitter

logger = logging.getLogger(__name__)


class UpworkAdapter:
    """
    Full Upwork platform integration.

    Constructor-injected with all collaborators so they can be replaced
    in tests without touching the adapter logic.
    """

    def __init__(
        self,
        auth: UpworkAuth,
        scraper: UpworkScraper,
        submitter: UpworkSubmitter,
    ) -> None:
        self._auth = auth
        self._scraper = scraper
        self._submitter = submitter

    @property
    def platform_name(self) -> str:
        return "upwork"

    # ------------------------------------------------------------------
    # JobScraper
    # ------------------------------------------------------------------

    async def search_jobs(self, filters: JobFilter) -> AsyncIterator[Job]:
        """Delegate to the scraper's browser-based search."""
        return await self._scraper.search_jobs(filters)

    async def get_job_details(self, platform_job_id: str) -> Job:
        """Delegate to the scraper's single-job page fetch."""
        return await self._scraper.get_job_details(platform_job_id)

    # ------------------------------------------------------------------
    # ClientInspector
    # ------------------------------------------------------------------

    async def get_client_profile(self, platform_client_id: str) -> Client:
        """Delegate to the scraper's client profile fetch."""
        return await self._scraper.get_client_profile(platform_client_id)

    # ------------------------------------------------------------------
    # ProposalSubmitter
    # ------------------------------------------------------------------

    async def submit_proposal(self, draft: ProposalDraft) -> ProposalResult:
        """Delegate to the submitter's proposal form automation."""
        return await self._submitter.submit_proposal(draft)

    async def withdraw_proposal(self, platform_proposal_id: str) -> bool:
        """Delegate to the submitter's proposal withdrawal."""
        return await self._submitter.withdraw_proposal(platform_proposal_id)

    # ------------------------------------------------------------------
    # MessageSender
    # ------------------------------------------------------------------

    async def send_message(self, platform_client_id: str, message: str) -> bool:
        """Delegate to the submitter's messaging automation."""
        return await self._submitter.send_message(platform_client_id, message)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def healthcheck(self) -> bool:
        """
        Verify the platform integration is operational.

        Checks that the stored session cookie is still valid. Does not
        attempt a re-login; callers must handle expired sessions explicitly.
        """
        try:
            is_valid = await self._auth.is_session_valid()
            if not is_valid:
                logger.warning("Upwork healthcheck failed — session invalid")
            return is_valid
        except Exception:
            logger.exception("Upwork healthcheck raised an exception")
            return False
