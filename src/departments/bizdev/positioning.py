"""
LLM-powered positioning engine for the BizDev department.

Generates a competitive positioning angle for a job proposal — a 1-2 sentence
narrative lead that differentiates the freelancer and addresses the specific
needs of the posting. Uses litellm for provider-agnostic model routing.
"""
from __future__ import annotations

import json
import logging

import litellm

from src.core.config import UserProfile
from src.departments.bizdev.pricing import BidPrice
from src.models.job import Job
from src.models.score import CompositeScore

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a proposal strategist for a freelancing agency. Produce a competitive
positioning angle for the proposal below.

FREELANCER PROFILE:
- Skills: {skills}
- Experience: {experience_level}
- Rate: ${hourly_rate_min}-${hourly_rate_max}/hr

JOB POSTING:
- Title: {title}
- Description: {description}
- Required Skills: {required_skills}
- Client Country: {client_country}
- Proposed Bid: {bid_type} at {bid_display}

ANALYST SCORES:
- Final Score: {final_score:.1f}/100
- Relevance: {relevance:.0f}/100
- Win Probability: {win_probability:.0f}/100
- Red Flags: {red_flags}

Generate a 1-2 sentence positioning angle that:
1. Opens with the freelancer's strongest match for this specific job.
2. Proactively addresses the most critical red flag (if any).
3. Sounds human and specific — not generic AI filler.

Respond in JSON only:
{{
  "angle": "<1-2 sentence positioning angle for the proposal opening>",
  "reasoning": "<brief internal note on why this angle>"
}}"""

_CONSERVATIVE_ANGLE = (
    "I have the skills and experience to deliver exactly what you need for this project. "
    "Let me walk you through how I'd approach it."
)


def _build_prompt(
    job: Job,
    profile: UserProfile,
    score: CompositeScore,
    bid_price: BidPrice,
) -> str:
    bid_display = (
        f"${bid_price.amount:.0f}/hr"
        if bid_price.bid_type == "hourly"
        else f"${bid_price.amount:.0f} fixed"
    )
    return _PROMPT_TEMPLATE.format(
        skills=", ".join(profile.skills) if profile.skills else "not specified",
        experience_level=profile.experience_level,
        hourly_rate_min=profile.hourly_rate_min,
        hourly_rate_max=profile.hourly_rate_max,
        title=job.title,
        description=job.description[:1500],
        required_skills=", ".join(job.required_skills) if job.required_skills else "none listed",
        client_country=job.client_country or "unknown",
        bid_type=bid_price.bid_type,
        bid_display=bid_display,
        final_score=score.final_score,
        relevance=score.deep_score.relevance,
        win_probability=score.deep_score.win_probability,
        red_flags=", ".join(score.deep_score.red_flags) if score.deep_score.red_flags else "none",
    )


def _parse_angle(content: str) -> str:
    """Extract the positioning angle from the LLM JSON response."""
    start = content.find("{")
    end = content.rfind("}") + 1
    if start == -1 or end == 0:
        return _CONSERVATIVE_ANGLE
    try:
        data = json.loads(content[start:end])
        angle = data.get("angle", "")
        return str(angle) if angle else _CONSERVATIVE_ANGLE
    except json.JSONDecodeError:
        return _CONSERVATIVE_ANGLE


class Positioner:
    """
    LLM-powered positioning angle generator.

    Sends a structured prompt and returns a 1-2 sentence proposal opening.
    Falls back to a conservative generic angle on any failure.
    """

    def __init__(self, model: str, temperature: float) -> None:
        self._model = model
        self._temperature = temperature

    async def get_angle(
        self,
        job: Job,
        profile: UserProfile,
        score: CompositeScore,
        bid_price: BidPrice,
    ) -> str:
        """
        Generate a positioning angle for the proposal.

        Returns a conservative fallback on LLM or parse failure so the
        pipeline never blocks waiting on an angle.
        """
        prompt = _build_prompt(job, profile, score, bid_price)

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
            )
            content: str = response.choices[0].message.content or ""
        except Exception:
            logger.exception("Positioner LLM call failed for job %s — using fallback", job.id)
            return _CONSERVATIVE_ANGLE

        return _parse_angle(content) if content else _CONSERVATIVE_ANGLE
