"""Unit tests for photo pipeline session integration.

Validates session creation, metadata persistence, queue integration,
and source_type discrimination (Requirements 11.1, 11.7, 14.5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import PipelineState, SessionMode
from src.photo_pipeline.models import PhotoSessionMetadata
from src.photo_pipeline.session_integration import (
    create_photo_session,
    get_session_source_type,
    store_photo_session_metadata,
    queue_for_compilation,
)
from src.session_manager import SessionManager, SessionQueue


class TestCreatePhotoSession:
    """Tests for create_photo_session()."""

    def test_returns_session_id_and_path(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, session_dir = create_photo_session(mgr, image)

        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID4 format
        assert session_dir.exists()
        assert session_dir.is_dir()

    def test_creates_session_directory_structure(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, session_dir = create_photo_session(mgr, image)

        assert (session_dir / "input").is_dir()
        assert (session_dir / "output").is_dir()
        assert (session_dir / "tmp").is_dir()

    def test_writes_photo_meta_stub(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "scene.jpg"
        image.write_bytes(b"\xff\xd8\xff")

        session_id, session_dir = create_photo_session(mgr, image)

        meta_file = session_dir / "photo_session_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["source_type"] == "photo"
        assert meta["source_image_path"] == str(image)
        assert meta["session_id"] == session_id

    def test_persists_session_json(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, session_dir = create_photo_session(mgr, image)

        session_file = session_dir / "session.json"
        assert session_file.exists()
        data = json.loads(session_file.read_text(encoding="utf-8"))
        assert data["session_id"] == session_id
        assert data["mode"] == "mvp"

    def test_unique_sessions(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        id1, dir1 = create_photo_session(mgr, image)
        id2, dir2 = create_photo_session(mgr, image)

        assert id1 != id2
        assert dir1 != dir2

    def test_accepts_full_mode(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, session_dir = create_photo_session(
            mgr, image, mode=SessionMode.FULL
        )

        session_file = session_dir / "session.json"
        data = json.loads(session_file.read_text(encoding="utf-8"))
        assert data["mode"] == "full"


class TestStorePhotoSessionMetadata:
    """Tests for store_photo_session_metadata()."""

    def test_writes_metadata_json(self, tmp_path: Path):
        session_dir = tmp_path / "test-session"
        session_dir.mkdir()

        metadata = PhotoSessionMetadata(
            source_image_path=Path("/images/room.png"),
            source_image_hash="abc123def456",
            source_resolution=(1920, 1080),
            quality_classification="full",
            object_count=5,
            primary_methods_succeeded=4,
            fallbacks_used=1,
            total_pipeline_duration_s=320.5,
        )

        result_path = store_photo_session_metadata(session_dir, metadata)

        assert result_path.exists()
        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["source_type"] == "photo"
        assert data["source_image_hash"] == "abc123def456"
        assert data["source_resolution"] == [1920, 1080]
        assert data["quality_classification"] == "full"
        assert data["object_count"] == 5
        assert data["primary_methods_succeeded"] == 4
        assert data["fallbacks_used"] == 1
        assert data["total_pipeline_duration_s"] == 320.5

    def test_source_image_path_is_string(self, tmp_path: Path):
        session_dir = tmp_path / "test-session"
        session_dir.mkdir()

        metadata = PhotoSessionMetadata(
            source_image_path=Path("C:/photos/my_room.jpg"),
            source_image_hash="deadbeef",
            source_resolution=(3840, 2160),
            quality_classification="degraded",
            object_count=3,
            primary_methods_succeeded=2,
            fallbacks_used=1,
            total_pipeline_duration_s=180.0,
        )

        result_path = store_photo_session_metadata(session_dir, metadata)
        data = json.loads(result_path.read_text(encoding="utf-8"))

        # Path should be serialized as a string, not a Path object repr
        assert isinstance(data["source_image_path"], str)
        assert "PosixPath" not in data["source_image_path"]
        assert "WindowsPath" not in data["source_image_path"]

    def test_overwrites_existing_meta(self, tmp_path: Path):
        session_dir = tmp_path / "test-session"
        session_dir.mkdir()

        # Write initial stub
        (session_dir / "photo_session_meta.json").write_text('{"source_type": "photo"}')

        metadata = PhotoSessionMetadata(
            source_image_path=Path("/img.png"),
            source_image_hash="hash1",
            source_resolution=(512, 512),
            quality_classification="minimal",
            object_count=0,
            primary_methods_succeeded=0,
            fallbacks_used=0,
            total_pipeline_duration_s=60.0,
        )

        store_photo_session_metadata(session_dir, metadata)

        data = json.loads(
            (session_dir / "photo_session_meta.json").read_text(encoding="utf-8")
        )
        assert data["object_count"] == 0
        assert data["quality_classification"] == "minimal"


class TestGetSessionSourceType:
    """Tests for get_session_source_type()."""

    def test_photo_session_detected(self, tmp_path: Path):
        session_dir = tmp_path / "session-1"
        session_dir.mkdir()
        (session_dir / "photo_session_meta.json").write_text(
            json.dumps({"source_type": "photo"})
        )

        assert get_session_source_type(session_dir) == "photo"

    def test_text_session_when_no_meta(self, tmp_path: Path):
        session_dir = tmp_path / "session-2"
        session_dir.mkdir()

        assert get_session_source_type(session_dir) == "text"

    def test_text_session_when_meta_has_text_type(self, tmp_path: Path):
        session_dir = tmp_path / "session-3"
        session_dir.mkdir()
        (session_dir / "photo_session_meta.json").write_text(
            json.dumps({"source_type": "text"})
        )

        assert get_session_source_type(session_dir) == "text"

    def test_text_session_when_meta_is_corrupt(self, tmp_path: Path):
        session_dir = tmp_path / "session-4"
        session_dir.mkdir()
        (session_dir / "photo_session_meta.json").write_text("{{not json}}")

        assert get_session_source_type(session_dir) == "text"

    def test_text_session_when_dir_missing(self, tmp_path: Path):
        session_dir = tmp_path / "nonexistent"

        assert get_session_source_type(session_dir) == "text"


class TestQueueForCompilation:
    """Tests for queue_for_compilation()."""

    @pytest.mark.asyncio
    async def test_enqueues_photo_session(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, _ = create_photo_session(mgr, image)
        queue = SessionQueue()

        starts_immediately = await queue_for_compilation(queue, session_id, mgr)

        assert starts_immediately is True
        assert queue.is_active(session_id)

    @pytest.mark.asyncio
    async def test_queues_behind_active_session(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        # Create two sessions
        id1, _ = create_photo_session(mgr, image)
        id2, _ = create_photo_session(mgr, image)
        queue = SessionQueue()

        # First session starts immediately
        await queue_for_compilation(queue, id1, mgr)

        # Second session gets queued
        starts_immediately = await queue_for_compilation(queue, id2, mgr)

        assert starts_immediately is False
        assert queue.is_active(id1)
        assert queue.pending_count == 1

    @pytest.mark.asyncio
    async def test_updates_session_state(self, tmp_path: Path):
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG")

        session_id, session_dir = create_photo_session(mgr, image)
        queue = SessionQueue()

        await queue_for_compilation(queue, session_id, mgr)

        # Session state should be updated to ASSEMBLING_WORLD
        session_file = session_dir / "session.json"
        data = json.loads(session_file.read_text(encoding="utf-8"))
        assert data["state"] == PipelineState.ASSEMBLING_WORLD.value
