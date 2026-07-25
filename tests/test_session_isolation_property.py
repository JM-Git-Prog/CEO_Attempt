"""Property-based tests for Session Isolation (Property 18).

**Validates: Requirements 12.2, 12.5**

Property 18: Session Isolation Invariant
- For any set of sessions (even with identical descriptions), verify unique UUIDs,
  exclusive output directories, no cross-session file references.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from src.models import SessionMode, WorldSession
from src.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate lists of descriptions — including duplicates to test identical inputs.
# Use ASCII printable characters to avoid platform-specific encoding issues (cp1252 on Windows).
descriptions_st = st.lists(
    st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
        min_size=0,
        max_size=50,
    ),
    min_size=2,
    max_size=20,
)

# Generate session modes
modes_st = st.lists(
    st.sampled_from([SessionMode.MVP, SessionMode.FULL]),
    min_size=2,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 18: Session Isolation Invariant
# ---------------------------------------------------------------------------


@given(descriptions=descriptions_st, modes=modes_st)
@settings(max_examples=200)
def test_property_18_session_isolation(descriptions: list[str], modes: list[SessionMode]):
    """Property 18: Sessions are fully isolated from each other.

    **Validates: Requirements 12.2, 12.5**

    For any set of sessions (even with identical descriptions):
    1. All session_ids are unique (random UUIDs never collide).
    2. All output_paths are unique (exclusive output directories).
    3. Every session's output directory is a subdirectory of the output_base.
    4. No session's output_path is a prefix of another session's output_path (non-nesting).
    5. Each session's directory structure (input/, output/, tmp/) exists independently.
    6. session.json files exist only within that session's own directory.
    """
    # Align descriptions and modes to the shorter list
    count = min(len(descriptions), len(modes))
    if count < 2:
        return  # Need at least 2 sessions to test isolation

    descriptions = descriptions[:count]
    modes = modes[:count]

    # Create isolated temp directory for this test run
    tmp_dir = tempfile.mkdtemp()
    tmp_path = Path(tmp_dir)

    try:
        mgr = SessionManager(output_base=tmp_path)
        sessions: list[WorldSession] = []

        for desc, mode in zip(descriptions, modes):
            session = mgr.create_session(desc, mode)
            sessions.append(session)

        # --- Assertion 1: All session_ids are unique ---
        ids = [s.session_id for s in sessions]
        assert len(set(ids)) == len(ids), (
            f"Duplicate session IDs found: {len(ids)} sessions but only "
            f"{len(set(ids))} unique IDs"
        )

        # --- Assertion 2: All output_paths are unique ---
        paths = [s.output_path for s in sessions]
        assert len(set(paths)) == len(paths), (
            f"Duplicate output paths found: {len(paths)} sessions but only "
            f"{len(set(paths))} unique paths"
        )

        # --- Assertion 3: Every output directory is under output_base ---
        for session in sessions:
            session_path = Path(session.output_path)
            assert session_path.is_relative_to(tmp_path), (
                f"Session {session.session_id} output_path '{session.output_path}' "
                f"is not under output_base '{tmp_path}'"
            )

        # --- Assertion 4: No session's output_path is a prefix of another's (non-nesting) ---
        for i, path_i in enumerate(paths):
            for j, path_j in enumerate(paths):
                if i == j:
                    continue
                # Neither path should be a parent of the other
                assert not Path(path_j).is_relative_to(Path(path_i)), (
                    f"Session {ids[j]} output_path is nested inside session {ids[i]} "
                    f"output_path: '{path_j}' is under '{path_i}'"
                )

        # --- Assertion 5: Each session's subdirectory structure exists independently ---
        for session in sessions:
            session_dir = Path(session.output_path)
            assert (session_dir / "input").is_dir(), (
                f"Session {session.session_id} missing 'input/' subdirectory"
            )
            assert (session_dir / "output").is_dir(), (
                f"Session {session.session_id} missing 'output/' subdirectory"
            )
            assert (session_dir / "tmp").is_dir(), (
                f"Session {session.session_id} missing 'tmp/' subdirectory"
            )

        # --- Assertion 6: session.json exists only in that session's directory ---
        all_session_jsons = list(tmp_path.rglob("session.json"))
        # Each session should have exactly one session.json
        assert len(all_session_jsons) == len(sessions), (
            f"Expected {len(sessions)} session.json files but found "
            f"{len(all_session_jsons)}"
        )
        # Each session.json must be in its own session directory
        for session in sessions:
            session_json = Path(session.output_path) / "session.json"
            assert session_json.exists(), (
                f"Session {session.session_id} missing session.json at "
                f"'{session_json}'"
            )

    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
