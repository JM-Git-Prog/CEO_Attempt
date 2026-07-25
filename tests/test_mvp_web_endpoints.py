"""Tests for MVP mode web endpoints (Task 11.1, Requirements 9.1, 9.2, 9.3)."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.models import PipelineState, SessionMode, WorldSession
from src.web import app as web
from src.workflow_provenance import profile_for


class StubBuilder:
    """Minimal WorldBuilder stub for endpoint testing."""

    root = None

    def __init__(self, session_id=None, interface_version=11):
        profile = profile_for(interface_version)
        self.session = WorldSession(
            session_id=session_id or uuid4().hex[:8],
            interface_version=interface_version,
            workflow_profile_id=profile["id"],
            workflow_profile=profile,
        )
        self.output_dir = self.root / self.session.session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self):
        return None

    async def run_mvp(self, description: str, **kwargs):
        """Simulate MVP pipeline: emit SSE events and complete."""
        from src.models import PipelineState

        # Simulate stage emissions
        self.session.progress_messages.append("sse:interpreting:0.1s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:planning:1.2s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:building_scene:3.0s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:compiling:5.0s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:validating:8.0s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:launching:9.0s")
        await asyncio.sleep(0.01)
        self.session.progress_messages.append("sse:game_running:10.0s")

        # Simulate success
        self.session.state = PipelineState.READY
        self.session.game_pid = 12345
        self.session.quality_label = "smoke_structural"
        blend_path = self.output_dir / "game.blend"
        blend_path.write_bytes(b"BLENDER_FAKE_DATA")
        self.session.output_path = str(blend_path)

        # Return a mock result (not strictly needed since background task handles it)
        from dataclasses import dataclass
        from pathlib import Path

        @dataclass
        class FakeResult:
            success: bool = True
            failure_diagnostic: str | None = None
            failure_reason_code: str | None = None

        return FakeResult()

    async def step_interpret(self, description):
        pass

    async def step_build_floor_plan(self, feedback=None):
        from src.models import FloorPlan
        return FloorPlan(width=5.0, depth=4.0, height=3.0, objects=[])


@pytest.fixture
def client(tmp_path, monkeypatch):
    StubBuilder.root = tmp_path
    web.sessions.clear()
    web._mvp_tasks.clear()
    monkeypatch.setattr(web, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(web, "WorldBuilder", StubBuilder)
    monkeypatch.setattr(
        web, "append_event",
        lambda root, payload: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "app_version": str(payload.get("app_version", 11)),
        },
    )
    with TestClient(web.app) as test_client:
        yield test_client
    web.sessions.clear()
    web._mvp_tasks.clear()


class TestDescribeMvpEndpoint:
    """Tests for POST /api/session/{id}/describe_mvp."""

    def test_mvp_describe_returns_immediately_with_events_url(self, client):
        """MVP describe should return immediately with session info and events URL."""
        # Create session first
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        # Submit MVP describe
        resp = client.post(
            f"/api/session/{session_id}/describe_mvp",
            json={"description": "A cozy living room with a fireplace", "mode": "mvp"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "mvp"
        assert data["session_id"] == session_id
        assert "events_url" in data
        assert f"/api/session/{session_id}/events" in data["events_url"]

    def test_mvp_describe_empty_description_rejected(self, client):
        """Empty description should be rejected with 400."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        resp = client.post(
            f"/api/session/{session_id}/describe_mvp",
            json={"description": "", "mode": "mvp"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 400

    def test_mvp_describe_defaults_to_mvp_mode(self, client):
        """When no mode specified, should default to mvp."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        resp = client.post(
            f"/api/session/{session_id}/describe_mvp",
            json={"description": "A kitchen with modern appliances"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "mvp"


class TestSSEEventsEndpoint:
    """Tests for GET /api/session/{id}/events."""

    def test_events_404_for_unknown_session(self, client):
        """Should return 404 for non-existent session."""
        resp = client.get(
            "/api/session/nonexistent/events",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 404

    def test_events_streams_sse_for_completed_session(self, client):
        """Should stream SSE events for a session that has progress messages."""
        # Create session and put it in a terminal state with some SSE messages
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.progress_messages = [
            "sse:interpreting:0.1s",
            "sse:planning:1.5s",
            "sse:building_scene:3.0s",
        ]
        builder.session.state = PipelineState.READY
        builder.session.quality_label = "smoke_structural"
        builder.session.game_pid = 9999

        # Stream events
        resp = client.get(
            f"/api/session/{session_id}/events",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Parse SSE data lines
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 4  # 3 stage events + 1 terminal

        # Verify stage events
        first_event = json.loads(data_lines[0].replace("data: ", ""))
        assert first_event["stage"] == "interpreting"

        # Verify terminal event
        terminal = json.loads(data_lines[-1].replace("data: ", ""))
        assert terminal["stage"] == "done"
        assert terminal["state"] == "ready"
        assert terminal["game_running"] is True
        assert "download_url" in terminal

    def test_events_terminal_includes_failure_info_on_error(self, client):
        """SSE terminal event should include structured failure info (Req 9.4, 9.5)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.progress_messages = [
            "sse:interpreting:0.1s",
            "sse:compiling:2.0s",
        ]
        builder.session.state = PipelineState.ERROR
        builder.session.error = json.dumps({
            "stage": "compiling",
            "reason_code": "sidecar_compilation_failed",
            "message": "UPBGE sidecar exited with code 1",
        })

        resp = client.get(
            f"/api/session/{session_id}/events",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        terminal = json.loads(data_lines[-1].replace("data: ", ""))

        assert terminal["stage"] == "done"
        assert terminal["state"] == "error"
        assert terminal["failure_stage"] == "compiling"
        assert terminal["reason_code"] == "sidecar_compilation_failed"
        assert terminal["error"] == "UPBGE sidecar exited with code 1"

    def test_events_terminal_includes_launch_fallback(self, client):
        """SSE terminal event should include launch fallback info when launch failed (Req 1.8)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.progress_messages = [
            "sse:interpreting:0.1s",
            "sse:launching:8.0s",
        ]
        builder.session.state = PipelineState.READY
        builder.session.quality_label = "smoke_structural"
        builder.session.game_pid = None
        builder.session.output_path = str(builder.output_dir / "game.blend")
        builder.session.launch_fallback = {
            "launch_failed": True,
            "reason_code": "process_exited",
            "diagnostics": "blenderplayer exited with code 1",
            "fallback_instructions": "To launch manually: run blenderplayer game.blend",
        }

        resp = client.get(
            f"/api/session/{session_id}/events",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        terminal = json.loads(data_lines[-1].replace("data: ", ""))

        assert terminal["stage"] == "done"
        assert terminal["state"] == "ready"
        assert terminal["launch_failed"] is True
        assert "blenderplayer" in terminal["fallback_instructions"]
        assert "download_url" in terminal


class TestDownloadBlendEndpoint:
    """Tests for GET /api/session/{id}/download_blend."""

    def test_download_blend_404_for_unknown_session(self, client):
        """Should return 404 for non-existent session."""
        resp = client.get(
            "/api/session/nonexistent/download_blend",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 404

    def test_download_blend_404_when_no_artifact(self, client):
        """Should return 404 when session has no compiled artifact."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        resp = client.get(
            f"/api/session/{session_id}/download_blend",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 404

    def test_download_blend_serves_file(self, client, tmp_path):
        """Should serve the .blend file when available."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        blend_file = builder.output_dir / "game.blend"
        blend_file.write_bytes(b"FAKE_BLEND_CONTENT_FOR_TEST")
        builder.session.output_path = str(blend_file)

        resp = client.get(
            f"/api/session/{session_id}/download_blend",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        assert resp.content == b"FAKE_BLEND_CONTENT_FOR_TEST"
        assert "application/x-blender" in resp.headers["content-type"]


class TestMvpResultEndpoint:
    """Tests for GET /api/session/{id}/mvp_result."""

    def test_mvp_result_202_when_in_progress(self, client):
        """Should return 202 when pipeline is still running."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.state = PipelineState.GENERATING_CONCEPT

        resp = client.get(
            f"/api/session/{session_id}/mvp_result",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["complete"] is False

    def test_mvp_result_success(self, client, tmp_path):
        """Should return full result when pipeline completed successfully."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.state = PipelineState.READY
        builder.session.mode = SessionMode.MVP
        builder.session.quality_label = "smoke_structural"
        builder.session.game_pid = 42
        blend_file = builder.output_dir / "game.blend"
        blend_file.write_bytes(b"BLEND")
        builder.session.output_path = str(blend_file)

        resp = client.get(
            f"/api/session/{session_id}/mvp_result",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["complete"] is True
        assert data["success"] is True
        assert data["quality_label"] == "smoke_structural"
        assert data["game_running"] is True
        assert data["game_pid"] == 42
        assert "download_url" in data

    def test_mvp_result_failure(self, client):
        """Should return structured error info when pipeline failed (Req 9.4, 9.5)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.state = PipelineState.ERROR
        builder.session.mode = SessionMode.MVP
        # Store structured failure as JSON (as the background task does)
        import json as _json
        builder.session.error = _json.dumps({
            "stage": "validating",
            "reason_code": "parity_failed",
            "message": "Objects missing from scene",
        })

        resp = client.get(
            f"/api/session/{session_id}/mvp_result",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["complete"] is True
        assert data["success"] is False
        assert data["failure_stage"] == "validating"
        assert data["reason_code"] == "parity_failed"
        assert data["error"] == "Objects missing from scene"

    def test_mvp_result_failure_plain_string(self, client):
        """Should parse plain string error gracefully (Req 9.4)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.state = PipelineState.ERROR
        builder.session.mode = SessionMode.MVP
        builder.session.error = "parity_failed: Objects missing from scene"

        resp = client.get(
            f"/api/session/{session_id}/mvp_result",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["complete"] is True
        assert data["success"] is False
        assert data["reason_code"] == "parity_failed"
        assert data["error"] == "Objects missing from scene"

    def test_mvp_result_launch_failure_fallback(self, client, tmp_path):
        """Should include launch fallback info when launch failed (Req 1.4, 1.8)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        session_id = resp.json()["session_id"]

        builder = web.sessions[session_id]
        builder.session.state = PipelineState.READY
        builder.session.mode = SessionMode.MVP
        builder.session.quality_label = "smoke_structural"
        builder.session.game_pid = None  # game NOT running
        blend_file = builder.output_dir / "game.blend"
        blend_file.write_bytes(b"BLEND")
        builder.session.output_path = str(blend_file)
        builder.session.launch_fallback = {
            "launch_failed": True,
            "reason_code": "blenderplayer_not_found",
            "diagnostics": "blenderplayer not available",
            "fallback_instructions": "To launch the game manually on Windows:\n  1. Open Command Prompt\n  2. Run: blenderplayer game.blend",
        }

        resp = client.get(
            f"/api/session/{session_id}/mvp_result",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["complete"] is True
        assert data["success"] is True
        assert data["launch_failed"] is True
        assert "blenderplayer" in data["fallback_instructions"]
        assert "download_url" in data
        assert data["game_running"] is False


class TestSessionModeCreation:
    """Tests for mode parameter at session creation (Task 11.3, Requirements 10.2-10.4)."""

    def test_session_creation_defaults_to_mvp_mode(self, client):
        """When no mode is specified, session should default to MVP (Req 10.4)."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "mvp"
        # Verify session object also has mvp mode
        builder = web.sessions[data["session_id"]]
        assert builder.session.mode == SessionMode.MVP

    def test_session_creation_explicit_full_mode(self, client):
        """When mode='full' is specified, session should store full mode."""
        resp = client.post(
            "/api/session",
            json={"mode": "full"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "full"
        builder = web.sessions[data["session_id"]]
        assert builder.session.mode == SessionMode.FULL

    def test_session_creation_explicit_mvp_mode(self, client):
        """When mode='mvp' is specified explicitly, session should store mvp mode."""
        resp = client.post(
            "/api/session",
            json={"mode": "mvp"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "mvp"
        builder = web.sessions[data["session_id"]]
        assert builder.session.mode == SessionMode.MVP

    def test_session_creation_invalid_mode_rejected(self, client):
        """Unsupported mode value should return 400."""
        resp = client.post(
            "/api/session",
            json={"mode": "turbo"},
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 400
        assert "Unsupported mode" in resp.json()["error"]

    def test_describe_endpoint_still_works_for_full_mode_session(self, client):
        """Existing /describe endpoint must still accept full-mode sessions (not reject them)."""
        # Create a full-mode session
        resp = client.post(
            "/api/session",
            json={"mode": "full"},
            headers={"X-App-Version": "11"},
        )
        session_id = resp.json()["session_id"]
        assert resp.json()["mode"] == "full"

        # Verify the session is stored with full mode
        builder = web.sessions[session_id]
        assert builder.session.mode == SessionMode.FULL

        # The existing describe endpoint should not reject the session due to mode.
        # (It may fail in the stub due to missing scene_concept from the stub's
        # step_interpret, but that's a test stub limitation, not a mode rejection.)
        resp = client.post(
            f"/api/session/{session_id}/describe",
            json={"description": "A cozy reading nook with a bookshelf"},
            headers={"X-App-Version": "11"},
        )
        # Should NOT return a mode-related error; any failure here would be from
        # stub incompleteness (500) not from mode blocking (403/400 with mode error)
        assert resp.status_code != 403
        if resp.status_code == 400:
            # If 400, ensure it's not a mode-related rejection
            assert "mode" not in resp.json().get("error", "").lower()

    def test_session_creation_response_includes_mode(self, client):
        """Response from session creation should always include mode field."""
        resp = client.post("/api/session", headers={"X-App-Version": "11"})
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "session_id" in data
        assert "interface_version" in data
        assert "workflow_profile_id" in data


class TestV8V9V10Preservation:
    """Tests verifying V3-V10 versioned endpoints remain unchanged (Req 9.6, 10.2, 10.3)."""

    def test_v8_sessions_endpoint_still_works(self, client):
        """GET /api/v8/sessions should remain functional."""
        resp = client.get(
            "/api/v8/sessions",
            headers={"X-App-Version": "8"},
        )
        # Should return a list (possibly empty), not an error
        assert resp.status_code == 200

    def test_v9_sessions_endpoint_still_works(self, client):
        """GET /api/v9/sessions should remain functional."""
        resp = client.get(
            "/api/v9/sessions",
            headers={"X-App-Version": "9"},
        )
        assert resp.status_code == 200

    def test_v10_sessions_endpoint_still_works(self, client):
        """GET /api/v10/sessions should remain functional."""
        resp = client.get(
            "/api/v10/sessions",
            headers={"X-App-Version": "10"},
        )
        assert resp.status_code == 200

    def test_v11_sessions_endpoint_still_works(self, client):
        """GET /api/v11/sessions should remain functional."""
        resp = client.get(
            "/api/v11/sessions",
            headers={"X-App-Version": "11"},
        )
        assert resp.status_code == 200
