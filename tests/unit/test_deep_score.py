"""
Unit tests for src/departments/analyst/deep_score.py.

Covers LLM response parsing, prompt construction, budget formatting,
and DeepScorer resilience to malformed/missing LLM output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import UserProfile
from src.departments.analyst.deep_score import (
    DeepScorer,
    _build_prompt,
    _format_budget,
    _parse_llm_response,
)
from src.models.job import ExperienceLevel, Job, JobStatus, JobType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)

_PROFILE = UserProfile(
    name="Jane Dev",
    skills=["Python", "FastAPI", "PostgreSQL"],
    hourly_rate_min=60.0,
    hourly_rate_max=120.0,
    experience_level="expert",
)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "platform": "upwork",
        "platform_job_id": "test-deep-001",
        "url": "https://upwork.com/jobs/test",
        "title": "Backend Python Developer",
        "description": "Build a FastAPI service.",
        "job_type": JobType.HOURLY,
        "experience_level": ExperienceLevel.EXPERT,
        "hourly_rate_min": Decimal("70"),
        "hourly_rate_max": Decimal("110"),
        "required_skills": ["Python", "FastAPI"],
        "client_rating": 4.8,
        "client_total_spent": Decimal("25000"),
        "proposals_count": 7,
        "posted_at": _NOW - timedelta(hours=2),
        "status": JobStatus.DISCOVERED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


_VALID_LLM_JSON = (
    '{"relevance": 85, "feasibility": 70, "profitability": 60, '
    '"win_probability": 75, "reasoning": "Good match.", '
    '"red_flags": ["tight deadline"]}'
)


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_valid_json(self) -> None:
        data = _parse_llm_response(_VALID_LLM_JSON)
        assert data["relevance"] == 85
        assert data["reasoning"] == "Good match."
        assert data["red_flags"] == ["tight deadline"]

    def test_json_with_preamble(self) -> None:
        content = 'Here is the analysis:\n\n' + _VALID_LLM_JSON
        data = _parse_llm_response(content)
        assert data["relevance"] == 85

    def test_json_with_trailing_text(self) -> None:
        content = _VALID_LLM_JSON + '\n\nHope this helps!'
        data = _parse_llm_response(content)
        assert data["relevance"] == 85

    def test_no_json_returns_conservative(self) -> None:
        data = _parse_llm_response("No JSON here at all.")
        assert data["relevance"] == 50
        assert data["feasibility"] == 50
        assert "conservative" in str(data["reasoning"]).lower() or "failure" in str(data["reasoning"]).lower()

    def test_invalid_json_returns_conservative(self) -> None:
        data = _parse_llm_response("{invalid json content}")
        assert data["relevance"] == 50
        assert data["feasibility"] == 50

    def test_empty_string_returns_conservative(self) -> None:
        data = _parse_llm_response("")
        assert data["relevance"] == 50


# ---------------------------------------------------------------------------
# _format_budget
# ---------------------------------------------------------------------------


class TestFormatBudget:
    def test_hourly_with_both_rates(self) -> None:
        job = _make_job(job_type=JobType.HOURLY, hourly_rate_min=Decimal("50"), hourly_rate_max=Decimal("100"))
        assert _format_budget(job) == "$50-$100/hr"

    def test_hourly_missing_min(self) -> None:
        job = _make_job(job_type=JobType.HOURLY, hourly_rate_min=None, hourly_rate_max=Decimal("100"))
        assert _format_budget(job) == "?-$100/hr"

    def test_hourly_missing_max(self) -> None:
        job = _make_job(job_type=JobType.HOURLY, hourly_rate_min=Decimal("50"), hourly_rate_max=None)
        assert _format_budget(job) == "$50-?/hr"

    def test_fixed_with_both_budgets(self) -> None:
        job = _make_job(
            job_type=JobType.FIXED,
            budget_min=Decimal("1000"),
            budget_max=Decimal("5000"),
            hourly_rate_min=None,
            hourly_rate_max=None,
        )
        assert _format_budget(job) == "$1000-$5000 fixed"

    def test_fixed_missing_both(self) -> None:
        job = _make_job(
            job_type=JobType.FIXED,
            budget_min=None,
            budget_max=None,
            hourly_rate_min=None,
            hourly_rate_max=None,
        )
        assert _format_budget(job) == "?-? fixed"


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_contains_profile_skills(self) -> None:
        prompt = _build_prompt(_make_job(), _PROFILE)
        assert "Python" in prompt
        assert "FastAPI" in prompt
        assert "PostgreSQL" in prompt

    def test_contains_job_title(self) -> None:
        job = _make_job(title="Senior ML Engineer")
        prompt = _build_prompt(job, _PROFILE)
        assert "Senior ML Engineer" in prompt

    def test_contains_rate_range(self) -> None:
        prompt = _build_prompt(_make_job(), _PROFILE)
        assert "$60" in prompt
        assert "$120" in prompt

    def test_truncates_long_description(self) -> None:
        job = _make_job(description="x" * 5000)
        prompt = _build_prompt(job, _PROFILE)
        # Description capped at 2000 chars
        assert "x" * 2000 in prompt
        assert "x" * 2001 not in prompt

    def test_empty_skills_shows_not_specified(self) -> None:
        profile = UserProfile(name="Test", skills=[])
        prompt = _build_prompt(_make_job(), profile)
        assert "not specified" in prompt

    def test_no_required_skills_shows_none_listed(self) -> None:
        job = _make_job(required_skills=[])
        prompt = _build_prompt(job, _PROFILE)
        assert "none listed" in prompt

    def test_missing_experience_level(self) -> None:
        job = _make_job(experience_level=None)
        prompt = _build_prompt(job, _PROFILE)
        assert "not specified" in prompt

    def test_missing_client_rating(self) -> None:
        job = _make_job(client_rating=None)
        prompt = _build_prompt(job, _PROFILE)
        assert "unknown" in prompt


# ---------------------------------------------------------------------------
# DeepScorer.score
# ---------------------------------------------------------------------------


class TestDeepScorerScore:
    @pytest.fixture
    def scorer(self) -> DeepScorer:
        return DeepScorer(model="test-model", temperature=0.3)

    @pytest.mark.asyncio
    async def test_valid_llm_response(self, scorer: DeepScorer) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = _VALID_LLM_JSON

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.relevance == 85.0
        assert result.feasibility == 70.0
        assert result.profitability == 60.0
        assert result.win_probability == 75.0
        assert result.reasoning == "Good match."
        assert result.red_flags == ["tight deadline"]

    @pytest.mark.asyncio
    async def test_llm_exception_returns_conservative(self, scorer: DeepScorer) -> None:
        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=RuntimeError("API down"))
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.relevance == 50.0
        assert result.feasibility == 50.0
        assert result.profitability == 50.0
        assert result.win_probability == 50.0

    @pytest.mark.asyncio
    async def test_empty_llm_response(self, scorer: DeepScorer) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = ""

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.relevance == 50.0
        assert result.feasibility == 50.0

    @pytest.mark.asyncio
    async def test_non_numeric_scores_fallback(self, scorer: DeepScorer) -> None:
        """LLM returns string values like 'high' instead of numbers."""
        content = (
            '{"relevance": "high", "feasibility": "medium", '
            '"profitability": null, "win_probability": [1,2,3], '
            '"reasoning": "test", "red_flags": []}'
        )
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = content

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        # All non-numeric values should fall back to 50.0
        assert result.relevance == 50.0
        assert result.feasibility == 50.0
        assert result.profitability == 50.0
        assert result.win_probability == 50.0

    @pytest.mark.asyncio
    async def test_scores_clamped_to_range(self, scorer: DeepScorer) -> None:
        """Scores outside 0-100 are clamped."""
        content = (
            '{"relevance": 150, "feasibility": -20, '
            '"profitability": 100, "win_probability": 0, '
            '"reasoning": "test", "red_flags": []}'
        )
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = content

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.relevance == 100.0
        assert result.feasibility == 0.0
        assert result.profitability == 100.0
        assert result.win_probability == 0.0

    @pytest.mark.asyncio
    async def test_non_list_red_flags_ignored(self, scorer: DeepScorer) -> None:
        """red_flags as a string instead of list should produce empty list."""
        content = (
            '{"relevance": 70, "feasibility": 70, '
            '"profitability": 70, "win_probability": 70, '
            '"reasoning": "test", "red_flags": "some flag"}'
        )
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = content

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.red_flags == []

    @pytest.mark.asyncio
    async def test_missing_red_flags_key(self, scorer: DeepScorer) -> None:
        """Missing red_flags key should produce empty list."""
        content = (
            '{"relevance": 70, "feasibility": 70, '
            '"profitability": 70, "win_probability": 70, '
            '"reasoning": "test"}'
        )
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = content

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.red_flags == []

    @pytest.mark.asyncio
    async def test_none_content_returns_conservative(self, scorer: DeepScorer) -> None:
        """message.content is None."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = None

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.relevance == 50.0
        assert result.feasibility == 50.0

    @pytest.mark.asyncio
    async def test_result_has_job_id(self, scorer: DeepScorer) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = _VALID_LLM_JSON

        job = _make_job()
        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(job, _PROFILE)

        assert result.job_id == job.id

    @pytest.mark.asyncio
    async def test_result_has_scored_at(self, scorer: DeepScorer) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = _VALID_LLM_JSON

        with patch("src.departments.analyst.deep_score.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await scorer.score(_make_job(), _PROFILE)

        assert result.scored_at is not None
        assert result.scored_at.tzinfo is not None
