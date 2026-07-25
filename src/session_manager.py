"""
Session Manager — lifecycle, isolation, and cleanup for world-building sessions.

Handles session creation with unique UUIDs and isolated output directories,
marks incomplete sessions as failed on server restart, and enforces FIFO
compilation ordering (max 1 active UPBGE compilation at a time).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from pathlib import Path

from src.models import PipelineState, SessionMode, WorldSession

# Base directory for all session output (relative to project root)
OUTPUT_BASE = Path("output/sessions")

# Terminal states — sessions in these states are considered complete
_TERMINAL_STATES = frozenset({PipelineState.READY, PipelineState.ERROR})


class SessionManager:
    """Manages session lifecycle, isolation, and cleanup."""

    def __init__(self, output_base: Path | None = None) -> None:
        """Initialize with an optional custom output base path (useful for testing)."""
        self._output_base = output_base or OUTPUT_BASE

    @property
    def output_base(self) -> Path:
        return self._output_base

    def create_session(self, description: str, mode: SessionMode) -> WorldSession:
        """Create a new session with a unique UUID and isolated output directory.

        Generates a random UUID, creates the session's output directory structure
        (input/, output/, tmp/ subdirectories), persists session metadata as
        session.json, and returns the WorldSession instance.

        Never reuses directories even for identical descriptions.
        """
        session_id = str(uuid.uuid4())
        session_dir = self._output_base / session_id

        # Create subdirectory structure
        (session_dir / "input").mkdir(parents=True, exist_ok=True)
        (session_dir / "output").mkdir(parents=True, exist_ok=True)
        (session_dir / "tmp").mkdir(parents=True, exist_ok=True)

        session = WorldSession(
            session_id=session_id,
            mode=mode,
            user_description=description,
            output_path=str(session_dir),
            state=PipelineState.AWAITING_DESCRIPTION,
        )

        # Persist session metadata
        self._save_session(session)

        return session

    def mark_failed_on_restart(self) -> int:
        """Mark any incomplete sessions as failed with reason_code 'server_restart'.

        Scans existing session directories, loads session.json from each,
        checks if the session state is not in a terminal state (READY or ERROR),
        and if so updates the state to ERROR with reason_code in the error field.

        Returns the count of sessions marked as failed.
        """
        if not self._output_base.exists():
            return 0

        count = 0
        for session_dir in self._output_base.iterdir():
            if not session_dir.is_dir():
                continue

            session_file = session_dir / "session.json"
            if not session_file.exists():
                continue

            try:
                session = WorldSession.model_validate_json(session_file.read_text())
            except Exception:
                # Corrupted session file — skip it
                continue

            if session.state not in _TERMINAL_STATES:
                session.state = PipelineState.ERROR
                session.error = json.dumps({"reason_code": "server_restart"})
                self._save_session(session)
                count += 1

        return count

    def _save_session(self, session: WorldSession) -> None:
        """Persist session metadata to session.json inside the session's output directory."""
        session_dir = self._output_base / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / "session.json"
        session_file.write_text(session.model_dump_json(indent=2))


class SessionQueue:
    """FIFO compilation queue — max 1 active UPBGE compilation at a time.

    Pre-compilation stages (interpret, plan, validate, scene graph) can proceed
    concurrently; only sidecar compilation is serialized through this queue.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active: WorldSession | None = None
        self._pending: deque[WorldSession] = deque()

    @property
    def active(self) -> WorldSession | None:
        """The currently active compilation session, or None if idle."""
        return self._active

    @property
    def pending_count(self) -> int:
        """Number of sessions waiting in the queue."""
        return len(self._pending)

    def is_active(self, session_id: str) -> bool:
        """Check whether a given session is the currently active compilation."""
        return self._active is not None and self._active.session_id == session_id

    async def enqueue(self, session: WorldSession) -> bool:
        """Add session to the compilation queue.

        Returns True if the session starts immediately (no active compilation),
        or False if it was queued behind the current active compilation.
        """
        async with self._lock:
            if self._active is None:
                self._active = session
                return True
            else:
                self._pending.append(session)
                return False

    async def complete(self, session_id: str) -> WorldSession | None:
        """Mark the active compilation done and start the next queued session.

        Returns the next session that was promoted to active, or None if the
        queue was empty.
        """
        async with self._lock:
            if self._active is not None and self._active.session_id == session_id:
                self._active = None
            if self._pending:
                next_session = self._pending.popleft()
                self._active = next_session
                return next_session
            return None
