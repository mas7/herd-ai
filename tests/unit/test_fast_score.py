"""
Unit tests for src/departments/analyst/fast_score.py.

Covers every scoring dimension plus edge cases, threshold boundary,
None-field resilience, and model immutability.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.config import ScoringWeights, UserProfile
from src.departments.analyst.fast_score import compute_fast_score
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import FastScore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WEIGHTS = ScoringWeights()  # default weights
_THRESHOLD = 40.0

_PROFILE = UserProfile(
    name="Jane Dev",
    skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
    hourly_rate_min=60.0,
    hourly_rate_max=120.0,
    experience_level="expert",
)

_NOW = datetime.now(timezone.utc)


def _make_job(**overrides: object) -> Job:
    """Return a base Job with all signals set to neutral/good values."""
    defaults: dict[str, object] = {
        "platform": "upwork",
        "platform_job_id": "test-job-001",
        "url": "https://upwork.com/jobs/test",
        "title": "Backend Python Developer",
        "description": "Build a FastAPI service backed by PostgreSQL.",
        "job_type": JobType.HOURLY,
        "experience_level": ExperienceLevel.EXPERT,
        "hourly_rate_min": Decimal("70"),
        "hourly_rate_max": Decimal("110"),
        "required_skills": ["Python", "FastAPI"],
        "client_rating": 4.8,
        "client_total_spent": Decimal("25000"),
        "client_hire_rate": 0.75,
        "proposals_count": 7,
        "posted_at": _NOW - timedelta(hours=2),
        "status": JobStatus.DISCOVERED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Composite score tests
# ---------------------------------------------------------------------------


class TestPerfectJob:
    def test_high_score_passes_threshold(self) -> None:
        job = _make_job(
            required_skills=["Python", "FastAPI"],
            hourly_rate_min=Decimal("80"),
            hourly_rate_max=Decimal("120"),
            client_rating=5.0,
            client_total_spent=Decimal("200000"),
            client_hire_rate=0.9,
            proposals_count=3,
            posted_at=_NOW - timedelta(minutes=30),
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.total > 70.0
        assert score.pass_threshold is True

    def test_breakdown_keys_present(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert set(score.breakdown.keys()) == {
            "skill_match", "budget_fit", "client_quality", "competition", "freshness"
        }

    def test_all_breakdown_values_in_range(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        for key, val in score.breakdown.items():
            assert 0.0 <= val <= 100.0, f"{key} = {val} out of [0, 100]"

    def test_total_is_weighted_sum(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        expected = (
            score.breakdown["skill_match"] * _WEIGHTS.skill_match
            + score.breakdown["budget_fit"] * _WEIGHTS.budget_fit
            + score.breakdown["client_quality"] * _WEIGHTS.client_quality
            + score.breakdown["competition"] * _WEIGHTS.competition
            + score.breakdown["freshness"] * _WEIGHTS.freshness
        )
        assert abs(score.total - expected) < 1e-9


class TestTerribleJob:
    def test_low_score_fails_threshold(self) -> None:
        job = _make_job(
            required_skills=["Java", "Rust", "Go"],  # none in profile
            hourly_rate_min=None,
            hourly_rate_max=None,
            budget_min=None,
            budget_max=None,
            client_rating=None,
            client_total_spent=None,
            client_hire_rate=None,
            proposals_count=60,
            posted_at=_NOW - timedelta(days=7),
            job_type=JobType.FIXED,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.total < 40.0
        assert score.pass_threshold is False


# ---------------------------------------------------------------------------
# Skill match
# ---------------------------------------------------------------------------


class TestSkillMatch:
    def test_full_match_scores_100(self) -> None:
        job = _make_job(required_skills=["Python", "FastAPI"])
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 100.0

    def test_partial_match(self) -> None:
        # Profile has Python + FastAPI + PostgreSQL + Docker (4 skills)
        # Job requires Python + FastAPI + Rust (3 skills — Rust not in profile)
        job = _make_job(required_skills=["Python", "FastAPI", "Rust"])
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert abs(score.breakdown["skill_match"] - (2 / 3 * 100)) < 0.01

    def test_no_match_scores_zero(self) -> None:
        job = _make_job(required_skills=["Java", "Rust", "Go"])
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 0.0

    def test_case_insensitive_matching(self) -> None:
        job = _make_job(required_skills=["python", "FASTAPI"])
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 100.0

    def test_no_required_skills_scores_neutral(self) -> None:
        job = _make_job(required_skills=[])
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 50.0


# ---------------------------------------------------------------------------
# Budget fit
# ---------------------------------------------------------------------------


class TestBudgetFit:
    def test_hourly_rate_in_range_scores_100(self) -> None:
        # Profile: $60-$120/hr; job: $80-$110/hr — well within range
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=Decimal("80"),
            hourly_rate_max=Decimal("110"),
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["budget_fit"] == 100.0

    def test_hourly_rate_above_range_scores_100(self) -> None:
        # Job pays more than user's max — still good
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=Decimal("130"),
            hourly_rate_max=Decimal("160"),
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["budget_fit"] == 100.0

    def test_hourly_rate_far_below_range_scores_zero(self) -> None:
        # Profile min: $60; job pays $15/hr — far below
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=Decimal("10"),
            hourly_rate_max=Decimal("15"),
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["budget_fit"] == 0.0

    def test_no_budget_info_scores_neutral(self) -> None:
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_min=None,
            hourly_rate_max=None,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["budget_fit"] == 50.0

    def test_fixed_price_with_good_budget(self) -> None:
        # $4000 fixed / 40 estimated hours = $100/hr — above profile min of $60
        job = _make_job(
            job_type=JobType.FIXED,
            budget_min=Decimal("3000"),
            budget_max=Decimal("4000"),
            hourly_rate_min=None,
            hourly_rate_max=None,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["budget_fit"] == 100.0


# ---------------------------------------------------------------------------
# Client quality
# ---------------------------------------------------------------------------


class TestClientQuality:
    def test_verified_high_spend_client_scores_high(self) -> None:
        job = _make_job(
            client_rating=4.9,
            client_total_spent=Decimal("150000"),
            client_hire_rate=0.85,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        # All three sub-scores are 100 → average is 100
        assert score.breakdown["client_quality"] == 100.0

    def test_new_client_no_signals_scores_low(self) -> None:
        job = _make_job(
            client_rating=None,
            client_total_spent=None,
            client_hire_rate=None,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        # rating→30, spend→20, hire→50 → avg = 33.33
        expected = (30.0 + 20.0 + 50.0) / 3.0
        assert abs(score.breakdown["client_quality"] - expected) < 0.01

    def test_bad_rating_client(self) -> None:
        job = _make_job(
            client_rating=2.5,
            client_total_spent=Decimal("500"),
            client_hire_rate=0.2,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        # rating→20, spend→30, hire→30 → avg = 26.67
        expected = (20.0 + 30.0 + 30.0) / 3.0
        assert abs(score.breakdown["client_quality"] - expected) < 0.01

    def test_zero_spend_client(self) -> None:
        job = _make_job(client_total_spent=Decimal("0"))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        # spend sub-score = 0
        assert score.breakdown["client_quality"] < 70.0

    def test_rating_boundary_3_to_4(self) -> None:
        job = _make_job(client_rating=3.5)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        # rating sub-score = 50; check it doesn't get 70 or 100
        assert score.breakdown["client_quality"] < 80.0


# ---------------------------------------------------------------------------
# Competition
# ---------------------------------------------------------------------------


class TestCompetition:
    def test_very_few_proposals_scores_100(self) -> None:
        job = _make_job(proposals_count=2)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["competition"] == 100.0

    def test_5_to_9_proposals_scores_80(self) -> None:
        job = _make_job(proposals_count=8)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["competition"] == 80.0

    def test_many_proposals_scores_low(self) -> None:
        job = _make_job(proposals_count=55)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["competition"] == 10.0

    def test_none_proposals_scores_neutral(self) -> None:
        job = _make_job(proposals_count=None)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["competition"] == 50.0

    def test_20_to_49_proposals_scores_30(self) -> None:
        job = _make_job(proposals_count=35)
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["competition"] == 30.0


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_just_posted_scores_100(self) -> None:
        job = _make_job(posted_at=_NOW - timedelta(minutes=10))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["freshness"] == 100.0

    def test_few_hours_old_scores_80(self) -> None:
        job = _make_job(posted_at=_NOW - timedelta(hours=2))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["freshness"] == 80.0

    def test_day_old_scores_40(self) -> None:
        job = _make_job(posted_at=_NOW - timedelta(hours=20))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["freshness"] == 40.0

    def test_week_old_scores_10(self) -> None:
        job = _make_job(posted_at=_NOW - timedelta(days=7))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["freshness"] == 10.0

    def test_12_to_24_hours_scores_40(self) -> None:
        job = _make_job(posted_at=_NOW - timedelta(hours=18))
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["freshness"] == 40.0

    def test_naive_datetime_handled_gracefully(self) -> None:
        naive_dt = datetime.now()  # no tzinfo
        job = _make_job(posted_at=naive_dt)
        # Should not raise
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert 0.0 <= score.breakdown["freshness"] <= 100.0


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------


class TestThresholdBoundary:
    def test_score_exactly_at_threshold_passes(self) -> None:
        """A job whose total equals the threshold exactly should pass."""
        job = _make_job(
            required_skills=[],  # skill_match→50
            hourly_rate_min=None,
            hourly_rate_max=None,  # budget_fit→50
            client_rating=None,
            client_total_spent=None,
            client_hire_rate=None,  # client_quality→(30+20+50)/3≈33.3
            proposals_count=None,  # competition→50
            posted_at=_NOW - timedelta(hours=2),  # freshness→80
        )
        # Compute the real total first with a threshold of 0 (always passes)
        real_score = compute_fast_score(job, _PROFILE, _WEIGHTS, threshold=0.0)
        # Now use the exact total as the threshold — should still pass (>=)
        result_at = compute_fast_score(job, _PROFILE, _WEIGHTS, threshold=real_score.total)
        assert result_at.pass_threshold is True

    def test_score_just_below_threshold_fails(self) -> None:
        real_score = compute_fast_score(_make_job(), _PROFILE, _WEIGHTS, threshold=0.0)
        result = compute_fast_score(
            _make_job(), _PROFILE, _WEIGHTS, threshold=real_score.total + 0.001
        )
        assert result.pass_threshold is False

    def test_zero_threshold_always_passes(self) -> None:
        job = _make_job(
            required_skills=["Java", "Rust"],
            hourly_rate_min=None,
            hourly_rate_max=None,
            client_rating=None,
            proposals_count=100,
            posted_at=_NOW - timedelta(days=30),
            job_type=JobType.FIXED,
        )
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, threshold=0.0)
        assert score.pass_threshold is True


# ---------------------------------------------------------------------------
# None / missing field resilience
# ---------------------------------------------------------------------------


class TestNoneFieldResilience:
    def test_all_optional_fields_none(self) -> None:
        job = _make_job(
            experience_level=None,
            budget_min=None,
            budget_max=None,
            hourly_rate_min=None,
            hourly_rate_max=None,
            client_country=None,
            client_rating=None,
            client_total_spent=None,
            client_hire_rate=None,
            client_jobs_posted=None,
            proposals_count=None,
        )
        # Must not raise
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert 0.0 <= score.total <= 100.0

    def test_empty_profile_skills(self) -> None:
        profile = UserProfile(skills=[], hourly_rate_min=60.0, hourly_rate_max=120.0)
        job = _make_job(required_skills=["Python", "FastAPI"])
        score = compute_fast_score(job, profile, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 0.0

    def test_job_with_no_skills_and_empty_profile_skills(self) -> None:
        profile = UserProfile(skills=[], hourly_rate_min=60.0, hourly_rate_max=120.0)
        job = _make_job(required_skills=[])
        score = compute_fast_score(job, profile, _WEIGHTS, _THRESHOLD)
        assert score.breakdown["skill_match"] == 50.0  # neutral


# ---------------------------------------------------------------------------
# Model immutability
# ---------------------------------------------------------------------------


class TestFastScoreImmutability:
    def test_fast_score_model_is_frozen(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert isinstance(score, FastScore)
        with pytest.raises(Exception):
            score.total = 99.9  # type: ignore[misc]

    def test_fast_score_breakdown_reflects_all_dimensions(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        for key in ("skill_match", "budget_fit", "client_quality", "competition", "freshness"):
            assert key in score.breakdown

    def test_returns_fast_score_instance(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert isinstance(score, FastScore)

    def test_job_id_matches(self) -> None:
        job = _make_job()
        score = compute_fast_score(job, _PROFILE, _WEIGHTS, _THRESHOLD)
        assert score.job_id == job.id
