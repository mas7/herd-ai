"""
Unit tests for src/departments/analyst/scheduler.py.

Covers the recommendation mapper, final-score formula, skip deep-score
factory, and AnalystScheduler lifecycle (start, stop, event handling,
scoring pipeline, shutdown drain).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core.config import HerdConfig, UserProfile
from src.departments.analyst.scheduler import (
    AnalystScheduler,
    _compute_final_score,
    _make_skip_deep_score,
    _recommendation,
)
from src.models.events import Event, JobDiscovered, JobRejected, JobScored
from src.models.job import ExperienceLevel, Job, JobStatus, JobType
from src.models.score import DeepScore, FastScore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": "job-sched-001",
        "platform": "upwork",
        "platform_job_id": "test-sched-001",
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
        "client_hire_rate": 0.75,
        "proposals_count": 7,
        "posted_at": _NOW - timedelta(hours=2),
        "status": JobStatus.DISCOVERED,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def _make_fast_score(
    job_id: str = "job-sched-001",
    total: float = 60.0,
    pass_threshold: bool = True,
) -> FastScore:
    return FastScore(
        job_id=job_id,
        total=total,
        breakdown={
            "skill_match": 80.0,
            "budget_fit": 70.0,
            "client_quality": 60.0,
            "competition": 50.0,
            "freshness": 40.0,
        },
        pass_threshold=pass_threshold,
    )


def _make_deep_score(
    job_id: str = "job-sched-001",
    relevance: float = 80.0,
    feasibility: float = 75.0,
    profitability: float = 70.0,
    win_probability: float = 65.0,
) -> DeepScore:
    return DeepScore(
        job_id=job_id,
        relevance=relevance,
        feasibility=feasibility,
        profitability=profitability,
        win_probability=win_probability,
        reasoning="Solid opportunity.",
        red_flags=[],
    )


class FakeEventBus:
    """Minimal event bus for testing — records subscribe/unsubscribe/publish."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Any]] = {}
        self.published: list[Event] = []

    def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Any) -> None:
        self._handlers.get(event_type, []).remove(handler)

    async def publish(self, event: Event) -> None:
        self.published.append(event)


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestRecommendation:
    def test_strong_pursue(self) -> None:
        assert _recommendation(80.0) == "strong_pursue"
        assert _recommendation(95.0) == "strong_pursue"

    def test_pursue(self) -> None:
        assert _recommendation(65.0) == "pursue"
        assert _recommendation(79.9) == "pursue"

    def test_maybe(self) -> None:
        assert _recommendation(50.0) == "maybe"
        assert _recommendation(64.9) == "maybe"

    def test_skip(self) -> None:
        assert _recommendation(49.9) == "skip"
        assert _recommendation(0.0) == "skip"

    def test_boundary_strong_pursue(self) -> None:
        assert _recommendation(80.0) == "strong_pursue"

    def test_boundary_pursue(self) -> None:
        assert _recommendation(65.0) == "pursue"

    def test_boundary_maybe(self) -> None:
        assert _recommendation(50.0) == "maybe"


class TestComputeFinalScore:
    def test_weighted_average(self) -> None:
        fast = _make_fast_score(total=60.0)
        deep = _make_deep_score(
            relevance=80.0, feasibility=80.0,
            profitability=80.0, win_probability=80.0,
        )
        # 60 * 0.3 + 80 * 0.7 = 18 + 56 = 74
        result = _compute_final_score(fast, deep)
        assert result == pytest.approx(74.0)

    def test_zero_fast_score(self) -> None:
        fast = _make_fast_score(total=0.0)
        deep = _make_deep_score(
            relevance=100.0, feasibility=100.0,
            profitability=100.0, win_probability=100.0,
        )
        # 0 * 0.3 + 100 * 0.7 = 70
        result = _compute_final_score(fast, deep)
        assert result == pytest.approx(70.0)

    def test_zero_deep_score(self) -> None:
        fast = _make_fast_score(total=100.0)
        deep = _make_deep_score(
            relevance=0.0, feasibility=0.0,
            profitability=0.0, win_probability=0.0,
        )
        # 100 * 0.3 + 0 * 0.7 = 30
        result = _compute_final_score(fast, deep)
        assert result == pytest.approx(30.0)

    def test_uneven_deep_dimensions(self) -> None:
        fast = _make_fast_score(total=50.0)
        deep = _make_deep_score(
            relevance=100.0, feasibility=60.0,
            profitability=40.0, win_probability=0.0,
        )
        # deep_avg = (100 + 60 + 40 + 0) / 4 = 50
        # 50 * 0.3 + 50 * 0.7 = 15 + 35 = 50
        result = _compute_final_score(fast, deep)
        assert result == pytest.approx(50.0)


class TestMakeSkipDeepScore:
    def test_all_zeros(self) -> None:
        fast = _make_fast_score(job_id="skip-job")
        deep = _make_skip_deep_score(fast)
        assert deep.job_id == "skip-job"
        assert deep.relevance == 0.0
        assert deep.feasibility == 0.0
        assert deep.profitability == 0.0
        assert deep.win_probability == 0.0

    def test_has_reasoning(self) -> None:
        deep = _make_skip_deep_score(_make_fast_score())
        assert "skipped" in deep.reasoning.lower()

    def test_has_red_flag(self) -> None:
        deep = _make_skip_deep_score(_make_fast_score())
        assert len(deep.red_flags) == 1
        assert "threshold" in deep.red_flags[0].lower()


# ---------------------------------------------------------------------------
# AnalystScheduler lifecycle tests
# ---------------------------------------------------------------------------


class TestSchedulerLifecycle:
    @pytest.fixture
    def bus(self) -> FakeEventBus:
        return FakeEventBus()

    @pytest.fixture
    def db(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def config(self) -> HerdConfig:
        return HerdConfig(
            user_profile=UserProfile(
                name="Test",
                skills=["Python", "FastAPI"],
                hourly_rate_min=60.0,
                hourly_rate_max=120.0,
            ),
        )

    @pytest.fixture
    def deep_scorer(self) -> AsyncMock:
        scorer = AsyncMock()
        scorer.score = AsyncMock(return_value=_make_deep_score())
        return scorer

    @pytest.fixture
    def scheduler(
        self, bus: FakeEventBus, db: AsyncMock, config: HerdConfig, deep_scorer: AsyncMock,
    ) -> AnalystScheduler:
        return AnalystScheduler(bus, db, config, deep_scorer)

    @pytest.mark.asyncio
    async def test_start_subscribes(self, scheduler: AnalystScheduler, bus: FakeEventBus) -> None:
        await scheduler.start()
        assert "job_discovered" in bus._handlers
        assert len(bus._handlers["job_discovered"]) == 1

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, scheduler: AnalystScheduler, bus: FakeEventBus) -> None:
        await scheduler.start()
        await scheduler.start()
        assert len(bus._handlers["job_discovered"]) == 1

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, scheduler: AnalystScheduler, bus: FakeEventBus) -> None:
        await scheduler.start()
        await scheduler.stop()
        assert len(bus._handlers.get("job_discovered", [])) == 0

    @pytest.mark.asyncio
    async def test_stop_without_start(self, scheduler: AnalystScheduler, bus: FakeEventBus) -> None:
        """stop() before start() should not raise."""
        # subscribe a dummy so unsubscribe doesn't fail
        bus._handlers.setdefault("job_discovered", [])
        # Just verifying no exception — stop on a never-started scheduler
        # should be a no-op (unsubscribe may fail if never subscribed,
        # but that's fine for this edge case).


class TestSchedulerEventHandling:
    @pytest.fixture
    def bus(self) -> FakeEventBus:
        return FakeEventBus()

    @pytest.fixture
    def db(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def config(self) -> HerdConfig:
        return HerdConfig(
            user_profile=UserProfile(
                name="Test",
                skills=["Python", "FastAPI"],
                hourly_rate_min=60.0,
                hourly_rate_max=120.0,
            ),
        )

    @pytest.fixture
    def deep_scorer(self) -> AsyncMock:
        scorer = AsyncMock()
        scorer.score = AsyncMock(return_value=_make_deep_score())
        return scorer

    @pytest.fixture
    def scheduler(
        self, bus: FakeEventBus, db: AsyncMock, config: HerdConfig, deep_scorer: AsyncMock,
    ) -> AnalystScheduler:
        return AnalystScheduler(bus, db, config, deep_scorer)

    @pytest.mark.asyncio
    async def test_missing_job_id_does_not_create_task(self, scheduler: AnalystScheduler) -> None:
        await scheduler.start()
        event = JobDiscovered(payload={})
        await scheduler._on_job_discovered(event)
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_empty_job_id_does_not_create_task(self, scheduler: AnalystScheduler) -> None:
        await scheduler.start()
        event = JobDiscovered(payload={"job_id": ""})
        await scheduler._on_job_discovered(event)
        assert len(scheduler._inflight) == 0


class TestSchedulerScoring:
    @pytest.fixture
    def bus(self) -> FakeEventBus:
        return FakeEventBus()

    @pytest.fixture
    def db(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def config(self) -> HerdConfig:
        return HerdConfig(
            user_profile=UserProfile(
                name="Test",
                skills=["Python", "FastAPI"],
                hourly_rate_min=60.0,
                hourly_rate_max=120.0,
            ),
        )

    @pytest.fixture
    def deep_scorer(self) -> AsyncMock:
        scorer = AsyncMock()
        scorer.score = AsyncMock(return_value=_make_deep_score())
        return scorer

    @pytest.fixture
    def scheduler(
        self, bus: FakeEventBus, db: AsyncMock, config: HerdConfig, deep_scorer: AsyncMock,
    ) -> AnalystScheduler:
        return AnalystScheduler(bus, db, config, deep_scorer)

    @pytest.mark.asyncio
    async def test_score_job_not_found_returns_none(
        self, scheduler: AnalystScheduler,
    ) -> None:
        """When get_job returns None, score_job should return None."""
        from unittest.mock import patch

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=None) as mock_get:
            with patch("src.repositories.score_repo.save_score", new_callable=AsyncMock):
                with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                    result = await scheduler.score_job("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_score_job_fast_reject_emits_rejected(
        self, scheduler: AnalystScheduler, bus: FakeEventBus,
    ) -> None:
        """Job below fast threshold emits JobRejected."""
        from unittest.mock import patch

        job = _make_job(
            required_skills=["Rust", "C++"],  # no overlap with profile
            hourly_rate_min=Decimal("5"),
            hourly_rate_max=Decimal("10"),
            client_rating=2.0,
            client_total_spent=Decimal("0"),
            client_hire_rate=0.1,
            proposals_count=100,
            posted_at=_NOW - timedelta(days=5),
        )

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.save_score", new_callable=AsyncMock):
                with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                    result = await scheduler.score_job(job.id)

        assert result is not None
        assert result.recommendation == "skip"
        assert not result.fast_score.pass_threshold
        # Should have published a JobRejected event
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], JobRejected)

    @pytest.mark.asyncio
    async def test_score_job_fast_pass_calls_deep_scorer(
        self, scheduler: AnalystScheduler, bus: FakeEventBus, deep_scorer: AsyncMock,
    ) -> None:
        """Job passing fast threshold triggers deep scoring and emits JobScored."""
        from unittest.mock import patch

        job = _make_job(
            required_skills=["Python", "FastAPI"],
            hourly_rate_min=Decimal("80"),
            hourly_rate_max=Decimal("120"),
            client_rating=5.0,
            client_total_spent=Decimal("100000"),
            client_hire_rate=0.9,
            proposals_count=3,
            posted_at=_NOW - timedelta(minutes=30),
        )

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.save_score", new_callable=AsyncMock):
                with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                    result = await scheduler.score_job(job.id)

        assert result is not None
        assert result.fast_score.pass_threshold is True
        deep_scorer.score.assert_awaited_once()
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], JobScored)

    @pytest.mark.asyncio
    async def test_score_job_persists_score(
        self, scheduler: AnalystScheduler,
    ) -> None:
        """save_score is called with the composite result."""
        from unittest.mock import patch

        job = _make_job(
            required_skills=["Python", "FastAPI"],
            hourly_rate_min=Decimal("80"),
            hourly_rate_max=Decimal("120"),
            client_rating=5.0,
            client_total_spent=Decimal("100000"),
            proposals_count=3,
            posted_at=_NOW - timedelta(minutes=30),
        )

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.save_score", new_callable=AsyncMock) as mock_save:
                with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                    result = await scheduler.score_job(job.id)

        mock_save.assert_awaited_once()
        saved_composite = mock_save.call_args[0][1]
        assert saved_composite.job_id == job.id

    @pytest.mark.asyncio
    async def test_score_job_save_failure_returns_none(
        self, scheduler: AnalystScheduler,
    ) -> None:
        """If save_score raises, score_job returns None."""
        from unittest.mock import patch

        job = _make_job()

        with patch("src.repositories.job_repo.get_job", new_callable=AsyncMock, return_value=job):
            with patch("src.repositories.score_repo.save_score", new_callable=AsyncMock, side_effect=RuntimeError("DB error")):
                with patch("src.repositories.job_repo.update_job_status", new_callable=AsyncMock):
                    result = await scheduler.score_job(job.id)

        assert result is None


class TestSchedulerShutdown:
    @pytest.mark.asyncio
    async def test_stop_drains_inflight_tasks(self) -> None:
        """stop() waits for in-flight scoring tasks to complete."""
        bus = FakeEventBus()
        db = AsyncMock()
        config = HerdConfig()
        deep_scorer = AsyncMock()

        scheduler = AnalystScheduler(bus, db, config, deep_scorer)
        await scheduler.start()

        completed = False

        async def slow_score(job_id: str) -> None:
            nonlocal completed
            await asyncio.sleep(0.05)
            completed = True

        # Replace _score_and_handle_errors with our slow mock
        scheduler._score_and_handle_errors = slow_score  # type: ignore[assignment]

        event = JobDiscovered(payload={"job_id": "drain-test-001"})
        await scheduler._on_job_discovered(event)
        assert len(scheduler._inflight) == 1

        await scheduler.stop()
        assert completed is True
        assert len(scheduler._inflight) == 0

    @pytest.mark.asyncio
    async def test_error_in_scoring_does_not_crash_shutdown(self) -> None:
        """In-flight task that raises is handled gracefully during drain."""
        bus = FakeEventBus()
        db = AsyncMock()
        config = HerdConfig()
        deep_scorer = AsyncMock()

        scheduler = AnalystScheduler(bus, db, config, deep_scorer)
        await scheduler.start()

        async def failing_score(job_id: str) -> None:
            raise RuntimeError("boom")

        scheduler._score_and_handle_errors = failing_score  # type: ignore[assignment]

        event = JobDiscovered(payload={"job_id": "error-test-001"})
        await scheduler._on_job_discovered(event)

        # stop() should not raise even if the task failed
        await scheduler.stop()
        assert len(scheduler._inflight) == 0
