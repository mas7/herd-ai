"""
Unit tests for src/departments/bizdev/scheduler.py.

Covers:
  - _pricing_confidence  (helper)
  - _compute_confidence  (helper)
  - _urgency             (helper)
  - BizDevScheduler lifecycle (start, stop, double-start, stop-before-start)
  - Event handling (skip recommendation, missing job_id)
  - decide_bid pipeline (job not found, score not found, pass paths, full bid)
  - Shutdown drain
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import HerdConfig, UserProfile
from src.departments.bizdev.pricing import BidPrice
from src.departments.bizdev.scheduler import (
    BizDevScheduler,
    _compute_confidence,
    _pricing_confidence,
    _urgency,
)
from src.models.bid import BidStrategy, WinRecord
from src.models.events import BidDecided, Event, JobPassed, JobScored
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import CompositeScore, DeepScore, FastScore

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-bizdev-001",
        "platform": "upwork",
        "platform_job_id": "bizdev-001",
        "url": "https://upwork.com/jobs/bizdev",
        "title": "BizDev Test Job",
        "description": "A test job for the bizdev scheduler.",
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


def _make_composite_score(
    job_id: str = "job-bizdev-001",
    final_score: float = 75.0,
    win_probability: float = 70.0,
    recommendation: str = "pursue",
) -> CompositeScore:
    fast = FastScore(
        job_id=job_id,
        total=70.0,
        breakdown={},
        pass_threshold=True,
    )
    deep = DeepScore(
        job_id=job_id,
        relevance=75.0,
        feasibility=75.0,
        profitability=75.0,
        win_probability=win_probability,
        reasoning="Solid opportunity.",
        red_flags=[],
    )
    return CompositeScore(
        job_id=job_id,
        fast_score=fast,
        deep_score=deep,
        final_score=final_score,
        recommendation=recommendation,
    )


def _make_config(min_rate: float = 60.0, max_rate: float = 120.0) -> HerdConfig:
    return HerdConfig(
        user_profile=UserProfile(
            name="Test",
            skills=["Python", "FastAPI"],
            hourly_rate_min=min_rate,
            hourly_rate_max=max_rate,
        ),
    )


class FakeEventBus:
    """Minimal event bus for testing."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Any]] = {}
        self.published: list[Event] = []

    def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.get(event_type, []).remove(handler)

    async def publish(self, event: Event) -> None:
        self.published.append(event)


def _make_scheduler(
    bus: FakeEventBus | None = None,
    db: AsyncMock | None = None,
    config: HerdConfig | None = None,
    positioner: AsyncMock | None = None,
) -> BizDevScheduler:
    if bus is None:
        bus = FakeEventBus()
    if db is None:
        db = AsyncMock()
    if config is None:
        config = _make_config()
    if positioner is None:
        positioner = AsyncMock()
        positioner.get_angle = AsyncMock(return_value="Lead with Python expertise.")
    return BizDevScheduler(bus, db, config, positioner)


# ---------------------------------------------------------------------------
# Pure function helpers
# ---------------------------------------------------------------------------


class TestPricingConfidence:
    def test_none_budget_returns_70(self) -> None:
        assert _pricing_confidence(100.0, None) == 70.0

    def test_bid_within_budget_is_100(self) -> None:
        assert _pricing_confidence(80.0, 100.0) == 100.0

    def test_bid_equal_to_budget_is_100(self) -> None:
        assert _pricing_confidence(100.0, 100.0) == 100.0

    def test_bid_slightly_over_budget_is_70(self) -> None:
        # ratio = 105/100 = 1.05 → 70
        assert _pricing_confidence(105.0, 100.0) == 70.0

    def test_bid_over_10pct_above_budget_is_50(self) -> None:
        # ratio = 115/100 = 1.15 → 50
        assert _pricing_confidence(115.0, 100.0) == 50.0

    def test_boundary_exactly_1_10_is_70(self) -> None:
        # ratio = 110/100 = 1.10 → 70
        assert _pricing_confidence(110.0, 100.0) == 70.0


class TestComputeConfidence:
    def test_weighted_formula(self) -> None:
        # 80*0.5 + 70*0.3 + 100*0.2 = 40 + 21 + 20 = 81
        result = _compute_confidence(
            final_score=80.0,
            win_probability=70.0,
            bid_amount=80.0,
            job_budget_max=100.0,
        )
        assert result == pytest.approx(81.0)

    def test_no_budget_max(self) -> None:
        # pricing_conf = 70 (None budget)
        # 80*0.5 + 70*0.3 + 70*0.2 = 40 + 21 + 14 = 75
        result = _compute_confidence(
            final_score=80.0,
            win_probability=70.0,
            bid_amount=80.0,
            job_budget_max=None,
        )
        assert result == pytest.approx(75.0)


class TestUrgency:
    def test_immediate_at_80(self) -> None:
        assert _urgency(80.0) == "immediate"

    def test_immediate_above_80(self) -> None:
        assert _urgency(95.0) == "immediate"

    def test_normal_at_60(self) -> None:
        assert _urgency(60.0) == "normal"

    def test_normal_at_79(self) -> None:
        assert _urgency(79.9) == "normal"

    def test_low_below_60(self) -> None:
        assert _urgency(59.9) == "low"

    def test_low_at_zero(self) -> None:
        assert _urgency(0.0) == "low"


# ---------------------------------------------------------------------------
# BizDevScheduler lifecycle
# ---------------------------------------------------------------------------


class TestBizDevSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_job_scored(self) -> None:
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        await scheduler.start()
        assert "job_scored" in bus._handlers
        assert len(bus._handlers["job_scored"]) == 1

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self) -> None:
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        await scheduler.start()
        await scheduler.start()
        assert len(bus._handlers["job_scored"]) == 1

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self) -> None:
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        await scheduler.start()
        await scheduler.stop()
        assert len(bus._handlers.get("job_scored", [])) == 0

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe_noop(self) -> None:
        scheduler = _make_scheduler()
        await scheduler.stop()  # must not raise
        assert not scheduler._running


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------


class TestBizDevSchedulerEventHandling:
    @pytest.mark.asyncio
    async def test_missing_job_id_does_not_create_task(self) -> None:
        scheduler = _make_scheduler()
        await scheduler.start()
        event = JobScored(payload={})
        await scheduler._on_job_scored(event)
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_empty_job_id_does_not_create_task(self) -> None:
        scheduler = _make_scheduler()
        await scheduler.start()
        event = JobScored(payload={"job_id": ""})
        await scheduler._on_job_scored(event)
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_skip_recommendation_does_not_create_task(self) -> None:
        """Events with recommendation=skip bypass the bid pipeline."""
        scheduler = _make_scheduler()
        await scheduler.start()
        event = JobScored(payload={"job_id": "some-job", "recommendation": "skip"})
        await scheduler._on_job_scored(event)
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_pursue_recommendation_creates_task(self) -> None:
        """Events with pursue recommendation enqueue a bid decision task."""
        scheduler = _make_scheduler()
        await scheduler.start()

        # Prevent actual decide_bid execution during this test
        async def _noop(job_id: str) -> None:
            pass

        scheduler._decide_and_handle_errors = _noop  # type: ignore[method-assign]
        event = JobScored(payload={"job_id": "some-job", "recommendation": "pursue"})
        await scheduler._on_job_scored(event)
        assert len(scheduler._inflight) == 1
        # Clean up
        await asyncio.gather(*scheduler._inflight, return_exceptions=True)


# ---------------------------------------------------------------------------
# decide_bid pipeline
# ---------------------------------------------------------------------------


class TestDecideBid:
    @pytest.mark.asyncio
    async def test_job_not_found_returns_none(self) -> None:
        scheduler = _make_scheduler()
        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=None):
            result = await scheduler.decide_bid("nonexistent-job")
        assert result is None

    @pytest.mark.asyncio
    async def test_score_not_found_returns_none(self) -> None:
        scheduler = _make_scheduler()
        job = _make_job()
        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=None):
                result = await scheduler.decide_bid(job.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_low_analyst_score_emits_job_passed(self) -> None:
        """recommend=skip in DB score → emit JobPassed(reason=low_analyst_score)."""
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        job = _make_job()
        score = _make_composite_score(
            job_id=job.id, final_score=40.0, recommendation="skip"
        )
        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock):
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            result = await scheduler.decide_bid(job.id)

        assert result is not None
        assert result.should_bid is False
        assert result.pass_reason == "low_analyst_score"
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], JobPassed)
        assert bus.published[0].payload["reason"] == "low_analyst_score"

    @pytest.mark.asyncio
    async def test_price_not_viable_emits_job_passed(self) -> None:
        """When bid price is not viable → emit JobPassed(reason=price_not_viable)."""
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_max=Decimal("10"),  # far below profile_min
        )
        score = _make_composite_score(job_id=job.id, recommendation="pursue")

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock):
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            result = await scheduler.decide_bid(job.id)

        assert result is not None
        assert result.should_bid is False
        assert result.pass_reason == "price_not_viable"
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], JobPassed)
        assert bus.published[0].payload["reason"] == "price_not_viable"

    @pytest.mark.asyncio
    async def test_full_bid_decision_emits_bid_decided(self) -> None:
        """Happy path: viable price → positioning → BidDecided event."""
        bus = FakeEventBus()
        positioner = AsyncMock()
        positioner.get_angle = AsyncMock(return_value="Lead with Python expertise.")
        scheduler = _make_scheduler(bus=bus, positioner=positioner)

        job = _make_job(
            job_type=JobType.HOURLY,
            hourly_rate_max=Decimal("120"),
        )
        score = _make_composite_score(
            job_id=job.id, final_score=80.0, win_probability=72.0, recommendation="pursue"
        )

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock):
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            result = await scheduler.decide_bid(job.id)

        assert result is not None
        assert result.should_bid is True
        assert result.positioning_angle == "Lead with Python expertise."
        assert result.bid_type == "hourly"
        assert result.proposed_rate is not None
        assert result.confidence > 0
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], BidDecided)

    @pytest.mark.asyncio
    async def test_full_bid_decision_persists_strategy(self) -> None:
        """save_bid_strategy is called once with correct job_id."""
        bus = FakeEventBus()
        positioner = AsyncMock()
        positioner.get_angle = AsyncMock(return_value="Angle.")
        scheduler = _make_scheduler(bus=bus, positioner=positioner)

        job = _make_job(job_type=JobType.HOURLY, hourly_rate_max=Decimal("120"))
        score = _make_composite_score(job_id=job.id, recommendation="pursue")

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock) as mock_save:
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            await scheduler.decide_bid(job.id)

        mock_save.assert_awaited_once()
        saved: BidStrategy = mock_save.call_args[0][1]
        assert saved.job_id == job.id
        assert saved.should_bid is True

    @pytest.mark.asyncio
    async def test_bid_decided_payload_fields(self) -> None:
        """BidDecided event payload contains required fields."""
        bus = FakeEventBus()
        positioner = AsyncMock()
        positioner.get_angle = AsyncMock(return_value="Angle.")
        scheduler = _make_scheduler(bus=bus, positioner=positioner)

        job = _make_job(job_type=JobType.HOURLY, hourly_rate_max=Decimal("120"))
        score = _make_composite_score(job_id=job.id, final_score=82.0, recommendation="pursue")

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock):
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            await scheduler.decide_bid(job.id)

        event = bus.published[0]
        assert isinstance(event, BidDecided)
        assert event.payload["job_id"] == job.id
        assert "bid_type" in event.payload
        assert "proposed_rate" in event.payload
        assert "confidence" in event.payload
        assert "urgency" in event.payload

    @pytest.mark.asyncio
    async def test_urgency_is_immediate_for_high_score(self) -> None:
        """final_score >= 80 → urgency = immediate."""
        bus = FakeEventBus()
        positioner = AsyncMock()
        positioner.get_angle = AsyncMock(return_value="Angle.")
        scheduler = _make_scheduler(bus=bus, positioner=positioner)

        job = _make_job(job_type=JobType.HOURLY, hourly_rate_max=Decimal("120"))
        score = _make_composite_score(job_id=job.id, final_score=85.0, recommendation="strong_pursue")

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.get_score_by_job_id", new_callable=AsyncMock, return_value=score):
                with patch("src.repositories.bid_repo.get_win_history", new_callable=AsyncMock, return_value=[]):
                    with patch("src.repositories.bid_repo.save_bid_strategy", new_callable=AsyncMock):
                        with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                            result = await scheduler.decide_bid(job.id)

        assert result is not None
        assert result.urgency == "immediate"


# ---------------------------------------------------------------------------
# Shutdown drain
# ---------------------------------------------------------------------------


class TestBizDevSchedulerShutdown:
    @pytest.mark.asyncio
    async def test_stop_drains_inflight_tasks(self) -> None:
        """stop() waits for in-flight tasks to complete before returning."""
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        await scheduler.start()

        completed = False

        async def slow_decide(job_id: str) -> None:
            nonlocal completed
            await asyncio.sleep(0.05)
            completed = True

        scheduler._decide_and_handle_errors = slow_decide  # type: ignore[method-assign]

        event = JobScored(payload={"job_id": "drain-test-001", "recommendation": "pursue"})
        await scheduler._on_job_scored(event)
        assert len(scheduler._inflight) == 1

        await scheduler.stop()
        assert completed is True
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_error_in_task_does_not_crash_shutdown(self) -> None:
        """In-flight task that raises is handled gracefully during drain."""
        bus = FakeEventBus()
        scheduler = _make_scheduler(bus=bus)
        await scheduler.start()

        async def failing_decide(job_id: str) -> None:
            raise RuntimeError("boom")

        scheduler._decide_and_handle_errors = failing_decide  # type: ignore[method-assign]

        event = JobScored(payload={"job_id": "error-test-001", "recommendation": "pursue"})
        await scheduler._on_job_scored(event)

        await scheduler.stop()  # must not raise
        assert len(scheduler._inflight) == 0
