"""
LLM-powered proposal writer for the Content department.

Generates a personalised cover letter in the proven structure:
  Hook → Plan → Proof → Fit → CTA  (150-250 words)

Uses past proposals retrieved from the RAG store as stylistic anchors,
and the BidStrategy positioning angle as the opening hook seed.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import litellm

from src.models.proposal import ProposalDraft

if TYPE_CHECKING:
    from src.core.config import UserProfile
    from src.departments.content.rag import ProposalStore
    from src.models.bid import BidStrategy
    from src.models.job import Job
    from src.models.score import CompositeScore

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a freelance proposal writer. Write a winning proposal cover letter.

FREELANCER PROFILE:
- Name: {name}
- Skills: {skills}
- Experience: {experience_level}
- Rate: ${hourly_rate_min}-${hourly_rate_max}/hr

JOB POSTING:
- Title: {title}
- Description: {description}
- Required Skills: {required_skills}
- Budget: {budget}
- Client Country: {client_country}

BID STRATEGY:
- Positioning Angle: {positioning_angle}
- Bid: {bid_display}
- Confidence: {confidence:.0f}/100
- Win Probability: {win_probability:.0f}/100
- Red Flags: {red_flags}

PAST WINNING PROPOSALS (for style and structure reference):
{past_proposals}

Write a 150-250 word cover letter following this structure:
1. HOOK (1-2 sentences): Open with the positioning angle — reference a specific detail from the job.
2. PLAN (2-4 bullets): Concrete first milestone + approach. Show you've thought about their problem.
3. PROOF (1-2 sentences): One relevant result or portfolio item that matches this job.
4. FIT + TIMELINE (1 sentence): Why you specifically + when you can deliver.
5. CTA (1 sentence): One clear next step (e.g., quick call, question, Loom walkthrough).

Rules:
- Sound human — no AI filler ("I am excited to...", "I would love to...", "As an expert...")
- Be specific to THIS job, not generic
- Keep it 150-250 words
- Match the tone of the past proposals (direct, professional, confident)

Also identify any clarifying questions worth asking the client.

Respond in JSON only:
{{
  "cover_letter": "<full cover letter text>",
  "questions": ["<optional question 1>", "<optional question 2>"],
  "confidence": <0-100 float, your confidence this proposal will get a response>,
  "reasoning": "<one sentence on why this proposal will work>"
}}"""

_CONSERVATIVE_COVER_LETTER = (
    "I've read through your job posting carefully and I'm confident I can deliver exactly "
    "what you need. I have relevant experience with the required skills and can start "
    "immediately. Let's hop on a quick call to align on the details and get started."
)


def _format_past_proposals(results: list[dict]) -> str:
    if not results:
        return "No past proposals available."
    lines = []
    for i, r in enumerate(results[:3], 1):
        meta = r.get("metadata", {})
        outcome = meta.get("outcome", "unknown")
        title = meta.get("job_title", "")
        doc = r.get("document", "")
        # Strip the job header from the stored document
        body = doc.split("\n\n", 1)[-1] if "\n\n" in doc else doc
        lines.append(f"[{i}] Job: {title} | Outcome: {outcome}\n{body[:400]}")
    return "\n\n---\n\n".join(lines)


def _format_budget(job: "Job") -> str:
    if job.job_type.value == "hourly":
        lo = f"${job.hourly_rate_min}" if job.hourly_rate_min else "?"
        hi = f"${job.hourly_rate_max}" if job.hourly_rate_max else "?"
        return f"{lo}-{hi}/hr"
    lo = f"${job.budget_min}" if job.budget_min else "?"
    hi = f"${job.budget_max}" if job.budget_max else "?"
    return f"{lo}-{hi} fixed"


def _build_prompt(
    job: "Job",
    profile: "UserProfile",
    strategy: "BidStrategy",
    score: "CompositeScore",
    past_proposals: list[dict],
) -> str:
    bid_display = (
        f"${strategy.proposed_rate:.0f}/hr"
        if strategy.bid_type == "hourly"
        else f"${strategy.proposed_rate:.0f} fixed"
    )
    return _PROMPT_TEMPLATE.format(
        name=profile.name or "the freelancer",
        skills=", ".join(profile.skills) if profile.skills else "not specified",
        experience_level=profile.experience_level,
        hourly_rate_min=profile.hourly_rate_min,
        hourly_rate_max=profile.hourly_rate_max,
        title=job.title,
        description=job.description[:2000],
        required_skills=", ".join(job.required_skills) if job.required_skills else "none listed",
        budget=_format_budget(job),
        client_country=job.client_country or "unknown",
        positioning_angle=strategy.positioning_angle or "Lead with your strongest match.",
        bid_display=bid_display,
        confidence=strategy.confidence,
        win_probability=score.deep_score.win_probability,
        red_flags=", ".join(score.deep_score.red_flags) if score.deep_score.red_flags else "none",
        past_proposals=_format_past_proposals(past_proposals),
    )


def _parse_draft(content: str) -> tuple[str, list[str], float]:
    """Extract cover_letter, questions, confidence from LLM JSON response."""
    start = content.find("{")
    end = content.rfind("}") + 1
    if start == -1 or end == 0:
        return _CONSERVATIVE_COVER_LETTER, [], 40.0
    try:
        data = json.loads(content[start:end])
        letter = str(data.get("cover_letter", "") or _CONSERVATIVE_COVER_LETTER)
        questions = [str(q) for q in data.get("questions", []) if q]
        confidence = float(data.get("confidence", 50.0))
        return letter or _CONSERVATIVE_COVER_LETTER, questions, confidence
    except (json.JSONDecodeError, ValueError):
        return _CONSERVATIVE_COVER_LETTER, [], 40.0


class ProposalWriter:
    """
    LLM-powered cover letter generator.

    Retrieves relevant past proposals via RAG, then prompts the LLM to
    write a personalised proposal in the proven hook-plan-proof-fit-CTA
    structure. Falls back to a conservative cover letter on any failure.
    """

    def __init__(
        self,
        model: str,
        temperature: float,
        proposal_store: "ProposalStore",
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._proposal_store = proposal_store

    async def write(
        self,
        job: "Job",
        profile: "UserProfile",
        strategy: "BidStrategy",
        score: "CompositeScore",
    ) -> ProposalDraft:
        """
        Generate a ProposalDraft for the given job + bid strategy.

        Returns a draft with a conservative cover letter on LLM failure
        so the pipeline never blocks on generation.
        """
        from decimal import Decimal

        past_proposals = self._proposal_store.query(job)
        prompt = _build_prompt(job, profile, strategy, score, past_proposals)

        cover_letter = _CONSERVATIVE_COVER_LETTER
        questions: list[str] = []
        llm_confidence = 40.0

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
            )
            content: str = response.choices[0].message.content or ""
            if content:
                cover_letter, questions, llm_confidence = _parse_draft(content)
        except Exception:
            logger.exception(
                "ProposalWriter LLM call failed for job %s — using fallback",
                job.id,
            )

        return ProposalDraft(
            job_id=job.id,
            platform=job.platform,
            platform_job_id=job.platform_job_id,
            bid_type=strategy.bid_type or "hourly",
            bid_amount=strategy.proposed_rate or Decimal("0"),
            cover_letter=cover_letter,
            questions_answers={q: "" for q in questions},
            confidence=llm_confidence,
            positioning_angle=strategy.positioning_angle or "",
        )
