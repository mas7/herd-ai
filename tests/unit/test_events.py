"""
Unit tests for src/core/events.py (InProcessEventBus).

Covers:
  - Basic subscribe/publish/unsubscribe mechanics
  - Concurrent handler execution (asyncio.gather)
  - Error isolation (one handler failure does not stop others)
  - History tracking
  - No-handler publish is a no-op
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, call

import pytest

from src.core.events import InProcessEventBus
from src.models.events import Event, JobDiscovered, JobScored


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(event_type: str = "test_event") -> Event:
    return Event(
        event_type=event_type,
        source_department="test",
    )


# ---------------------------------------------------------------------------
# Subscribe / Publish
# ---------------------------------------------------------------------------


class TestSubscribePublish:
    @pytest.mark.asyncio
    async def test_handler_called_on_matching_event(self) -> None:
        bus = InProcessEventBus()
        handler = AsyncMock()
        bus.subscribe("test_event", handler)

        event = _make_event("test_event")
        await bus.publish(event)

        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_handler_not_called_on_different_event(self) -> None:
        bus = InProcessEventBus()
        handler = AsyncMock()
        bus.subscribe("other_event", handler)

        await bus.publish(_make_event("test_event"))

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self) -> None:
        bus = InProcessEventBus()
        h1 = AsyncMock()
        h2 = AsyncMock()
        bus.subscribe("test_event", h1)
        bus.subscribe("test_event", h2)

        event = _make_event("test_event")
        await bus.publish(event)

        h1.assert_called_once_with(event)
        h2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_handler_receives_correct_event_object(self) -> None:
        bus = InProcessEventBus()
        received: list[Event] = []

        async def capture(event: Event) -> None:
            received.append(event)

        bus.subscribe("job_discovered", capture)
        event = JobDiscovered(payload={"job_id": "abc"})
        await bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    @pytest.mark.asyncio
    async def test_publish_with_no_handlers_is_noop(self) -> None:
        bus = InProcessEventBus()
        # Must not raise
        await bus.publish(_make_event("orphan_event"))

    @pytest.mark.asyncio
    async def test_multiple_event_types_isolated(self) -> None:
        bus = InProcessEventBus()
        calls: list[str] = []

        async def handler_a(event: Event) -> None:
            calls.append("a")

        async def handler_b(event: Event) -> None:
            calls.append("b")

        bus.subscribe("event_a", handler_a)
        bus.subscribe("event_b", handler_b)

        await bus.publish(_make_event("event_a"))
        assert calls == ["a"]

        await bus.publish(_make_event("event_b"))
        assert calls == ["a", "b"]


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribed_handler_not_called(self) -> None:
        bus = InProcessEventBus()
        handler = AsyncMock()
        bus.subscribe("test_event", handler)
        bus.unsubscribe("test_event", handler)

        await bus.publish(_make_event("test_event"))

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_handlers_still_called_after_unsubscribe(self) -> None:
        bus = InProcessEventBus()
        h1 = AsyncMock()
        h2 = AsyncMock()
        bus.subscribe("test_event", h1)
        bus.subscribe("test_event", h2)
        bus.unsubscribe("test_event", h1)

        event = _make_event("test_event")
        await bus.publish(event)

        h1.assert_not_called()
        h2.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_failing_handler_does_not_stop_other_handlers(self) -> None:
        bus = InProcessEventBus()
        successful = AsyncMock()

        async def failing_handler(event: Event) -> None:
            raise RuntimeError("I always fail")

        bus.subscribe("test_event", failing_handler)
        bus.subscribe("test_event", successful)

        event = _make_event("test_event")
        # Must not propagate the exception
        await bus.publish(event)

        successful.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_all_failing_handlers_do_not_raise(self) -> None:
        bus = InProcessEventBus()

        async def always_fail(event: Event) -> None:
            raise ValueError("boom")

        bus.subscribe("test_event", always_fail)
        # Must not raise
        await bus.publish(_make_event("test_event"))

    @pytest.mark.asyncio
    async def test_error_in_one_does_not_affect_event_history(self) -> None:
        bus = InProcessEventBus()

        async def always_fail(event: Event) -> None:
            raise RuntimeError("fail")

        bus.subscribe("test_event", always_fail)
        event = _make_event("test_event")
        await bus.publish(event)

        assert event in bus.history


# ---------------------------------------------------------------------------
# Concurrent handler execution
# ---------------------------------------------------------------------------


class TestConcurrentExecution:
    @pytest.mark.asyncio
    async def test_handlers_run_concurrently(self) -> None:
        """
        Three handlers each sleep for 0.05s. If they ran sequentially the
        total time would be >=0.15s. Concurrent execution completes in ~0.05s.
        """
        bus = InProcessEventBus()
        order: list[int] = []

        async def h1(event: Event) -> None:
            await asyncio.sleep(0.05)
            order.append(1)

        async def h2(event: Event) -> None:
            await asyncio.sleep(0.05)
            order.append(2)

        async def h3(event: Event) -> None:
            await asyncio.sleep(0.05)
            order.append(3)

        bus.subscribe("test_event", h1)
        bus.subscribe("test_event", h2)
        bus.subscribe("test_event", h3)

        import time
        start = time.monotonic()
        await bus.publish(_make_event("test_event"))
        elapsed = time.monotonic() - start

        assert len(order) == 3
        # Sequential would be >=0.15s; concurrent should be well under 0.12s
        assert elapsed < 0.12, f"Expected concurrent execution, got {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_publish_is_await_safe(self) -> None:
        """publish() can be awaited inside another coroutine without deadlocking."""
        bus = InProcessEventBus()
        results: list[str] = []

        async def handler(event: Event) -> None:
            results.append(event.event_type)

        bus.subscribe("job_scored", handler)
        event = JobScored(payload={"score": 85})
        await bus.publish(event)
        assert results == ["job_scored"]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestHistory:
    @pytest.mark.asyncio
    async def test_events_recorded_in_history(self) -> None:
        bus = InProcessEventBus()
        e1 = _make_event("event_a")
        e2 = _make_event("event_b")
        await bus.publish(e1)
        await bus.publish(e2)

        assert e1 in bus.history
        assert e2 in bus.history

    @pytest.mark.asyncio
    async def test_history_is_a_copy(self) -> None:
        bus = InProcessEventBus()
        await bus.publish(_make_event("test_event"))
        history = bus.history
        history.clear()
        assert len(bus.history) == 1

    @pytest.mark.asyncio
    async def test_history_capped_at_max(self) -> None:
        bus = InProcessEventBus()
        bus._max_history = 5

        for _ in range(10):
            await bus.publish(_make_event("test_event"))

        assert len(bus.history) == 5

    @pytest.mark.asyncio
    async def test_history_retains_most_recent_events(self) -> None:
        bus = InProcessEventBus()
        bus._max_history = 3

        events = [_make_event(f"event_{i}") for i in range(5)]
        for e in events:
            await bus.publish(e)

        history = bus.history
        # Most recent 3
        assert events[2] in history
        assert events[3] in history
        assert events[4] in history
        assert events[0] not in history
        assert events[1] not in history

    @pytest.mark.asyncio
    async def test_domain_events_recorded(self) -> None:
        bus = InProcessEventBus()
        event = JobDiscovered(payload={"job_id": "xyz", "platform": "upwork"})
        await bus.publish(event)
        assert any(e.event_type == "job_discovered" for e in bus.history)
