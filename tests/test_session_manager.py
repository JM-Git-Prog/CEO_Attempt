"""Unit tests for SessionManager — session creation, isolation, and restart recovery."""

from __future__ import annotations

import json

import pytest

from src.models import PipelineState, SessionMode, WorldSession
from src.session_manager import SessionManager


class TestCreateSession:
    """Test session creation with unique IDs and directory structure."""

    def test_create_session_returns_world_session(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A cozy room", SessionMode.MVP)
        assert isinstance(session, WorldSession)

    def test_create_session_has_uuid_format(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A cozy room", SessionMode.MVP)
        # UUID4 format: 8-4-4-4-12 hex chars
        parts = session.session_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_create_session_sets_mode(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.FULL)
        assert session.mode == SessionMode.FULL

    def test_create_session_sets_description(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("Gothic library", SessionMode.MVP)
        assert session.user_description == "Gothic library"

    def test_create_session_sets_output_path(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)
        assert session.output_path == str(tmp_path / session.session_id)

    def test_create_session_creates_subdirectories(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)
        session_dir = tmp_path / session.session_id
        assert (session_dir / "input").is_dir()
        assert (session_dir / "output").is_dir()
        assert (session_dir / "tmp").is_dir()

    def test_create_session_persists_session_json(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        session = mgr.create_session("A room", SessionMode.MVP)
        session_file = tmp_path / session.session_id / "session.json"
        assert session_file.exists()
        loaded = WorldSession.model_validate_json(session_file.read_text())
        assert loaded.session_id == session.session_id
        assert loaded.user_description == "A room"
        assert loaded.mode == SessionMode.MVP

    def test_create_session_unique_ids(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        s1 = mgr.create_session("Same description", SessionMode.MVP)
        s2 = mgr.create_session("Same description", SessionMode.MVP)
        assert s1.session_id != s2.session_id

    def test_create_session_unique_directories(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        s1 = mgr.create_session("Same description", SessionMode.MVP)
        s2 = mgr.create_session("Same description", SessionMode.MVP)
        assert s1.output_path != s2.output_path


class TestMarkFailedOnRestart:
    """Test that incomplete sessions are marked failed on restart."""

    def _write_session(self, tmp_path, session_id: str, state: PipelineState):
        """Helper to write a session.json with a given state."""
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session = WorldSession(
            session_id=session_id,
            mode=SessionMode.MVP,
            state=state,
            user_description="test",
            output_path=str(session_dir),
        )
        (session_dir / "session.json").write_text(session.model_dump_json(indent=2))

    def test_marks_incomplete_sessions_as_error(self, tmp_path):
        self._write_session(tmp_path, "aaa-bbb-ccc-ddd-eee", PipelineState.GENERATING_PLAN)
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 1

        # Verify the session was updated
        session_file = tmp_path / "aaa-bbb-ccc-ddd-eee" / "session.json"
        loaded = WorldSession.model_validate_json(session_file.read_text())
        assert loaded.state == PipelineState.ERROR
        error_data = json.loads(loaded.error)
        assert error_data["reason_code"] == "server_restart"

    def test_skips_completed_sessions(self, tmp_path):
        self._write_session(tmp_path, "session-ready", PipelineState.READY)
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 0

    def test_skips_already_errored_sessions(self, tmp_path):
        self._write_session(tmp_path, "session-error", PipelineState.ERROR)
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 0

    def test_marks_multiple_incomplete_sessions(self, tmp_path):
        self._write_session(tmp_path, "s1", PipelineState.GENERATING_CONCEPT)
        self._write_session(tmp_path, "s2", PipelineState.ASSEMBLING_WORLD)
        self._write_session(tmp_path, "s3", PipelineState.READY)
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 2

    def test_returns_zero_when_no_sessions_exist(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 0

    def test_returns_zero_when_output_dir_missing(self, tmp_path):
        mgr = SessionManager(output_base=tmp_path / "nonexistent")
        count = mgr.mark_failed_on_restart()
        assert count == 0

    def test_skips_corrupted_session_files(self, tmp_path):
        session_dir = tmp_path / "bad-session"
        session_dir.mkdir(parents=True)
        (session_dir / "session.json").write_text("not valid json {{{")
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 0

    def test_skips_directories_without_session_json(self, tmp_path):
        (tmp_path / "orphan-dir").mkdir()
        mgr = SessionManager(output_base=tmp_path)
        count = mgr.mark_failed_on_restart()
        assert count == 0
