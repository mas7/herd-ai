"""
Rule-based fast scorer for the Analyst department.

Pure function — no I/O, no LLM calls, no side effects. Must complete in <100ms.
Evaluates five weighted dimensions and returns a FastScore with a pass/fail flag.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.core.config import ScoringWeights, UserProfile
from src.models.job import Job, JobType
from src.models.score import FastScore


def _score_skill_match(job: Job, profile: UserProfile) -> float:
    """Percentage of required skills present in the freelancer's profile."""
    if not job.required_skills:
        return 50.0

    profile_skills_lower = {s.lower() for s in profile.skills}
    matched = sum(
        1 for skill in job.required_skills
        if skill.lower() in profile_skills_lower
    )
    return (matched / len(job.required_skills)) * 100.0


def _score_budget_fit(job: Job, profile: UserProfile) -> float:
    """How well the job's compensation aligns with the freelancer's rate."""
    if job.job_type == JobType.HOURLY:
        job_min = float(job.hourly_rate_min) if job.hourly_rate_min is not None else None
        job_max = float(job.hourly_rate_max) if job.hourly_rate_max is not None else None
    else:
        # Fixed price: estimate effective hourly from budget, assume 10hr/week, 4 weeks
        budget_min = float(job.budget_min) if job.budget_min is not None else None
        budget_max = float(job.budget_max) if job.budget_max is not None else None
        estimated_hours = 40.0  # conservative fixed-price estimate
        job_min = budget_min / estimated_hours if budget_min is not None else None
        job_max = budget_max / estimated_hours if budget_max is not None else None

    if job_min is None and job_max is None:
        return 50.0

    # Use whichever endpoint we have
    rate = job_max if job_max is not None else job_min
    assert rate is not None  # narrowed above

    profile_min = profile.hourly_rate_min
    profile_max = profile.hourly_rate_max

    if rate >= profile_min:
        return 100.0
    if rate >= profile_min * 0.75:
        # Overlaps the lower boundary of user's range
        return 50.0
    return 0.0


def _score_client_quality(job: Job) -> float:
    """Aggregate client trustworthiness from rating, spend, and hire rate."""
    # Rating sub-score
    if job.client_rating is None:
        rating_score = 30.0
    elif job.client_rating < 3.0:
        rating_score = 20.0
    elif job.client_rating < 4.0:
        rating_score = 50.0
    elif job.client_rating < 4.5:
        rating_score = 70.0
    else:
        rating_score = 100.0

    # Total-spend sub-score
    spent = float(job.client_total_spent) if job.client_total_spent is not None else None
    if spent is None:
        spend_score = 20.0
    elif spent == 0.0:
        spend_score = 0.0
    elif spent < 1_000.0:
        spend_score = 30.0
    elif spent < 10_000.0:
        spend_score = 50.0
    elif spent < 100_000.0:
        spend_score = 70.0
    else:
        spend_score = 100.0

    # Hire-rate sub-score
    if job.client_hire_rate is None:
        hire_score = 50.0
    elif job.client_hire_rate < 0.30:
        hire_score = 30.0
    elif job.client_hire_rate < 0.60:
        hire_score = 50.0
    elif job.client_hire_rate < 0.80:
        hire_score = 70.0
    else:
        hire_score = 100.0

    return (rating_score + spend_score + hire_score) / 3.0


def _score_competition(job: Job) -> float:
    """Lower proposal counts mean less competition — better odds."""
    count = job.proposals_count
    if count is None:
        return 50.0
    if count < 5:
        return 100.0
    if count < 10:
        return 80.0
    if count < 20:
        return 60.0
    if count < 50:
        return 30.0
    return 10.0


def _score_freshness(job: Job) -> float:
    """Jobs posted more recently are more likely to still accept proposals."""
    now = datetime.now(timezone.utc)
    posted = job.posted_at
    # Ensure both are timezone-aware for subtraction
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)

    hours_old = (now - posted).total_seconds() / 3600.0

    if hours_old < 1:
        return 100.0
    if hours_old < 4:
        return 80.0
    if hours_old < 12:
        return 60.0
    if hours_old < 24:
        return 40.0
    if hours_old < 48:
        return 20.0
    return 10.0


def compute_fast_score(
    job: Job,
    profile: UserProfile,
    weights: ScoringWeights,
    threshold: float,
) -> FastScore:
    """
    Compute a rule-based fast score for a job opportunity.

    Each dimension is scored 0-100 then multiplied by its configured weight.
    The weighted sum becomes the total; pass_threshold is set when total >= threshold.
    """
    breakdown = {
        "skill_match": _score_skill_match(job, profile),
        "budget_fit": _score_budget_fit(job, profile),
        "client_quality": _score_client_quality(job),
        "competition": _score_competition(job),
        "freshness": _score_freshness(job),
    }

    total = (
        breakdown["skill_match"] * weights.skill_match
        + breakdown["budget_fit"] * weights.budget_fit
        + breakdown["client_quality"] * weights.client_quality
        + breakdown["competition"] * weights.competition
        + breakdown["freshness"] * weights.freshness
    )

    return FastScore(
        job_id=job.id,
        total=total,
        breakdown=breakdown,
        pass_threshold=total >= threshold,
    )
