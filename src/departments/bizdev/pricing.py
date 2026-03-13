"""
Rule-based pricing engine for the BizDev department.

Pure function — no I/O, no LLM calls, no side effects. Must complete in <5ms.
Computes an optimal bid price from job data, freelancer profile, analyst score,
and optional historical win records. Returns a BidPrice with a viability flag.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.config import UserProfile
from src.models.bid import WinRecord
from src.models.job import Job, JobType
from src.models.score import CompositeScore


@dataclass(frozen=True)
class BidPrice:
    """Computed bid recommendation from the pricing engine."""

    bid_type: str           # "hourly" | "fixed"
    amount: float           # suggested bid rate or price
    rate_range: tuple[float, float]  # (floor, ceiling) for negotiation
    viable: bool            # False → caller should pass on this job
    reasoning: str          # human-readable explanation


def _competition_discount(proposals_count: int | None) -> float:
    """Return a multiplicative discount factor based on proposal volume."""
    if proposals_count is None:
        return 1.0
    if proposals_count >= 50:
        return 0.85
    if proposals_count >= 20:
        return 0.90
    if proposals_count >= 10:
        return 0.95
    return 1.0


def _win_prob_premium(win_probability: float) -> float:
    """Return a multiplicative premium when win probability is high."""
    if win_probability >= 80:
        return 1.08
    if win_probability >= 70:
        return 1.05
    return 1.0


def _historical_anchor(
    win_history: list[WinRecord],
    job_type: str,
) -> float | None:
    """
    Compute average winning bid amount for the same job type.

    Returns None when no relevant history is available.
    """
    relevant = [r.bid_amount for r in win_history if r.job_type == job_type and r.was_won]
    if not relevant:
        return None
    return sum(relevant) / len(relevant)


def _compute_hourly(
    job: Job,
    profile: UserProfile,
    score: CompositeScore,
    win_history: list[WinRecord],
) -> BidPrice:
    profile_min = profile.hourly_rate_min
    profile_max = profile.hourly_rate_max
    profile_mid = (profile_min + profile_max) / 2.0

    # Hard bid ceiling — only when the client explicitly stated a maximum rate.
    # hourly_rate_min alone means "$X+/hr": a client floor, not a bid ceiling.
    # When only a minimum is given, job_max stays None and the profile ceiling governs.
    job_max: float | None = (
        float(job.hourly_rate_max) if job.hourly_rate_max is not None else None
    )

    # Hard viability check
    if job_max is not None and job_max < profile_min * 0.75:
        return BidPrice(
            bid_type="hourly",
            amount=job_max,
            rate_range=(job_max, job_max),
            viable=False,
            reasoning=(
                f"Job ceiling ${job_max:.0f}/hr is below 75% of profile minimum "
                f"${profile_min:.0f}/hr — not viable."
            ),
        )

    # Start at profile midpoint; cap below explicit ceiling to be competitive
    base = profile_mid
    if job_max is not None and job_max < base:
        base = job_max * 0.95

    # Apply adjustments
    base *= _competition_discount(job.proposals_count)
    base *= _win_prob_premium(score.deep_score.win_probability)

    # Nudge toward historical winning rate (20% weight)
    anchor = _historical_anchor(win_history, "hourly")
    if anchor is not None:
        base = base * 0.80 + anchor * 0.20

    # Clamp to sensible range — never exceed the client's stated maximum rate
    floor = max(profile_min * 0.80, 1.0)
    ceiling = profile_max * 1.10
    if job_max is not None:
        ceiling = min(ceiling, job_max)
    amount = max(floor, min(ceiling, base))

    # Guard: floor-ceiling inversion — job max falls between 75% and 80% of
    # profile_min, so floor > ceiling and amount ends up above the stated cap.
    if job_max is not None and amount > job_max:
        return BidPrice(
            bid_type="hourly",
            amount=job_max,
            rate_range=(job_max, job_max),
            viable=False,
            reasoning=(
                f"Job ceiling ${job_max:.0f}/hr falls below the minimum viable rate "
                f"${floor:.0f}/hr (80% of profile minimum ${profile_min:.0f}/hr) — not viable."
            ),
        )

    # Determine urgency-based rate range
    rate_floor = max(profile_min * 0.75, amount * 0.90)
    rate_ceil = min(amount * 1.10, ceiling)

    return BidPrice(
        bid_type="hourly",
        amount=round(amount, 2),
        rate_range=(round(rate_floor, 2), round(rate_ceil, 2)),
        viable=True,
        reasoning=(
            f"Suggested ${amount:.0f}/hr (profile mid ${profile_mid:.0f}/hr, "
            f"competition factor {_competition_discount(job.proposals_count):.0%}, "
            f"win-prob factor {_win_prob_premium(score.deep_score.win_probability):.0%})."
        ),
    )


def _compute_fixed(
    job: Job,
    profile: UserProfile,
    score: CompositeScore,
    win_history: list[WinRecord],
) -> BidPrice:
    profile_mid = (profile.hourly_rate_min + profile.hourly_rate_max) / 2.0
    minimum_viable = profile.hourly_rate_min * 20.0  # at least 20h worth

    # Determine base budget from job data
    budget_max: float | None = None
    if job.budget_max is not None:
        budget_max = float(job.budget_max)
    elif job.budget_min is not None:
        budget_max = float(job.budget_min) * 1.20  # extrapolate if only min known

    base = budget_max if budget_max is not None else profile_mid * 40.0

    # Hard viability check
    if base < minimum_viable:
        return BidPrice(
            bid_type="fixed",
            amount=base,
            rate_range=(base, base),
            viable=False,
            reasoning=(
                f"Budget ${base:.0f} is below minimum viable ${minimum_viable:.0f} "
                f"(profile min ${profile.hourly_rate_min:.0f}/hr × 20h)."
            ),
        )

    # Apply adjustments (same as hourly)
    base *= _competition_discount(job.proposals_count)
    base *= _win_prob_premium(score.deep_score.win_probability)

    anchor = _historical_anchor(win_history, "fixed")
    if anchor is not None:
        base = base * 0.80 + anchor * 0.20

    amount = max(minimum_viable, base)
    rate_floor = amount * 0.90
    rate_ceil = amount * 1.15

    return BidPrice(
        bid_type="fixed",
        amount=round(amount, 2),
        rate_range=(round(rate_floor, 2), round(rate_ceil, 2)),
        viable=True,
        reasoning=(
            f"Suggested ${amount:.0f} fixed (budget ref ${budget_max or 'N/A'}, "
            f"competition factor {_competition_discount(job.proposals_count):.0%})."
        ),
    )


def compute_bid_price(
    job: Job,
    profile: UserProfile,
    score: CompositeScore,
    win_history: list[WinRecord],
) -> BidPrice:
    """
    Compute an optimal bid price for a job opportunity.

    Returns a BidPrice with viable=False when the job cannot be priced
    within the freelancer's acceptable range — the caller should pass.
    """
    if job.job_type == JobType.HOURLY:
        return _compute_hourly(job, profile, score, win_history)
    return _compute_fixed(job, profile, score, win_history)
