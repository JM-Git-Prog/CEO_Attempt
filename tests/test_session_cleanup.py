"""Unit tests for session cleanup — TTL-based artifact removal."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.models import PipelineState, SessionMode, WorldSession
from src.session_manager import (
    BLEND_ARTIFACT_TTL_DAYS,
    INTERMEDIATE_TTL_HOURS,
    SessionManager,
    start_cleanup_task,
)


def _create_terminal_session(
    tmp_path: Path,
    session_id: str,
    state: PipelineState = PipelineState.READY,
) -> Path:
    """Helper: create a session dir with session.json in a terminal state."""
    session_dir = tmp_path / session_id
    (session_dir / "input").mkdir(parents=True, exist_ok=True)
    (session_dir / "output").mkdir(parents=True, exist_ok=True)
    (session_dir / "tmp").mkdir(parents=True, exist_ok=True)

    session = WorldSession(
        session_id=session_id,
        mode=SessionMode.MVP,
        state=state,
        user_description="test session",
        output_path=str(session_dir),
    )
    (session_dir / "session.json").write_text(session.model_dump_json(indent=2))
    return session_dir


def _create_nonterminal_session(
    tmp_path: Path,
    session_id: str,
    state: PipelineState = PipelineState.GENERATING_PLAN,
) -> Path:
    """Helper: create a session dir with session.json in a non-terminal state."""
    session_dir = tmp_path / session_id
    (session_dir / "input").mkdir(parents=True, exist_ok=True)
    (session_dir / "output").mkdir(parents=True, exist_ok=True)
    (session_dir / "tmp").mkdir(parents=True, exist_ok=True)

    session = WorldSession(
        session_id=session_id,
        mode=SessionMode.MVP,
        state=state,
        user_description="test session",
        output_path=str(session_dir),
    )
    (session_dir / "session.json").write_text(session.model_dump_json(indent=2))
    return session_dir


class TestCleanupExpired:
    """Test cleanup_expired() removes files based on TTL rules."""

    def test_removes_blend_files_after_ttl(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        blend_file = session_dir / "output" / "scene.blend"
        blend_file.write_bytes(b"\x00" * 100)

        mgr = SessionManager(output_base=tmp_path)
        # Simulate 8 days after completion
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(days=8)

        removed = mgr.cleanup_expired(now=now)
        assert removed >= 1
        assert not blend_file.exists()

    def test_preserves_blend_files_before_ttl(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        blend_file = session_dir / "output" / "scene.blend"
        blend_file.write_bytes(b"\x00" * 100)

        mgr = SessionManager(output_base=tmp_path)
        # Simulate only 3 days after completion (before 7-day TTL)
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(days=3)

        removed = mgr.cleanup_expired(now=now)
        # tmp/ files get removed immediately, but blend should survive
        assert blend_file.exists()

    def test_removes_intermediate_input_files_after_ttl(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        input_file = session_dir / "input" / "compiler_plan.json"
        input_file.write_text('{"plan": "data"}')

        mgr = SessionManager(output_base=tmp_path)
        # Simulate 25 hours after completion (past 24h TTL)
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(hours=25)

        removed = mgr.cleanup_expired(now=now)
        assert removed >= 1
        assert not input_file.exists()

    def test_preserves_intermediate_files_before_ttl(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        input_file = session_dir / "input" / "compiler_plan.json"
        input_file.write_text('{"plan": "data"}')

        mgr = SessionManager(output_base=tmp_path)
        # Simulate only 12 hours after completion (before 24h TTL)
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(hours=12)

        removed = mgr.cleanup_expired(now=now)
        # tmp/ gets cleaned but input/ should survive
        assert input_file.exists()

    def test_removes_tmp_files_immediately_for_terminal_sessions(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        tmp_file = session_dir / "tmp" / "scratch.dat"
        tmp_file.write_bytes(b"temporary data")

        mgr = SessionManager(output_base=tmp_path)
        # Even with now == completion time, tmp/ files are removed
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        )

        removed = mgr.cleanup_expired(now=now)
        assert removed >= 1
        assert not tmp_file.exists()

    def test_preserves_tmp_files_for_nonterminal_sessions(self, tmp_path):
        session_dir = _create_nonterminal_session(tmp_path, "s1")
        tmp_file = session_dir / "tmp" / "scratch.dat"
        tmp_file.write_bytes(b"temporary data")

        mgr = SessionManager(output_base=tmp_path)
        now = datetime.now(tz=timezone.utc) + timedelta(days=30)

        removed = mgr.cleanup_expired(now=now)
        assert removed == 0
        assert tmp_file.exists()

    def test_skips_corrupt_session_directories(self, tmp_path):
        # Create a directory with a corrupt session.json
        session_dir = tmp_path / "bad-session"
        session_dir.mkdir()
        (session_dir / "session.json").write_text("not valid json {{{")
        (session_dir / "tmp").mkdir()
        tmp_file = session_dir / "tmp" / "should_remain.dat"
        tmp_file.write_bytes(b"data")

        mgr = SessionManager(output_base=tmp_path)
        now = datetime.now(tz=timezone.utc) + timedelta(days=30)

        removed = mgr.cleanup_expired(now=now)
        assert removed == 0
        assert tmp_file.exists()

    def test_skips_directories_without_session_json(self, tmp_path):
        orphan_dir = tmp_path / "orphan"
        orphan_dir.mkdir()
        (orphan_dir / "tmp").mkdir()
        tmp_file = orphan_dir / "tmp" / "orphan_file.dat"
        tmp_file.write_bytes(b"data")

        mgr = SessionManager(output_base=tmp_path)
        now = datetime.now(tz=timezone.utc) + timedelta(days=30)

        removed = mgr.cleanup_expired(now=now)
        assert removed == 0
        assert tmp_file.exists()

    def test_returns_correct_total_count(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        (session_dir / "tmp" / "a.dat").write_bytes(b"a")
        (session_dir / "tmp" / "b.dat").write_bytes(b"b")
        (session_dir / "input" / "plan.json").write_text("{}")
        (session_dir / "output" / "scene.blend").write_bytes(b"\x00")

        mgr = SessionManager(output_base=tmp_path)
        # 8 days out — everything should be cleaned
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(days=8)

        removed = mgr.cleanup_expired(now=now)
        # 2 tmp + 1 input + 1 blend = 4
        assert removed == 4

    def test_handles_multiple_sessions(self, tmp_path):
        s1 = _create_terminal_session(tmp_path, "s1")
        (s1 / "tmp" / "t1.dat").write_bytes(b"x")

        s2 = _create_terminal_session(tmp_path, "s2", state=PipelineState.ERROR)
        (s2 / "tmp" / "t2.dat").write_bytes(b"y")

        # Non-terminal session — should be skipped
        s3 = _create_nonterminal_session(tmp_path, "s3")
        (s3 / "tmp" / "t3.dat").write_bytes(b"z")

        mgr = SessionManager(output_base=tmp_path)
        now = datetime.now(tz=timezone.utc)

        removed = mgr.cleanup_expired(now=now)
        # Only s1 and s2 tmp/ files removed (terminal), s3 preserved
        assert removed == 2
        assert not (s1 / "tmp" / "t1.dat").exists()
        assert not (s2 / "tmp" / "t2.dat").exists()
        assert (s3 / "tmp" / "t3.dat").exists()

    def test_returns_zero_when_output_dir_missing(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path / "nonexistent")
        removed = mgr.cleanup_expired()
        assert removed == 0

    def test_custom_ttl_values(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        blend_file = session_dir / "output" / "scene.blend"
        blend_file.write_bytes(b"\x00" * 100)

        # Use 1-day blend TTL
        mgr = SessionManager(output_base=tmp_path, blend_ttl_days=1)
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(days=2)

        removed = mgr.cleanup_expired(now=now)
        assert not blend_file.exists()

    def test_only_blend_suffix_removed_from_output(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        blend_file = session_dir / "output" / "scene.blend"
        blend_file.write_bytes(b"\x00")
        json_file = session_dir / "output" / "inventory.json"
        json_file.write_text("{}")

        mgr = SessionManager(output_base=tmp_path)
        now = datetime.fromtimestamp(
            (session_dir / "session.json").stat().st_mtime, tz=timezone.utc
        ) + timedelta(days=8)

        mgr.cleanup_expired(now=now)
        # .blend removed, .json in output/ preserved (not covered by blend TTL rule)
        assert not blend_file.exists()
        assert json_file.exists()


class TestCleanupSessionOnComplete:
    """Test cleanup_session_on_complete() removes tmp/ files immediately."""

    def test_removes_tmp_files(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)
        tmp_dir = tmp_path / session.session_id / "tmp"
        (tmp_dir / "scratch1.dat").write_bytes(b"data1")
        (tmp_dir / "scratch2.dat").write_bytes(b"data2")

        removed = mgr.cleanup_session_on_complete(session.session_id)
        assert removed == 2
        assert not (tmp_dir / "scratch1.dat").exists()
        assert not (tmp_dir / "scratch2.dat").exists()

    def test_returns_zero_when_no_tmp_files(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)

        removed = mgr.cleanup_session_on_complete(session.session_id)
        assert removed == 0

    def test_returns_zero_when_tmp_dir_missing(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        removed = mgr.cleanup_session_on_complete("nonexistent-session-id")
        assert removed == 0

    def test_preserves_input_and_output_files(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)
        session_dir = tmp_path / session.session_id

        # Create files in all subdirs
        (session_dir / "input" / "plan.json").write_text("{}")
        (session_dir / "output" / "scene.blend").write_bytes(b"\x00")
        (session_dir / "tmp" / "scratch.dat").write_bytes(b"tmp")

        mgr.cleanup_session_on_complete(session.session_id)

        assert (session_dir / "input" / "plan.json").exists()
        assert (session_dir / "output" / "scene.blend").exists()
        assert not (session_dir / "tmp" / "scratch.dat").exists()


class TestStartCleanupTask:
    """Test the asyncio background cleanup task."""

    @pytest.mark.asyncio
    async def test_task_runs_cleanup(self, tmp_path):
        session_dir = _create_terminal_session(tmp_path, "s1")
        (session_dir / "tmp" / "scratch.dat").write_bytes(b"data")

        mgr = SessionManager(output_base=tmp_path)
        # Use a very short interval for testing
        task = await start_cleanup_task(mgr, interval_seconds=0)

        # Give the task a moment to execute
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert not (session_dir / "tmp" / "scratch.dat").exists()

    @pytest.mark.asyncio
    async def test_task_is_cancellable(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        task = await start_cleanup_task(mgr, interval_seconds=3600)

        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_task_survives_errors(self, tmp_path):
        """The cleanup loop should not crash on exceptions."""
        mgr = SessionManager(output_base=tmp_path / "nonexistent")
        task = await start_cleanup_task(mgr, interval_seconds=0)

        # Let it run a couple iterations (no crash even though dir doesn't exist)
        await asyncio.sleep(0.1)
        assert not task.done()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
