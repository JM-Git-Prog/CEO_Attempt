"""Property-based tests for SessionQueue FIFO ordering (Property 19).

**Validates: Requirements 12.1**

Property 19: FIFO Queue Ordering
- For any sequence of session submissions arriving while a compilation is active,
  the SessionQueue SHALL process them in exact submission order when complete() is
  called on the active session.
- At most ONE session is active at any time.
- After all sessions complete, the queue returns to idle state.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings, strategies as st

from src.models import PipelineState, SessionMode, WorldSession
from src.session_manager import SessionQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(session_id: str) -> WorldSession:
    """Create a minimal WorldSession for testing."""
    return WorldSession(
        session_id=session_id,
        mode=SessionMode.MVP,
        state=PipelineState.ASSEMBLING_WORLD,
        user_description=f"Test session {session_id}",
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate unique session ID lists (2-20 items) using text with a minimum length
# to avoid empty IDs. We use unique IDs to model distinct sessions.
session_ids_st = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
    min_size=2,
    max_size=20,
    unique=True,
)


# ---------------------------------------------------------------------------
# Property 19: FIFO Queue Ordering
# ---------------------------------------------------------------------------


@given(session_ids=session_ids_st)
@settings(max_examples=200)
def test_property_19_fifo_queue_ordering(session_ids: list[str]):
    """Property 19: FIFO ordering is preserved for queued sessions.

    **Validates: Requirements 12.1**

    For any sequence of session submissions arriving while a compilation is active:
    1. The first session starts immediately (enqueue returns True).
    2. Subsequent sessions are queued (enqueue returns False).
    3. complete() promotes sessions in exact FIFO submission order.
    4. At most ONE session is active at any time.
    5. After all sessions complete, queue is idle (active=None, pending_count=0).
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_verify_fifo_ordering(session_ids))
    finally:
        loop.close()


async def _verify_fifo_ordering(session_ids: list[str]) -> None:
    """Async helper that drives the queue and asserts FIFO properties."""
    queue = SessionQueue()
    sessions = [_make_session(sid) for sid in session_ids]

    # --- Enqueue phase ---
    # First session starts immediately
    first_result = await queue.enqueue(sessions[0])
    assert first_result is True, (
        f"First session '{session_ids[0]}' should start immediately but enqueue returned False"
    )
    assert queue.active is sessions[0], (
        f"Active session should be '{session_ids[0]}' after first enqueue"
    )

    # Remaining sessions queue behind
    for i, session in enumerate(sessions[1:], start=1):
        result = await queue.enqueue(session)
        assert result is False, (
            f"Session '{session_ids[i]}' (index {i}) should be queued but enqueue returned True"
        )

    # Verify pending count matches
    assert queue.pending_count == len(sessions) - 1, (
        f"Expected {len(sessions) - 1} pending sessions but got {queue.pending_count}"
    )

    # --- Completion phase: verify FIFO order ---
    # At most ONE session active at any time (invariant checked throughout)
    assert queue.active is sessions[0], (
        "Active session should still be the first session before completions begin"
    )

    for i in range(len(sessions) - 1):
        # Complete the current active session
        next_session = await queue.complete(sessions[i].session_id)

        # The promoted session must be the next in FIFO order
        expected = sessions[i + 1]
        assert next_session is expected, (
            f"After completing session '{session_ids[i]}', expected next session "
            f"'{session_ids[i + 1]}' but got '{next_session.session_id if next_session else None}'"
        )

        # Exactly one session active
        assert queue.active is expected, (
            f"Active session should be '{session_ids[i + 1]}' but got "
            f"'{queue.active.session_id if queue.active else None}'"
        )

    # Complete the last session — queue should be empty
    final_result = await queue.complete(sessions[-1].session_id)
    assert final_result is None, (
        f"After completing last session '{session_ids[-1]}', expected None but got "
        f"'{final_result.session_id if final_result else final_result}'"
    )

    # --- Idle state ---
    assert queue.active is None, (
        "Queue should have no active session after all completions"
    )
    assert queue.pending_count == 0, (
        f"Queue should have 0 pending after all completions but got {queue.pending_count}"
    )
