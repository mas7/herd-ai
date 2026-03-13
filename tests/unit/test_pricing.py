"""
Unit tests for src/departments/bizdev/pricing.py.

Covers all code paths of the rule-based pricing engine:
  - _competition_discount
  - _win_prob_premium
  - _historical_anchor
  - compute_bid_price → hourly (viable / not-viable)
  - compute_bid_price → fixed  (viable / not-viable, all base-budget branches)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.config import UserProfile
from src.departments.bizdev.pricing import (
    _competition_discount,
    _historical_anchor,
    _win_prob_premium,
    compute_bid_price,
)
from src.models.bid import WinRecord
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import CompositeScore, DeepScore, FastScore

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _make_profile(min_rate: float = 60.0, max_rate: float = 120.0) -> UserProfile:
    return UserProfile(
        name="Test",
        skills=["Python"],
        hourly_rate_min=min_rate,
        hourly_rate_max=max_rate,
    )


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-pricing-001",
        "platform": "upwork",
        "platform_job_id": "pricing-001",
        "url": "https://upwork.com/jobs/pricing",
        "title": "Pricing Test Job",
        "description": "Test job for pricing engine.",
        "job_type": JobType.HOURLY,
        "experience_level": ExperienceLevel.EXPERT,
        "hourly_rate_min": Decimal("80"),
        "hourly_rate_max": Decimal("120"),
        "required_skills": ["Python"],
        "proposals_count": 5,
        "posted_at": _NOW - timedelta(hours=1),
        "status": JobStatus.SCORED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def _make_score(win_probability: float = 60.0) -> CompositeScore:
    fast = FastScore(
        job_id="job-pricing-001",
        total=70.0,
        breakdown={},
        pass_threshold=True,
    )
    deep = DeepScore(
        job_id="job-pricing-001",
        relevance=70.0,
        feasibility=70.0,
        profitability=70.0,
        win_probability=win_probability,
        reasoning="ok",
    )
    return CompositeScore(
        job_id="job-pricing-001",
        fast_score=fast,
        deep_score=deep,
        final_score=70.0,
        recommendation="pursue",
    )


def _wins(job_type: str, amounts: list[float]) -> list[WinRecord]:
    return [WinRecord(bid_amount=a, job_type=job_type, was_won=True) for a in amounts]


# ---------------------------------------------------------------------------
# _competition_discount
# ---------------------------------------------------------------------------


class TestCompetitionDiscount:
    def test_none_proposals(self) -> None:
        assert _competition_discount(None) == 1.0

    def test_zero_proposals(self) -> None:
        assert _competition_discount(0) == 1.0

    def test_below_ten(self) -> None:
        assert _competition_discount(9) == 1.0

    def test_boundary_ten(self) -> None:
        assert _competition_discount(10) == 0.95

    def test_ten_to_nineteen(self) -> None:
        assert _competition_discount(19) == 0.95

    def test_boundary_twenty(self) -> None:
        assert _competition_discount(20) == 0.90

    def test_twenty_to_fortynine(self) -> None:
        assert _competition_discount(49) == 0.90

    def test_boundary_fifty(self) -> None:
        assert _competition_discount(50) == 0.85

    def test_above_fifty(self) -> None:
        assert _competition_discount(100) == 0.85


# ---------------------------------------------------------------------------
# _win_prob_premium
# ---------------------------------------------------------------------------


class TestWinProbPremium:
    def test_below_70_no_premium(self) -> None:
        assert _win_prob_premium(0.0) == 1.0
        assert _win_prob_premium(69.9) == 1.0

    def test_boundary_70(self) -> None:
        assert _win_prob_premium(70.0) == 1.05

    def test_70_to_79(self) -> None:
        assert _win_prob_premium(79.9) == 1.05

    def test_boundary_80(self) -> None:
        assert _win_prob_premium(80.0) == 1.08

    def test_above_80(self) -> None:
        assert _win_prob_premium(100.0) == 1.08


# ---------------------------------------------------------------------------
# _historical_anchor
# ---------------------------------------------------------------------------


class TestHistoricalAnchor:
    def test_empty_history_returns_none(self) -> None:
        assert _historical_anchor([], "hourly") is None

    def test_no_matching_type_returns_none(self) -> None:
        records = [WinRecord(bid_amount=100.0, job_type="fixed", was_won=True)]
        assert _historical_anchor(records, "hourly") is None

    def test_only_lost_records_returns_none(self) -> None:
        records = [WinRecord(bid_amount=100.0, job_type="hourly", was_won=False)]
        assert _historical_anchor(records, "hourly") is None

    def test_single_winning_record(self) -> None:
        records = [WinRecord(bid_amount=90.0, job_type="hourly", was_won=True)]
        assert _historical_anchor(records, "hourly") == pytest.approx(90.0)

    def test_averages_multiple_wins(self) -> None:
        records = [
            WinRecord(bid_amount=80.0, job_type="hourly", was_won=True),
            WinRecord(bid_amount=100.0, job_type="hourly", was_won=True),
            WinRecord(bid_amount=90.0, job_type="hourly", was_won=False),  # excluded
        ]
        # average of 80 and 100 = 90
        assert _historical_anchor(records, "hourly") == pytest.approx(90.0)

    def test_mixed_types_only_averages_matching(self) -> None:
        records = [
            WinRecord(bid_amount=100.0, job_type="hourly", was_won=True),
            WinRecord(bid_amount=5000.0, job_type="fixed", was_won=True),
        ]
        assert _historical_anchor(records, "hourly") == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# compute_bid_price — hourly
# ---------------------------------------------------------------------------


class TestComputeBidPriceHourly:
    def test_not_viable_when_ceiling_below_75pct_of_profile_min(self) -> None:
        """Job ceiling < profile_min * 0.75 returns viable=False."""
        profile = _make_profile(min_rate=100.0, max_rate=150.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=None,
            hourly_rate_max=Decimal("70"),  # 70 < 100 * 0.75 = 75
        )
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is False
        assert result.bid_type == "hourly"
        assert "not viable" in result.reasoning

    def test_viable_with_normal_ceiling(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(job_type=JobType.HOURLY)
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True
        assert result.bid_type == "hourly"
        assert result.amount > 0

    def test_no_ceiling_still_viable(self) -> None:
        """Job without any hourly rate info is priced using profile mid."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=None,
            hourly_rate_max=None,
        )
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True
        assert result.amount == pytest.approx(90.0, rel=0.1)  # near profile mid

    def test_only_min_rate_given_used_as_ceiling(self) -> None:
        """When only hourly_rate_min is set, it acts as the ceiling."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=Decimal("95"),
            hourly_rate_max=None,
        )
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True
        assert result.amount <= 95.0

    def test_amount_clamped_to_floor(self) -> None:
        """Amount never goes below profile_min * 0.80."""
        profile = _make_profile(min_rate=60.0, max_rate=70.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_max=Decimal("65"),
            proposals_count=50,  # 0.85 discount
        )
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True
        assert result.amount >= 60.0 * 0.80  # floor

    def test_amount_clamped_to_ceiling(self) -> None:
        """Amount never exceeds profile_max * 1.10."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_max=Decimal("200"),  # well above profile max
        )
        result = compute_bid_price(job, profile, _make_score(win_probability=90.0), [])
        assert result.amount <= 120.0 * 1.10

    def test_competition_discount_lowers_amount(self) -> None:
        """More proposals → lower bid."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        score = _make_score()
        job_few = _make_job(job_type=JobType.HOURLY, proposals_count=5)
        job_many = _make_job(job_type=JobType.HOURLY, proposals_count=55)
        result_few = compute_bid_price(job_few, profile, score, [])
        result_many = compute_bid_price(job_many, profile, score, [])
        assert result_many.amount < result_few.amount

    def test_win_prob_premium_raises_amount(self) -> None:
        """Higher win probability → higher bid."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(job_type=JobType.HOURLY, proposals_count=5)
        result_low = compute_bid_price(job, profile, _make_score(win_probability=50.0), [])
        result_high = compute_bid_price(job, profile, _make_score(win_probability=85.0), [])
        assert result_high.amount > result_low.amount

    def test_high_historical_anchor_nudges_amount_up(self) -> None:
        """High historical winning rate nudges bid higher."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(job_type=JobType.HOURLY, proposals_count=5)
        score = _make_score(win_probability=60.0)
        no_history = compute_bid_price(job, profile, score, [])
        high_history = compute_bid_price(job, profile, score, _wins("hourly", [200.0, 200.0]))
        assert high_history.amount >= no_history.amount

    def test_low_historical_anchor_nudges_amount_down(self) -> None:
        """Low historical winning rate nudges bid lower."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(job_type=JobType.HOURLY, proposals_count=5)
        score = _make_score(win_probability=60.0)
        no_history = compute_bid_price(job, profile, score, [])
        low_history = compute_bid_price(job, profile, score, _wins("hourly", [48.0, 48.0]))
        assert low_history.amount <= no_history.amount

    def test_amount_never_exceeds_client_ceiling_after_premium(self) -> None:
        """Bid stays at or below client's stated max even with win-prob premium applied."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_max=Decimal("80"),  # tight ceiling
        )
        # High win probability would push above 80 without the ceiling clamp
        result = compute_bid_price(job, profile, _make_score(win_probability=90.0), [])
        assert result.viable is True
        assert result.amount <= 80.0

    def test_rate_range_floor_le_ceil(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        result = compute_bid_price(_make_job(job_type=JobType.HOURLY), profile, _make_score(), [])
        assert result.rate_range[0] <= result.rate_range[1]

    def test_reasoning_is_non_empty(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        result = compute_bid_price(_make_job(job_type=JobType.HOURLY), profile, _make_score(), [])
        assert len(result.reasoning) > 0


# ---------------------------------------------------------------------------
# compute_bid_price — fixed
# ---------------------------------------------------------------------------


class TestComputeBidPriceFixed:
    def _fixed_job(self, **overrides: object) -> Job:
        defaults: dict[str, object] = {
            "id": "job-fixed-001",
            "platform": "upwork",
            "platform_job_id": "fixed-001",
            "url": "https://upwork.com/jobs/fixed",
            "title": "Fixed Price Job",
            "description": "A fixed-price project.",
            "job_type": JobType.FIXED,
            "experience_level": ExperienceLevel.INTERMEDIATE,
            "hourly_rate_min": None,
            "hourly_rate_max": None,
            "budget_max": Decimal("3000"),
            "required_skills": ["Python"],
            "proposals_count": 5,
            "posted_at": _NOW - timedelta(hours=1),
            "status": JobStatus.SCORED,
        }
        defaults.update(overrides)
        return Job(**defaults)  # type: ignore[arg-type]

    def test_not_viable_when_budget_below_minimum(self) -> None:
        """Budget < profile_min * 20h → not viable."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        # minimum_viable = 60 * 20 = 1200
        job = self._fixed_job(budget_max=Decimal("500"))
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is False
        assert result.bid_type == "fixed"
        assert "minimum viable" in result.reasoning.lower() or "below" in result.reasoning.lower()

    def test_viable_with_sufficient_budget(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = self._fixed_job(budget_max=Decimal("2000"))
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True
        assert result.bid_type == "fixed"
        assert result.amount >= 60.0 * 20.0  # at least minimum_viable

    def test_fallback_when_no_budget_info(self) -> None:
        """No budget fields → falls back to profile_mid * 40h."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        # profile_mid = 90.0 → fallback = 90 * 40 = 3600 → viable
        job = self._fixed_job(budget_min=None, budget_max=None)
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True

    def test_budget_min_extrapolated_as_1_20(self) -> None:
        """Only budget_min given → extrapolated as budget_min * 1.20."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        # budget_min=1500 → base = 1500 * 1.20 = 1800 > 1200 → viable
        job = self._fixed_job(budget_min=Decimal("1500"), budget_max=None)
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is True

    def test_budget_min_too_low_after_extrapolation(self) -> None:
        """Even after 1.20× extrapolation, too-low budget is not viable."""
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        # 300 * 1.20 = 360 < 1200 → not viable
        job = self._fixed_job(budget_min=Decimal("300"), budget_max=None)
        result = compute_bid_price(job, profile, _make_score(), [])
        assert result.viable is False

    def test_competition_discount_lowers_amount(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        score = _make_score()
        job_few = self._fixed_job(budget_max=Decimal("5000"), proposals_count=3)
        job_many = self._fixed_job(budget_max=Decimal("5000"), proposals_count=50)
        result_few = compute_bid_price(job_few, profile, score, [])
        result_many = compute_bid_price(job_many, profile, score, [])
        assert result_many.amount <= result_few.amount

    def test_historical_anchor_applied(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        job = self._fixed_job(budget_max=Decimal("5000"))
        score = _make_score()
        no_hist = compute_bid_price(job, profile, score, [])
        high_hist = compute_bid_price(job, profile, score, _wins("fixed", [8000.0, 8000.0]))
        assert high_hist.amount >= no_hist.amount

    def test_rate_range_brackets_amount(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        result = compute_bid_price(self._fixed_job(), profile, _make_score(), [])
        assert result.rate_range[0] < result.amount
        assert result.rate_range[1] > result.amount

    def test_reasoning_is_non_empty(self) -> None:
        profile = _make_profile(min_rate=60.0, max_rate=120.0)
        result = compute_bid_price(self._fixed_job(), profile, _make_score(), [])
        assert len(result.reasoning) > 0
