"""Unit tests for SessionQueue — FIFO compilation queue with max 1 active compilation."""

from __future__ import annotations

import pytest

from src.models import PipelineState, SessionMode, WorldSession
from src.session_manager import SessionQueue


def _make_session(session_id: str) -> WorldSession:
    """Helper to create a minimal WorldSession for testing."""
    return WorldSession(
        session_id=session_id,
        mode=SessionMode.MVP,
        state=PipelineState.ASSEMBLING_WORLD,
        user_description=f"Test session {session_id}",
    )


class TestEnqueue:
    """Test enqueue behavior — immediate start vs queuing."""

    @pytest.mark.asyncio
    async def test_enqueue_starts_immediately_when_idle(self):
        queue = SessionQueue()
        session = _make_session("s1")
        started = await queue.enqueue(session)
        assert started is True

    @pytest.mark.asyncio
    async def test_enqueue_sets_active_session(self):
        queue = SessionQueue()
        session = _make_session("s1")
        await queue.enqueue(session)
        assert queue.active is session
        assert queue.active.session_id == "s1"

    @pytest.mark.asyncio
    async def test_enqueue_queues_when_active_compilation_exists(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        s2 = _make_session("s2")
        await queue.enqueue(s1)
        started = await queue.enqueue(s2)
        assert started is False

    @pytest.mark.asyncio
    async def test_enqueue_queued_session_not_active(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        s2 = _make_session("s2")
        await queue.enqueue(s1)
        await queue.enqueue(s2)
        assert queue.active.session_id == "s1"
        assert queue.pending_count == 1


class TestComplete:
    """Test complete behavior — promotion of next session."""

    @pytest.mark.asyncio
    async def test_complete_starts_next_queued_session(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        s2 = _make_session("s2")
        await queue.enqueue(s1)
        await queue.enqueue(s2)
        next_session = await queue.complete("s1")
        assert next_session is s2
        assert queue.active is s2

    @pytest.mark.asyncio
    async def test_complete_returns_none_when_queue_empty(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        await queue.enqueue(s1)
        next_session = await queue.complete("s1")
        assert next_session is None
        assert queue.active is None

    @pytest.mark.asyncio
    async def test_complete_clears_active_when_queue_empty(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        await queue.enqueue(s1)
        await queue.complete("s1")
        assert queue.active is None
        assert queue.pending_count == 0


class TestFIFOOrdering:
    """Test that FIFO ordering is preserved across multiple enqueue/complete cycles."""

    @pytest.mark.asyncio
    async def test_fifo_order_preserved(self):
        queue = SessionQueue()
        sessions = [_make_session(f"s{i}") for i in range(5)]

        # First session starts immediately
        await queue.enqueue(sessions[0])
        # Remaining queue up
        for s in sessions[1:]:
            await queue.enqueue(s)

        # Complete them one by one and verify FIFO order
        for i in range(1, 5):
            next_s = await queue.complete(sessions[i - 1].session_id)
            assert next_s is sessions[i]

        # Final complete empties the queue
        result = await queue.complete(sessions[4].session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_enqueue_complete_cycles(self):
        queue = SessionQueue()

        # Cycle 1: single session
        s1 = _make_session("s1")
        assert await queue.enqueue(s1) is True
        assert await queue.complete("s1") is None

        # Cycle 2: two sessions
        s2 = _make_session("s2")
        s3 = _make_session("s3")
        assert await queue.enqueue(s2) is True
        assert await queue.enqueue(s3) is False
        next_s = await queue.complete("s2")
        assert next_s is s3
        assert await queue.complete("s3") is None

        # Queue is fully idle again
        assert queue.active is None
        assert queue.pending_count == 0


class TestObservability:
    """Test observability properties and helpers."""

    @pytest.mark.asyncio
    async def test_pending_count_increments(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        s2 = _make_session("s2")
        s3 = _make_session("s3")
        await queue.enqueue(s1)
        assert queue.pending_count == 0
        await queue.enqueue(s2)
        assert queue.pending_count == 1
        await queue.enqueue(s3)
        assert queue.pending_count == 2

    @pytest.mark.asyncio
    async def test_is_active_true_for_active_session(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        await queue.enqueue(s1)
        assert queue.is_active("s1") is True

    @pytest.mark.asyncio
    async def test_is_active_false_for_queued_session(self):
        queue = SessionQueue()
        s1 = _make_session("s1")
        s2 = _make_session("s2")
        await queue.enqueue(s1)
        await queue.enqueue(s2)
        assert queue.is_active("s2") is False

    @pytest.mark.asyncio
    async def test_is_active_false_for_unknown_session(self):
        queue = SessionQueue()
        assert queue.is_active("nonexistent") is False

    @pytest.mark.asyncio
    async def test_active_is_none_when_idle(self):
        queue = SessionQueue()
        assert queue.active is None
