"""
Unit tests for src/departments/content/writer.py.

Covers:
  - _format_budget (hourly and fixed)
  - _format_past_proposals (empty, with results, won prioritisation)
  - _parse_draft (valid JSON, malformed JSON, missing fields, fallback)
  - ProposalWriter.write (happy path, LLM failure fallback, empty content fallback)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import UserProfile
from src.departments.content.writer import (
    ProposalWriter,
    _CONSERVATIVE_COVER_LETTER,
    _format_budget,
    _format_past_proposals,
    _parse_draft,
)
from src.models.bid import BidStrategy
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import CompositeScore, DeepScore, FastScore

_NOW = datetime.now(timezone.utc)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-001",
        "platform": "upwork",
        "platform_job_id": "j001",
        "url": "https://upwork.com/jobs/j001",
        "title": "Build a FastAPI backend",
        "description": "We need a senior Python developer to build a REST API.",
        "job_type": JobType.HOURLY,
        "experience_level": ExperienceLevel.EXPERT,
        "hourly_rate_min": 50.0,
        "hourly_rate_max": 100.0,
        "required_skills": ["Python", "FastAPI"],
        "proposals_count": 5,
        "posted_at": _NOW,
        "discovered_at": _NOW,
        "status": JobStatus.BID_DECIDED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def _make_fixed_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-002",
        "platform": "upwork",
        "platform_job_id": "j002",
        "url": "https://upwork.com/jobs/j002",
        "title": "Build a landing page",
        "description": "Design and build a landing page.",
        "job_type": JobType.FIXED,
        "experience_level": ExperienceLevel.INTERMEDIATE,
        "budget_min": 200.0,
        "budget_max": 500.0,
        "required_skills": ["React", "CSS"],
        "proposals_count": 3,
        "posted_at": _NOW,
        "discovered_at": _NOW,
        "status": JobStatus.BID_DECIDED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def _make_strategy(**overrides: object) -> BidStrategy:
    defaults: dict[str, object] = {
        "job_id": "job-001",
        "should_bid": True,
        "bid_type": "hourly",
        "proposed_rate": Decimal("80"),
        "rate_range": (Decimal("75"), Decimal("90")),
        "positioning_angle": "My 5 years of FastAPI experience makes me the ideal fit.",
        "urgency": "normal",
        "confidence": 72.0,
        "reasoning": "Strong skill match, good budget.",
    }
    defaults.update(overrides)
    return BidStrategy(**defaults)  # type: ignore[arg-type]


def _make_score(**overrides: object) -> CompositeScore:
    deep = DeepScore(
        job_id="job-001",
        relevance=85.0,
        feasibility=80.0,
        profitability=75.0,
        win_probability=70.0,
        reasoning="Strong match.",
        red_flags=[],
    )
    fast = FastScore(
        job_id="job-001",
        skill_match=80.0,
        budget_fit=75.0,
        client_quality=70.0,
        competition=60.0,
        freshness=90.0,
        total=75.0,
        pass_threshold=True,
        breakdown={"skill_match": 80.0, "budget_fit": 75.0},
    )
    defaults: dict[str, object] = {
        "job_id": "job-001",
        "fast_score": fast,
        "deep_score": deep,
        "final_score": 78.0,
        "recommendation": "pursue",
    }
    defaults.update(overrides)
    return CompositeScore(**defaults)  # type: ignore[arg-type]


def _make_profile(**overrides: object) -> UserProfile:
    defaults = {
        "name": "Alice Dev",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "hourly_rate_min": 60.0,
        "hourly_rate_max": 120.0,
        "experience_level": "expert",
    }
    defaults.update(overrides)
    return UserProfile(**defaults)


# ---------------------------------------------------------------------------
# _format_budget
# ---------------------------------------------------------------------------

class TestFormatBudget:
    def test_hourly_both_ends(self) -> None:
        job = _make_job(hourly_rate_min=50.0, hourly_rate_max=100.0)
        assert _format_budget(job) == "$50.0-$100.0/hr"

    def test_hourly_missing_min(self) -> None:
        job = _make_job(hourly_rate_min=None, hourly_rate_max=100.0)
        assert _format_budget(job) == "?-$100.0/hr"

    def test_hourly_missing_max(self) -> None:
        job = _make_job(hourly_rate_min=50.0, hourly_rate_max=None)
        assert _format_budget(job) == "$50.0-?/hr"

    def test_fixed_both_ends(self) -> None:
        job = _make_fixed_job(budget_min=200.0, budget_max=500.0)
        assert _format_budget(job) == "$200.0-$500.0 fixed"

    def test_fixed_missing_min(self) -> None:
        job = _make_fixed_job(budget_min=None, budget_max=500.0)
        assert _format_budget(job) == "?-$500.0 fixed"

    def test_fixed_missing_max(self) -> None:
        job = _make_fixed_job(budget_min=200.0, budget_max=None)
        assert _format_budget(job) == "$200.0-? fixed"


# ---------------------------------------------------------------------------
# _format_past_proposals
# ---------------------------------------------------------------------------

class TestFormatPastProposals:
    def test_empty_results(self) -> None:
        assert _format_past_proposals([]) == "No past proposals available."

    def test_single_result(self) -> None:
        results = [
            {
                "document": "Job: Python API\n\nGreat proposal text here.",
                "metadata": {"job_title": "Python API", "outcome": "won"},
                "distance": 0.2,
            }
        ]
        output = _format_past_proposals(results)
        assert "Python API" in output
        assert "won" in output
        assert "Great proposal text here." in output

    def test_caps_at_three_results(self) -> None:
        results = [
            {
                "document": f"Job: Job {i}\n\nProposal {i}",
                "metadata": {"job_title": f"Job {i}", "outcome": "won"},
                "distance": 0.1 * i,
            }
            for i in range(5)
        ]
        output = _format_past_proposals(results)
        # Should have at most 3 separators
        assert output.count("---") <= 2

    def test_formats_without_double_newline_in_doc(self) -> None:
        results = [
            {
                "document": "Just the proposal text with no header",
                "metadata": {"job_title": "Job X", "outcome": "lost"},
                "distance": 0.5,
            }
        ]
        output = _format_past_proposals(results)
        assert "Job X" in output
        assert "lost" in output


# ---------------------------------------------------------------------------
# _parse_draft
# ---------------------------------------------------------------------------

class TestParseDraft:
    def test_valid_json(self) -> None:
        payload = json.dumps({
            "cover_letter": "This is my proposal.",
            "questions": ["What's the timeline?"],
            "confidence": 75.0,
            "reasoning": "Strong match.",
        })
        letter, questions, confidence = _parse_draft(payload)
        assert letter == "This is my proposal."
        assert questions == ["What's the timeline?"]
        assert confidence == 75.0

    def test_missing_optional_fields_uses_defaults(self) -> None:
        payload = json.dumps({"cover_letter": "My letter."})
        letter, questions, confidence = _parse_draft(payload)
        assert letter == "My letter."
        assert questions == []
        assert confidence == 50.0

    def test_empty_cover_letter_falls_back(self) -> None:
        payload = json.dumps({"cover_letter": "", "confidence": 60.0})
        letter, questions, confidence = _parse_draft(payload)
        assert letter == _CONSERVATIVE_COVER_LETTER

    def test_malformed_json_falls_back(self) -> None:
        letter, questions, confidence = _parse_draft("not json at all")
        assert letter == _CONSERVATIVE_COVER_LETTER
        assert questions == []
        assert confidence == 40.0

    def test_json_embedded_in_extra_text(self) -> None:
        raw = 'Some preamble {"cover_letter": "Embedded.", "confidence": 80.0} trailing'
        letter, questions, confidence = _parse_draft(raw)
        assert letter == "Embedded."
        assert confidence == 80.0

    def test_no_json_braces_falls_back(self) -> None:
        letter, questions, confidence = _parse_draft("no braces here")
        assert letter == _CONSERVATIVE_COVER_LETTER
        assert confidence == 40.0

    def test_filters_empty_questions(self) -> None:
        payload = json.dumps({
            "cover_letter": "My letter.",
            "questions": ["Real question?", "", None],
            "confidence": 65.0,
        })
        letter, questions, confidence = _parse_draft(payload)
        assert questions == ["Real question?"]


# ---------------------------------------------------------------------------
# ProposalWriter.write
# ---------------------------------------------------------------------------

class TestProposalWriter:
    def _make_writer(self, store: object | None = None) -> ProposalWriter:
        if store is None:
            store = MagicMock()
            store.query.return_value = []
        return ProposalWriter(
            model="gpt-4o-mini",
            temperature=0.5,
            proposal_store=store,  # type: ignore[arg-type]
        )

    @pytest.mark.asyncio
    async def test_happy_path_returns_draft(self) -> None:
        writer = self._make_writer()
        job = _make_job()
        strategy = _make_strategy()
        score = _make_score()
        profile = _make_profile()

        llm_response = json.dumps({
            "cover_letter": "I'm the ideal candidate for this API project.",
            "questions": ["Do you have an existing codebase?"],
            "confidence": 82.0,
            "reasoning": "Strong skill match with FastAPI.",
        })
        mock_response = MagicMock()
        mock_response.choices[0].message.content = llm_response

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
            draft = await writer.write(job=job, profile=profile, strategy=strategy, score=score)

        assert draft.job_id == job.id
        assert draft.cover_letter == "I'm the ideal candidate for this API project."
        assert draft.confidence == 82.0
        assert "Do you have an existing codebase?" in draft.questions_answers
        assert draft.bid_type == "hourly"
        assert draft.bid_amount == Decimal("80")
        assert draft.positioning_angle == strategy.positioning_angle

    @pytest.mark.asyncio
    async def test_llm_failure_uses_conservative_fallback(self) -> None:
        writer = self._make_writer()
        job = _make_job()
        strategy = _make_strategy()
        score = _make_score()
        profile = _make_profile()

        with patch("litellm.acompletion", new=AsyncMock(side_effect=RuntimeError("LLM down"))):
            draft = await writer.write(job=job, profile=profile, strategy=strategy, score=score)

        assert draft.cover_letter == _CONSERVATIVE_COVER_LETTER
        assert draft.confidence == 40.0

    @pytest.mark.asyncio
    async def test_empty_llm_content_uses_conservative_fallback(self) -> None:
        writer = self._make_writer()
        job = _make_job()
        strategy = _make_strategy()
        score = _make_score()
        profile = _make_profile()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = ""

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
            draft = await writer.write(job=job, profile=profile, strategy=strategy, score=score)

        assert draft.cover_letter == _CONSERVATIVE_COVER_LETTER

    @pytest.mark.asyncio
    async def test_rag_store_is_queried(self) -> None:
        store = MagicMock()
        store.query.return_value = []
        writer = self._make_writer(store=store)

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "cover_letter": "Letter.", "questions": [], "confidence": 70.0,
        })

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
            await writer.write(
                job=_make_job(),
                profile=_make_profile(),
                strategy=_make_strategy(),
                score=_make_score(),
            )

        store.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_fixed_bid_strategy(self) -> None:
        writer = self._make_writer()
        job = _make_fixed_job()
        strategy = _make_strategy(
            job_id="job-002",
            bid_type="fixed",
            proposed_rate=Decimal("400"),
            rate_range=(Decimal("350"), Decimal("450")),
        )
        score = _make_score(job_id="job-002")
        profile = _make_profile()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "cover_letter": "Fixed price proposal.", "questions": [], "confidence": 68.0,
        })

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
            draft = await writer.write(job=job, profile=profile, strategy=strategy, score=score)

        assert draft.bid_type == "fixed"
        assert draft.bid_amount == Decimal("400")

    @pytest.mark.asyncio
    async def test_strategy_missing_positioning_angle(self) -> None:
        """Proposal writer handles strategies without a positioning angle gracefully."""
        writer = self._make_writer()
        strategy = _make_strategy(positioning_angle=None)

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "cover_letter": "Angle-free proposal.", "questions": [], "confidence": 55.0,
        })

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
            draft = await writer.write(
                job=_make_job(),
                profile=_make_profile(),
                strategy=strategy,
                score=_make_score(),
            )

        assert draft.positioning_angle == ""
