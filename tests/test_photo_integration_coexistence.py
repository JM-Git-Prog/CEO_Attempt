"""Integration tests for photo + text pipeline coexistence.

Verifies that text pipeline sessions and photo pipeline sessions can coexist
in the same session manager and FIFO queue, with proper session isolation
(different source_types, separate output directories) and that text pipeline
behavior is unchanged after photo pipeline addition.

Requirements: 14.4, 14.5
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import PipelineState, SessionMode, WorldSession
from src.photo_pipeline.session_integration import (
    create_photo_session,
    get_session_source_type,
    queue_for_compilation,
)
from src.session_manager import SessionManager, SessionQueue


class TestTextAndPhotoSessionCoexistence:
    """Verify text and photo sessions coexist in the same SessionManager."""

    def test_text_session_has_own_output_dir_and_source_type(self, tmp_path: Path):
        """Text session: own output dir, session.json with source_type='text'."""
        mgr = SessionManager(output_base=tmp_path)

        session = mgr.create_session("A cozy living room", SessionMode.MVP)
        session_dir = Path(session.output_path)

        # Text session has its own directory
        assert session_dir.exists()
        assert session_dir.is_dir()

        # session.json exists with source_type="text" (the default)
        session_file = session_dir / "session.json"
        assert session_file.exists()
        data = json.loads(session_file.read_text(encoding="utf-8"))
        assert data["source_type"] == "text"

    def test_photo_session_has_own_output_dir_and_meta(self, tmp_path: Path):
        """Photo session: own output dir, photo_session_meta.json with source_type='photo'."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "room_photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        session_id, session_dir = create_photo_session(mgr, image)

        # Photo session has its own directory
        assert session_dir.exists()
        assert session_dir.is_dir()

        # photo_session_meta.json exists with source_type="photo"
        meta_file = session_dir / "photo_session_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["source_type"] == "photo"

    def test_both_sessions_get_unique_ids_and_separate_dirs(self, tmp_path: Path):
        """Creating both in the same session manager yields unique IDs and separate dirs."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create a text session
        text_session = mgr.create_session("Modern kitchen", SessionMode.MVP)
        text_dir = Path(text_session.output_path)

        # Create a photo session
        photo_id, photo_dir = create_photo_session(mgr, image)

        # Unique IDs
        assert text_session.session_id != photo_id

        # Separate directories
        assert text_dir != photo_dir
        assert text_dir.exists()
        assert photo_dir.exists()

        # Both under same output_base
        assert text_dir.parent == tmp_path
        assert photo_dir.parent == tmp_path

    def test_get_session_source_type_distinguishes_photo_vs_text(self, tmp_path: Path):
        """get_session_source_type() correctly identifies photo vs text sessions."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create both types
        text_session = mgr.create_session("Bedroom scene", SessionMode.MVP)
        text_dir = Path(text_session.output_path)

        photo_id, photo_dir = create_photo_session(mgr, image)

        # Correctly distinguishes
        assert get_session_source_type(text_dir) == "text"
        assert get_session_source_type(photo_dir) == "photo"

    def test_text_pipeline_behavior_unchanged(self, tmp_path: Path):
        """Text pipeline creates sessions with the expected structure unaffected by photo pipeline.

        Validates: Requirement 14.4 — existing text-to-world pipeline behavior continues
        to function identically after the photo pipeline is added.
        """
        mgr = SessionManager(output_base=tmp_path)

        # Create text session in the normal way
        session = mgr.create_session("A Victorian library", SessionMode.FULL)
        session_dir = Path(session.output_path)

        # Standard directory structure
        assert (session_dir / "input").is_dir()
        assert (session_dir / "output").is_dir()
        assert (session_dir / "tmp").is_dir()

        # session.json persisted with correct fields
        session_file = session_dir / "session.json"
        data = json.loads(session_file.read_text(encoding="utf-8"))
        assert data["session_id"] == session.session_id
        assert data["mode"] == "full"
        assert data["source_type"] == "text"
        assert data["state"] == PipelineState.AWAITING_DESCRIPTION.value

        # No photo_session_meta.json for text sessions
        assert not (session_dir / "photo_session_meta.json").exists()

    def test_multiple_sessions_of_both_types(self, tmp_path: Path):
        """Multiple text and photo sessions created concurrently remain fully isolated."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create several of each type
        text_sessions = [
            mgr.create_session(f"Room {i}", SessionMode.MVP)
            for i in range(3)
        ]
        photo_sessions = [
            create_photo_session(mgr, image)
            for _ in range(3)
        ]

        # All IDs are unique
        all_ids = [s.session_id for s in text_sessions] + [ps[0] for ps in photo_sessions]
        assert len(set(all_ids)) == 6

        # All directories are separate
        all_dirs = [Path(s.output_path) for s in text_sessions] + [ps[1] for ps in photo_sessions]
        assert len(set(all_dirs)) == 6

        # Source types are correctly identified
        for s in text_sessions:
            assert get_session_source_type(Path(s.output_path)) == "text"
        for _, photo_dir in photo_sessions:
            assert get_session_source_type(photo_dir) == "photo"


class TestFIFOQueueCoexistence:
    """Verify both session types can be enqueued in the same FIFO queue without conflict."""

    @pytest.mark.asyncio
    async def test_text_and_photo_in_same_queue(self, tmp_path: Path):
        """Both text and photo sessions can be enqueued in the same FIFO queue."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create a text session (simulate it reaching compilation stage)
        text_session = mgr.create_session("A kitchen", SessionMode.MVP)
        text_session.state = PipelineState.ASSEMBLING_WORLD
        mgr._save_session(text_session)

        # Create a photo session
        photo_id, photo_dir = create_photo_session(mgr, image)

        queue = SessionQueue()

        # Enqueue text session first
        text_starts = await queue.enqueue(text_session)
        assert text_starts is True
        assert queue.is_active(text_session.session_id)

        # Enqueue photo session — it should be queued behind text
        photo_starts = await queue_for_compilation(queue, photo_id, mgr)
        assert photo_starts is False
        assert queue.pending_count == 1

        # Text session completes — photo should become active
        next_session = await queue.complete(text_session.session_id)
        assert next_session is not None
        assert next_session.session_id == photo_id

    @pytest.mark.asyncio
    async def test_photo_then_text_in_queue(self, tmp_path: Path):
        """Photo session active, text session queued behind it."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create a photo session first
        photo_id, _ = create_photo_session(mgr, image)

        # Create a text session
        text_session = mgr.create_session("A bathroom", SessionMode.MVP)
        text_session.state = PipelineState.ASSEMBLING_WORLD
        mgr._save_session(text_session)

        queue = SessionQueue()

        # Photo session starts immediately
        photo_starts = await queue_for_compilation(queue, photo_id, mgr)
        assert photo_starts is True
        assert queue.is_active(photo_id)

        # Text session gets queued behind photo
        text_starts = await queue.enqueue(text_session)
        assert text_starts is False
        assert queue.pending_count == 1

    @pytest.mark.asyncio
    async def test_interleaved_queue_operations(self, tmp_path: Path):
        """Multiple text and photo sessions interleave through the queue correctly."""
        mgr = SessionManager(output_base=tmp_path)
        image = tmp_path / "photo.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Create sessions
        photo_id_1, _ = create_photo_session(mgr, image)
        text_session = mgr.create_session("Dining room", SessionMode.MVP)
        text_session.state = PipelineState.ASSEMBLING_WORLD
        mgr._save_session(text_session)
        photo_id_2, _ = create_photo_session(mgr, image)

        queue = SessionQueue()

        # Photo 1 starts
        await queue_for_compilation(queue, photo_id_1, mgr)
        assert queue.is_active(photo_id_1)

        # Text queued behind
        await queue.enqueue(text_session)
        assert queue.pending_count == 1

        # Photo 2 also queued
        await queue_for_compilation(queue, photo_id_2, mgr)
        assert queue.pending_count == 2

        # Complete photo 1 → text starts
        next_s = await queue.complete(photo_id_1)
        assert next_s is not None
        assert next_s.session_id == text_session.session_id

        # Complete text → photo 2 starts
        next_s = await queue.complete(text_session.session_id)
        assert next_s is not None
        assert next_s.session_id == photo_id_2
