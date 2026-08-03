"""
Session Manager — lifecycle, isolation, and cleanup for world-building sessions.

Handles session creation with unique UUIDs and isolated output directories,
marks incomplete sessions as failed on server restart, enforces FIFO
compilation ordering (max 1 active UPBGE compilation at a time), and
performs configurable TTL-based cleanup of session artifacts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import PipelineState, SessionMode, WorldSession

logger = logging.getLogger(__name__)

# Base directory for all session output (relative to project root)
OUTPUT_BASE = Path("output/sessions")

# Terminal states — sessions in these states are considered complete
_TERMINAL_STATES = frozenset({PipelineState.READY, PipelineState.ERROR})

# --- Cleanup TTL configuration defaults ---
BLEND_ARTIFACT_TTL_DAYS: int = 7
INTERMEDIATE_TTL_HOURS: int = 24
CLEANUP_INTERVAL_SECONDS: int = 3600  # 1 hour


class SessionManager:
    """Manages session lifecycle, isolation, and cleanup."""

    def __init__(
        self,
        output_base: Path | None = None,
        blend_ttl_days: int = BLEND_ARTIFACT_TTL_DAYS,
        intermediate_ttl_hours: int = INTERMEDIATE_TTL_HOURS,
    ) -> None:
        """Initialize with optional custom output base path and TTL settings."""
        self._output_base = output_base or OUTPUT_BASE
        self._blend_ttl = timedelta(days=blend_ttl_days)
        self._intermediate_ttl = timedelta(hours=intermediate_ttl_hours)

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

                # Also stamp session_meta.json if it exists (V16 dual-state fix)
                meta_path = session_dir / "session_meta.json"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        meta["state"] = "error"
                        meta["error"] = json.dumps({"reason_code": "server_restart"})
                        meta_path.write_text(
                            json.dumps(meta, indent=2), encoding="utf-8"
                        )
                    except (OSError, ValueError, TypeError):
                        logger.warning(
                            "Failed to update session_meta.json for %s",
                            session_dir.name,
                        )

                count += 1

        return count

    def _save_session(self, session: WorldSession) -> None:
        """Persist session metadata to session.json inside the session's output directory."""
        session_dir = self._output_base / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / "session.json"
        session_file.write_text(session.model_dump_json(indent=2))

    def _get_session_completion_time(self, session_dir: Path) -> datetime | None:
        """Read session.json and return completion time if session is in a terminal state.

        Returns None if session is not terminal, session.json is missing/corrupt,
        or there's no way to determine completion time.
        """
        session_file = session_dir / "session.json"
        if not session_file.exists():
            return None

        try:
            session = WorldSession.model_validate_json(session_file.read_text())
        except Exception:
            return None

        if session.state not in _TERMINAL_STATES:
            return None

        # Use session.json mtime as proxy for completion time
        return datetime.fromtimestamp(session_file.stat().st_mtime, tz=timezone.utc)

    def cleanup_session_on_complete(self, session_id: str) -> int:
        """Immediately remove tmp/ files for a completed session.

        Returns the count of files removed.
        """
        session_dir = self._output_base / session_id
        tmp_dir = session_dir / "tmp"

        if not tmp_dir.exists():
            return 0

        count = 0
        for f in tmp_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    count += 1
                except OSError:
                    logger.warning("Failed to remove tmp file: %s", f)
        return count

    def cleanup_expired(self, now: datetime | None = None) -> int:
        """Scan session directories and remove files past their TTL.

        TTL rules:
        - .blend files in output/ → removed after blend_ttl (default 7 days)
        - Intermediate files in input/ (*.json, etc.) → removed after intermediate_ttl (default 24h)
        - Files in tmp/ → removed immediately when session state is terminal (READY or ERROR)

        Args:
            now: Current time (injectable for testing). Defaults to UTC now.

        Returns:
            Total count of files removed across all sessions.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc)

        if not self._output_base.exists():
            return 0

        total_removed = 0

        for session_dir in self._output_base.iterdir():
            if not session_dir.is_dir():
                continue

            completion_time = self._get_session_completion_time(session_dir)
            if completion_time is None:
                # Session not terminal or session.json missing/corrupt — skip
                continue

            # Remove tmp/ files immediately for terminal sessions
            tmp_dir = session_dir / "tmp"
            if tmp_dir.exists():
                for f in tmp_dir.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                            total_removed += 1
                        except OSError:
                            logger.warning("Failed to remove tmp file: %s", f)

            # Remove .blend files in output/ after blend TTL
            output_dir = session_dir / "output"
            if output_dir.exists():
                elapsed = now - completion_time
                if elapsed >= self._blend_ttl:
                    for f in output_dir.iterdir():
                        if f.is_file() and f.suffix == ".blend":
                            try:
                                f.unlink()
                                total_removed += 1
                            except OSError:
                                logger.warning("Failed to remove blend artifact: %s", f)

            # Remove intermediate files in input/ after intermediate TTL
            input_dir = session_dir / "input"
            if input_dir.exists():
                elapsed = now - completion_time
                if elapsed >= self._intermediate_ttl:
                    for f in input_dir.iterdir():
                        if f.is_file():
                            try:
                                f.unlink()
                                total_removed += 1
                            except OSError:
                                logger.warning("Failed to remove intermediate file: %s", f)

        return total_removed


async def start_cleanup_task(
    manager: SessionManager,
    interval_seconds: int = CLEANUP_INTERVAL_SECONDS,
) -> asyncio.Task:
    """Create and return an asyncio background task that runs cleanup every interval.

    The task runs indefinitely until cancelled.

    Args:
        manager: SessionManager instance to use for cleanup.
        interval_seconds: Seconds between cleanup runs (default: 3600 = 1 hour).

    Returns:
        The created asyncio.Task.
    """

    async def _cleanup_loop() -> None:
        while True:
            try:
                removed = manager.cleanup_expired()
                if removed > 0:
                    logger.info("Session cleanup: removed %d expired files", removed)
            except Exception:
                logger.exception("Error during session cleanup")
            await asyncio.sleep(interval_seconds)

    task = asyncio.create_task(_cleanup_loop(), name="session-cleanup")
    return task


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
