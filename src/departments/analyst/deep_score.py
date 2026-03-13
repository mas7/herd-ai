"""
LLM-powered deep scorer for the Analyst department.

Uses litellm for model-agnostic LLM calls so the underlying model is
swappable via config without changing this module.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import litellm

from src.core.config import UserProfile
from src.models.job import Job
from src.models.score import DeepScore

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a freelance job analyst. Evaluate this job opportunity for the freelancer.

FREELANCER PROFILE:
- Skills: {skills}
- Experience: {experience_level}
- Rate: ${hourly_rate_min}-${hourly_rate_max}/hr

JOB POSTING:
- Title: {title}
- Description: {description}
- Type: {job_type}
- Budget: {budget}
- Required Skills: {required_skills}
- Experience Level: {experience_level_job}
- Proposals: {proposals_count}
- Client Rating: {client_rating}
- Client Spend: {client_total_spent}

Score this job on four dimensions (0-100 each):
1. Relevance: How well does this match the freelancer's skills?
2. Feasibility: Can this be delivered successfully?
3. Profitability: Is the compensation worth the effort?
4. Win Probability: How likely is the freelancer to win this bid?

Also identify any red flags (unrealistic scope, low budget, unclear requirements, etc).

Respond in JSON only:
{{
  "relevance": <int>,
  "feasibility": <int>,
  "profitability": <int>,
  "win_probability": <int>,
  "reasoning": "<2-3 sentence analysis>",
  "red_flags": ["<flag1>", "<flag2>"]
}}"""

_CONSERVATIVE_SCORES = {
    "relevance": 50,
    "feasibility": 50,
    "profitability": 50,
    "win_probability": 50,
    "reasoning": "LLM parse failure — conservative scores applied.",
    "red_flags": [],
}


def _format_budget(job: Job) -> str:
    """Return a human-readable budget string from job fields."""
    if job.job_type.value == "hourly":
        lo = f"${job.hourly_rate_min}" if job.hourly_rate_min else "?"
        hi = f"${job.hourly_rate_max}" if job.hourly_rate_max else "?"
        return f"{lo}-{hi}/hr"
    lo = f"${job.budget_min}" if job.budget_min else "?"
    hi = f"${job.budget_max}" if job.budget_max else "?"
    return f"{lo}-{hi} fixed"


def _build_prompt(job: Job, profile: UserProfile) -> str:
    return _PROMPT_TEMPLATE.format(
        skills=", ".join(profile.skills) if profile.skills else "not specified",
        experience_level=profile.experience_level,
        hourly_rate_min=profile.hourly_rate_min,
        hourly_rate_max=profile.hourly_rate_max,
        title=job.title,
        description=job.description[:2000],  # cap to avoid token bloat
        job_type=job.job_type.value,
        budget=_format_budget(job),
        required_skills=", ".join(job.required_skills) if job.required_skills else "none listed",
        experience_level_job=job.experience_level.value if job.experience_level else "not specified",
        proposals_count=job.proposals_count if job.proposals_count is not None else "unknown",
        client_rating=job.client_rating if job.client_rating is not None else "unknown",
        client_total_spent=f"${job.client_total_spent}" if job.client_total_spent else "unknown",
    )


def _parse_llm_response(content: str) -> dict[str, object]:
    """
    Extract the JSON object from the LLM response.

    Tolerates preamble text before the JSON by scanning for the first '{'.
    Falls back to conservative scores on any parse failure.
    """
    start = content.find("{")
    end = content.rfind("}") + 1
    if start == -1 or end == 0:
        logger.warning("No JSON object found in LLM response")
        return dict(_CONSERVATIVE_SCORES)

    try:
        return json.loads(content[start:end])
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON: %s", content[:200])
        return dict(_CONSERVATIVE_SCORES)


class DeepScorer:
    """
    LLM-powered semantic scorer.

    Sends a structured prompt to the configured LLM and parses the
    JSON response into a DeepScore. Uses litellm for provider-agnostic
    model routing.
    """

    def __init__(self, model: str, temperature: float) -> None:
        self._model = model
        self._temperature = temperature

    async def score(self, job: Job, profile: UserProfile) -> DeepScore:
        """
        Run the deep-scoring LLM call and return a structured DeepScore.

        On any LLM or parse failure, returns conservative 50-point scores
        so the pipeline can continue without crashing.
        """
        prompt = _build_prompt(job, profile)

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
            content: str = response.choices[0].message.content or ""
        except Exception:
            logger.exception("LLM call failed for job %s — using conservative scores", job.id)
            content = ""

        data = _parse_llm_response(content) if content else dict(_CONSERVATIVE_SCORES)

        def _safe_float(v: object, default: float = 50.0) -> float:
            try:
                return max(0.0, min(100.0, float(v)))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        raw_flags = data.get("red_flags")
        flags: list[str] = (
            [str(f) for f in raw_flags]
            if isinstance(raw_flags, list)
            else []
        )

        return DeepScore(
            job_id=job.id,
            relevance=_safe_float(data.get("relevance", 50)),
            feasibility=_safe_float(data.get("feasibility", 50)),
            profitability=_safe_float(data.get("profitability", 50)),
            win_probability=_safe_float(data.get("win_probability", 50)),
            reasoning=str(data.get("reasoning", _CONSERVATIVE_SCORES["reasoning"])),
            red_flags=flags,
            scored_at=datetime.now(timezone.utc),
        )
