"""
Upwork proposal submission and messaging — STUB implementation.

The structure fully satisfies the ProposalSubmitter and MessageSender
protocols. Actual browser automation sequences will be refined in
Feature #5. All public methods are marked with TODO comments indicating
the exact Playwright steps required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.models.proposal import ProposalDraft, ProposalResult, ProposalStatus

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.upwork.com"


class UpworkSubmitter:
    """
    Submits proposals and sends messages on Upwork via browser automation.

    This is a STUB — the public interface matches the protocols exactly
    but browser interaction sequences are placeholders pending Feature #5.
    """

    def __init__(self, browser_context: BrowserContext, base_url: str = _BASE_URL) -> None:
        self._context = browser_context
        self._base_url = base_url

    async def submit_proposal(self, draft: ProposalDraft) -> ProposalResult:
        """
        Fill out and submit an Upwork proposal form.

        TODO (Feature #5): Implement full browser automation sequence:
          1. Navigate to job URL: /jobs/{draft.platform_job_id}
          2. Click the "Apply Now" button (data-test="apply-now-button")
          3. Wait for the proposal modal/page to load
          4. Fill hourly rate or fixed price (draft.bid_amount)
          5. Fill estimated duration (draft.estimated_duration)
          6. Fill cover letter textarea (draft.cover_letter)
          7. For each item in draft.questions_answers, locate the
             question element by text and fill the corresponding textarea
          8. Review the connects cost displayed and validate against
             draft.connects_cost
          9. Click "Submit Proposal" and wait for confirmation
          10. Extract platform_proposal_id from confirmation page URL or
              response payload
          11. Return ProposalResult with status=SUBMITTED
        """
        logger.warning(
            "submit_proposal is a stub — proposal %s not actually submitted",
            draft.id,
        )
        return ProposalResult(
            proposal_id=draft.id,
            job_id=draft.job_id,
            platform=draft.platform,
            platform_proposal_id=None,
            status=ProposalStatus.DRAFTED,
            submitted_at=None,
            error="Submission not yet implemented (Feature #5)",
            bid_amount=draft.bid_amount,
            connects_spent=None,
        )

    async def withdraw_proposal(self, platform_proposal_id: str) -> bool:
        """
        Withdraw a previously submitted proposal.

        TODO (Feature #5): Implement browser automation sequence:
          1. Navigate to /proposals/{platform_proposal_id}
          2. Click "Withdraw Proposal" button
          3. Confirm the withdrawal dialog
          4. Verify the proposal status changes to "Withdrawn"
          5. Return True on success
        """
        logger.warning(
            "withdraw_proposal is a stub — proposal %s not actually withdrawn",
            platform_proposal_id,
        )
        return False

    async def send_message(self, platform_client_id: str, message: str) -> bool:
        """
        Send a message to a client via Upwork's messaging system.

        TODO (Feature #5): Implement browser automation sequence:
          1. Navigate to /messages/rooms or find existing conversation
             with platform_client_id
          2. If no existing room, create one via the "Message" button
             on the client's profile page
          3. Locate the message compose textarea
          4. Type message character by character with random delays
             to mimic human input (avoid paste detection)
          5. Click "Send" button
          6. Wait for the message to appear in the thread
          7. Return True on success
        """
        logger.warning(
            "send_message is a stub — message to client %s not sent",
            platform_client_id,
        )
        _ = message  # suppress unused-arg warning until Feature #5
        return False
