"""Unit tests for V14 web routes (Task 16.2).

Tests URL routing (`?v=14` default, `?v=13` still works), GLB serving,
SSE event format, and session metadata.

Requirements: 8.6, 12.4, 12.5
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.web import app as web


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with OUTPUT_DIR pointing to tmp_path."""
    web.sessions.clear()
    web._mvp_tasks.clear()
    monkeypatch.setattr(web, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        web, "append_event",
        lambda root, payload: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "app_version": str(payload.get("app_version", 14)),
        },
    )
    with TestClient(web.app) as test_client:
        yield test_client
    web.sessions.clear()
    web._mvp_tasks.clear()


# ---------------------------------------------------------------------------
# 1. URL Routing: ?v=14 default, ?v=13 still works (Req 8.6, 12.4)
# ---------------------------------------------------------------------------


class TestVersionRouting:
    """Test that V14 is the default and previous versions remain accessible."""

    def test_get_index_v14_explicit(self, client):
        """GET /?v=14 returns 200 with V14 content."""
        resp = client.get("/?v=14")
        assert resp.status_code == 200
        assert "V14" in resp.text
        assert "Real 3D World" in resp.text

    def test_get_index_no_version_defaults_to_v16(self, client):
        """GET / with no v param defaults to the additive V16 interface."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "V16 Unified World Pipeline" in resp.text

    def test_get_index_v13_still_works(self, client):
        """GET /?v=13 returns 200 and serves V13 (Req 12.4)."""
        resp = client.get("/?v=13")
        assert resp.status_code == 200
        # V13 page should NOT contain the V14 template header
        # It uses the standard template with version nav
        assert "V13" in resp.text.upper() or "v=13" in resp.text

    def test_get_index_v11_still_accessible(self, client):
        """GET /?v=11 returns 200, preserving older versions (Req 12.4)."""
        resp = client.get("/?v=11")
        assert resp.status_code == 200

    def test_get_index_invalid_version_returns_400(self, client):
        """GET /?v=999 returns 400 for unsupported version."""
        resp = client.get("/?v=999")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 2. POST /api/session/v14/photo (Req 12.5)
# ---------------------------------------------------------------------------


class TestV14PhotoEndpoint:
    """Test the V14 photo session creation endpoint."""

    def test_photo_valid_source_image_returns_200(self, client, tmp_path):
        """POST /api/session/v14/photo with valid source_image returns 200 with session_id."""
        # Create a dummy image file
        img = tmp_path / "test_photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch(
            "src.photo_pipeline.orchestrator.PhotoPipelineOrchestrator"
        ) as MockOrch:
            mock_instance = AsyncMock()
            MockOrch.return_value = mock_instance
            # Mock the run method to simulate background task
            mock_instance.run = AsyncMock()

            resp = client.post(
                "/api/session/v14/photo",
                json={"source_image": str(img)},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["interface_version"] == 14
        assert data["source_type"] == "photo"
        assert data["state"] == "started"
        assert "events_url" in data
        assert "/v14/events" in data["events_url"]
        assert "room_shell_url" in data
        assert "mesh_url_template" in data
        assert "materials_ws_url" in data

    def test_photo_missing_image_returns_400(self, client):
        """POST /api/session/v14/photo with missing image returns 400."""
        resp = client.post(
            "/api/session/v14/photo",
            json={"source_image": ""},
        )
        assert resp.status_code == 400
        assert "source_image" in resp.json()["error"].lower() or "required" in resp.json()["error"].lower()

    def test_photo_nonexistent_file_returns_400(self, client):
        """POST /api/session/v14/photo with nonexistent file path returns 400."""
        resp = client.post(
            "/api/session/v14/photo",
            json={"source_image": "/nonexistent/path/image.jpg"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["error"].lower()

    def test_photo_no_body_returns_400(self, client):
        """POST /api/session/v14/photo with no body returns 400."""
        resp = client.post(
            "/api/session/v14/photo",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_photo_session_metadata_includes_interface_version_14(self, client, tmp_path):
        """V14 session metadata includes interface_version=14 (Req 12.5)."""
        img = tmp_path / "test_photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch(
            "src.photo_pipeline.orchestrator_v14.V14Orchestrator"
        ) as MockOrch:
            mock_instance = AsyncMock()
            MockOrch.return_value = mock_instance
            mock_instance.run = AsyncMock()

            resp = client.post(
                "/api/session/v14/photo",
                json={"source_image": str(img)},
            )

        data = resp.json()
        session_id = data["session_id"]

        # Read the persisted session metadata
        meta_path = tmp_path / session_id / "session_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["interface_version"] == 14
        assert meta["session_id"] == session_id
        assert meta["source_type"] == "photo"
        assert meta["state"] == "started"


# ---------------------------------------------------------------------------
# 3. GET /api/session/{id}/room_shell — GLB serving (Req 8.5)
# ---------------------------------------------------------------------------


class TestRoomShellEndpoint:
    """Test the room shell GLB serving endpoint."""

    def test_room_shell_returns_404_when_no_session(self, client):
        """GET /api/session/{id}/room_shell returns 404 when no session exists."""
        resp = client.get("/api/session/nonexistent/room_shell")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    def test_room_shell_returns_200_with_glb_when_exists(self, client, tmp_path):
        """GET /api/session/{id}/room_shell returns 200 with GLB content when file exists."""
        session_id = "test1234"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        # Create a dummy GLB file (glTF binary magic: glTF\x02\x00\x00\x00)
        glb_content = b"glTF\x02\x00\x00\x00" + b"\x00" * 100
        (session_dir / "room_shell.glb").write_bytes(glb_content)

        resp = client.get(f"/api/session/{session_id}/room_shell")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "model/gltf-binary"
        assert resp.content == glb_content

    def test_room_shell_has_no_cache_header(self, client, tmp_path):
        """Room shell response includes Cache-Control: no-store header."""
        session_id = "sess5678"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "room_shell.glb").write_bytes(b"glTF" + b"\x00" * 50)

        resp = client.get(f"/api/session/{session_id}/room_shell")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# 4. SSE endpoint: /api/session/{id}/v14/events (Req 8.4, 9.4)
# ---------------------------------------------------------------------------


class TestV14SSEEvents:
    """Test the V14-specific SSE event stream."""

    def test_sse_returns_text_event_stream_content_type(self, client, tmp_path):
        """SSE endpoint returns text/event-stream content type."""
        session_id = "sse_test"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        # Create a completed session meta so the stream terminates quickly
        meta = {"state": "completed", "object_count": 3, "quality_classification": "full"}
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        resp = client.get(f"/api/session/{session_id}/v14/events")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    def test_sse_returns_404_for_nonexistent_session(self, client):
        """SSE endpoint returns 404 for a session that doesn't exist."""
        resp = client.get("/api/session/nonexistent/v14/events")
        assert resp.status_code == 404

    def test_sse_emits_done_event_for_completed_session(self, client, tmp_path):
        """SSE emits a terminal 'done' event when session is completed."""
        session_id = "sse_done"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        meta = {
            "state": "completed",
            "object_count": 5,
            "quality_classification": "full",
        }
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        resp = client.get(f"/api/session/{session_id}/v14/events")
        assert resp.status_code == 200

        # Parse SSE data lines
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1

        terminal = json.loads(data_lines[-1].replace("data: ", ""))
        assert terminal["type"] == "done"
        assert terminal["state"] == "completed"
        assert terminal["object_count"] == 5
        assert terminal["quality_classification"] == "full"
        assert "room_shell_url" in terminal
        assert "elapsed" in terminal

    def test_sse_emits_error_event_for_failed_session(self, client, tmp_path):
        """SSE emits an 'error' event when session failed."""
        session_id = "sse_err"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        meta = {"state": "error", "error": "ComfyUI unreachable"}
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        resp = client.get(f"/api/session/{session_id}/v14/events")
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1

        error_event = json.loads(data_lines[-1].replace("data: ", ""))
        assert error_event["type"] == "error"
        assert error_event["state"] == "error"
        assert "ComfyUI unreachable" in error_event["error"]

    def test_sse_streams_progress_events_from_jsonl(self, client, tmp_path):
        """SSE streams progress events from v14_events.jsonl file."""
        session_id = "sse_prog"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        # Write some progress events
        events = [
            {"type": "stage_change", "stage": "segmentation", "objects_total": 5},
            {"type": "object_complete", "object_id": "obj_01", "objects_complete": 1, "objects_total": 5},
        ]
        events_content = "\n".join(json.dumps(e) for e in events)
        (session_dir / "v14_events.jsonl").write_text(events_content, encoding="utf-8")

        # Also mark the session as completed so the stream terminates
        meta = {"state": "completed", "object_count": 5, "quality_classification": "full"}
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        resp = client.get(f"/api/session/{session_id}/v14/events")
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        # Should have progress events + terminal done event
        assert len(data_lines) >= 3

        # First event should be the stage_change
        first = json.loads(data_lines[0].replace("data: ", ""))
        assert first["type"] == "stage_change"
        assert first["stage"] == "segmentation"
        assert "elapsed" in first

    def test_sse_no_cache_headers(self, client, tmp_path):
        """SSE response has appropriate headers for streaming."""
        session_id = "sse_hdrs"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)

        meta = {"state": "completed", "object_count": 0, "quality_classification": "minimal"}
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

        resp = client.get(f"/api/session/{session_id}/v14/events")
        assert resp.status_code == 200
        assert "no-cache" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# 5. V14 sessions list endpoint
# ---------------------------------------------------------------------------


class TestV14SessionsList:
    """Test the V14 sessions list endpoint."""

    def test_v14_sessions_endpoint_returns_200(self, client):
        """GET /api/v14/sessions should return 200 with a list."""
        resp = client.get("/api/v14/sessions")
        assert resp.status_code == 200
