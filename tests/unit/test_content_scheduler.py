"""
Unit tests for src/departments/content/scheduler.py.

Covers:
  - ContentScheduler lifecycle (start, stop, double-start, stop-before-start)
  - Event handling (missing job_id, valid bid_decided event)
  - draft_proposal pipeline (job not found, score not found, strategy not found,
    strategy should_bid=False, happy path)
  - Shutdown drain
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import HerdConfig, UserProfile
from src.departments.content.scheduler import ContentScheduler
from src.models.bid import BidStrategy
from src.models.events import BidDecided, Event, ProposalDrafted
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.proposal import ProposalDraft
from src.models.score import CompositeScore, DeepScore, FastScore

_NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-content-001",
        "platform": "upwork",
        "platform_job_id": "content-001",
        "url": "https://upwork.com/jobs/content",
        "title": "Content Test Job",
        "description": "A test job for the content scheduler.",
        "job_type": JobType.HOURLY,
        "experience_level": ExperienceLevel.EXPERT,
        "hourly_rate_min": 50.0,
        "hourly_rate_max": 100.0,
        "required_skills": ["Python"],
        "proposals_count": 5,
        "posted_at": _NOW,
        "discovered_at": _NOW,
        "status": JobStatus.BID_DECIDED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def _make_strategy(**overrides: object) -> BidStrategy:
    defaults: dict[str, object] = {
        "job_id": "job-content-001",
        "should_bid": True,
        "bid_type": "hourly",
        "proposed_rate": Decimal("80"),
        "rate_range": (Decimal("75"), Decimal("90")),
        "positioning_angle": "Your API needs someone with deep Python chops.",
        "urgency": "normal",
        "confidence": 72.0,
        "reasoning": "Strong match.",
    }
    defaults.update(overrides)
    return BidStrategy(**defaults)  # type: ignore[arg-type]


def _make_score() -> CompositeScore:
    deep = DeepScore(
        job_id="job-content-001",
        relevance=85.0,
        feasibility=80.0,
        profitability=75.0,
        win_probability=70.0,
        reasoning="Good match.",
        red_flags=[],
    )
    fast = FastScore(
        job_id="job-content-001",
        skill_match=80.0,
        budget_fit=75.0,
        client_quality=70.0,
        competition=60.0,
        freshness=90.0,
        total=75.0,
        pass_threshold=True,
        breakdown={"skill_match": 80.0, "budget_fit": 75.0},
    )
    return CompositeScore(
        job_id="job-content-001",
        fast_score=fast,
        deep_score=deep,
        final_score=78.0,
        recommendation="pursue",
    )


def _make_draft(**overrides: object) -> ProposalDraft:
    defaults: dict[str, object] = {
        "job_id": "job-content-001",
        "platform": "upwork",
        "platform_job_id": "content-001",
        "bid_type": "hourly",
        "bid_amount": Decimal("80"),
        "cover_letter": "This is the generated cover letter.",
        "confidence": 75.0,
        "positioning_angle": "Your API needs someone with deep Python chops.",
    }
    defaults.update(overrides)
    return ProposalDraft(**defaults)  # type: ignore[arg-type]


class _FakeEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list] = {}
        self.published: list[Event] = []

    def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.get(event_type, []).remove(handler)

    async def publish(self, event: Event) -> None:
        self.published.append(event)

    async def emit(self, event_type: str, payload: dict) -> None:
        for handler in self._handlers.get(event_type, []):
            await handler(Event(event_type=event_type, source_department="test", payload=payload))


def _make_config() -> HerdConfig:
    return HerdConfig(user_profile=UserProfile(name="Test User", skills=["Python"]))


def _make_scheduler(writer: Any = None) -> tuple[ContentScheduler, _FakeEventBus]:
    bus = _FakeEventBus()
    db = MagicMock()
    config = _make_config()
    if writer is None:
        writer = AsyncMock()
        writer.write = AsyncMock(return_value=_make_draft())
    scheduler = ContentScheduler(event_bus=bus, db=db, config=config, writer=writer)
    return scheduler, bus


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_bid_decided(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()
        assert "bid_decided" in bus._handlers
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()
        await scheduler.stop()
        assert bus._handlers.get("bid_decided", []) == []

    @pytest.mark.asyncio
    async def test_double_start_is_harmless(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()
        await scheduler.start()
        assert len(bus._handlers.get("bid_decided", [])) == 1
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_before_start_is_harmless(self) -> None:
        scheduler, _ = _make_scheduler()
        await scheduler.stop()  # should not raise


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------

class TestEventHandling:
    @pytest.mark.asyncio
    async def test_missing_job_id_logs_warning_no_task(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()
        event = BidDecided(payload={"job_id": ""})
        await scheduler._on_bid_decided(event)
        assert len(scheduler._inflight) == 0
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_valid_event_creates_task(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()

        with patch.object(scheduler, "draft_proposal", new=AsyncMock()):
            event = BidDecided(payload={"job_id": "job-content-001"})
            await scheduler._on_bid_decided(event)
            assert len(scheduler._inflight) == 1

        await scheduler.stop()


# ---------------------------------------------------------------------------
# draft_proposal pipeline
# ---------------------------------------------------------------------------

_JOB_REPO = "src.repositories.job_repo"
_BID_REPO = "src.repositories.bid_repo"
_SCORE_REPO = "src.repositories.score_repo"
_PROPOSAL_REPO = "src.repositories.proposal_repo"


class TestDraftProposal:
    @pytest.mark.asyncio
    async def test_job_not_found_returns_early(self) -> None:
        scheduler, bus = _make_scheduler()
        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=None)),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock()) as mock_score,
        ):
            await scheduler.draft_proposal("job-content-001")
            mock_score.assert_not_called()
        assert bus.published == []

    @pytest.mark.asyncio
    async def test_score_not_found_returns_early(self) -> None:
        scheduler, bus = _make_scheduler()
        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=None)),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock()) as mock_strat,
        ):
            await scheduler.draft_proposal("job-content-001")
            mock_strat.assert_not_called()
        assert bus.published == []

    @pytest.mark.asyncio
    async def test_strategy_not_found_returns_early(self) -> None:
        scheduler, bus = _make_scheduler()
        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=_make_score())),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock(return_value=None)),
        ):
            await scheduler.draft_proposal("job-content-001")
        assert bus.published == []

    @pytest.mark.asyncio
    async def test_strategy_should_bid_false_skips_generation(self) -> None:
        writer = MagicMock()
        writer.write = AsyncMock()
        scheduler, bus = _make_scheduler(writer=writer)

        pass_strategy = _make_strategy(
            should_bid=False,
            bid_type=None,
            proposed_rate=None,
            rate_range=None,
            positioning_angle=None,
            urgency=None,
            pass_reason="low_analyst_score",
        )
        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=_make_score())),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock(return_value=pass_strategy)),
        ):
            await scheduler.draft_proposal("job-content-001")

        writer.write.assert_not_called()
        assert bus.published == []

    @pytest.mark.asyncio
    async def test_happy_path_emits_proposal_drafted(self) -> None:
        draft = _make_draft()
        writer = MagicMock()
        writer.write = AsyncMock(return_value=draft)
        scheduler, bus = _make_scheduler(writer=writer)

        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=_make_score())),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock(return_value=_make_strategy())),
            patch(f"{_PROPOSAL_REPO}.save_proposal", new=AsyncMock()),
            patch(f"{_JOB_REPO}.update_job_status", new=AsyncMock()),
        ):
            await scheduler.draft_proposal("job-content-001")

        assert len(bus.published) == 1
        event = bus.published[0]
        assert isinstance(event, ProposalDrafted)
        assert event.payload["job_id"] == "job-content-001"
        assert event.payload["proposal_id"] == str(draft.id)
        assert event.payload["confidence"] == draft.confidence

    @pytest.mark.asyncio
    async def test_happy_path_saves_proposal(self) -> None:
        draft = _make_draft()
        writer = MagicMock()
        writer.write = AsyncMock(return_value=draft)
        scheduler, _ = _make_scheduler(writer=writer)

        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=_make_score())),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock(return_value=_make_strategy())),
            patch(f"{_PROPOSAL_REPO}.save_proposal", new=AsyncMock()) as mock_save,
            patch(f"{_JOB_REPO}.update_job_status", new=AsyncMock()),
        ):
            await scheduler.draft_proposal("job-content-001")

        mock_save.assert_awaited_once_with(scheduler._db, draft)

    @pytest.mark.asyncio
    async def test_happy_path_updates_job_status(self) -> None:
        writer = MagicMock()
        writer.write = AsyncMock(return_value=_make_draft())
        scheduler, _ = _make_scheduler(writer=writer)

        with (
            patch(f"{_JOB_REPO}.get_job", new=AsyncMock(return_value=_make_job())),
            patch(f"{_SCORE_REPO}.get_score_by_job_id", new=AsyncMock(return_value=_make_score())),
            patch(f"{_BID_REPO}.get_bid_strategy", new=AsyncMock(return_value=_make_strategy())),
            patch(f"{_PROPOSAL_REPO}.save_proposal", new=AsyncMock()),
            patch(f"{_JOB_REPO}.update_job_status", new=AsyncMock()) as mock_status,
        ):
            await scheduler.draft_proposal("job-content-001")

        mock_status.assert_awaited_once_with(
            scheduler._db, "job-content-001", "proposal_drafted"
        )


# ---------------------------------------------------------------------------
# Shutdown drain
# ---------------------------------------------------------------------------

class TestShutdownDrain:
    @pytest.mark.asyncio
    async def test_stop_waits_for_inflight_tasks(self) -> None:
        completed: list[str] = []

        async def slow_draft(job_id: str) -> None:
            await asyncio.sleep(0.02)
            completed.append(job_id)

        scheduler, bus = _make_scheduler()
        await scheduler.start()

        task = asyncio.create_task(slow_draft("job-content-001"))
        scheduler._inflight.add(task)
        task.add_done_callback(scheduler._inflight.discard)

        await scheduler.stop()
        assert "job-content-001" in completed

    @pytest.mark.asyncio
    async def test_unhandled_error_in_task_does_not_block_stop(self) -> None:
        scheduler, bus = _make_scheduler()
        await scheduler.start()

        async def failing_draft(job_id: str) -> None:
            raise RuntimeError("boom")

        task = asyncio.create_task(failing_draft("job-err"))
        scheduler._inflight.add(task)
        task.add_done_callback(scheduler._inflight.discard)

        await scheduler.stop()  # should not raise
