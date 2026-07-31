"""Targeted route tests for Task 10.3's additive V16 interface."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.web import app as web
from src.web import unified_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    web.sessions.clear()
    unified_routes.clear_unified_web_state()
    monkeypatch.setattr(web, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        web,
        "append_event",
        lambda root, payload: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "app_version": str(payload.get("app_version", 16)),
        },
    )
    with TestClient(web.app) as test_client:
        yield test_client
    unified_routes.clear_unified_web_state()
    web.sessions.clear()


def _create_v16_session(root: Path, session_id: str, state: str = "running") -> Path:
    session_dir = root / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps({"session_id": session_id, "interface_version": 16, "state": state}),
        encoding="utf-8",
    )
    return session_dir


class TestV16Page:
    def test_v16_is_default_and_explicit(self, client):
        implicit = client.get("/")
        explicit = client.get("/?v=16")
        assert implicit.status_code == explicit.status_code == 200
        assert "V16 Unified World Pipeline" in implicit.text
        assert "/static/unified_v16.js?v=16" in implicit.text

    def test_released_pages_remain_accessible(self, client):
        assert "V14" in client.get("/?v=14").text
        assert "v15_Fable" in client.get("/?v=15").text
        assert "v15_Fable" in client.get("/?v=15_Fable").text
        assert client.get("/?v=3").status_code == 200

    def test_v16_has_retained_version_links(self, client):
        page = client.get("/?v=16").text
        assert 'href="/?v=14"' in page
        assert 'href="/?v=15_Fable"' in page
        assert 'aria-current="page" href="/?v=16"' in page


class TestUnifiedConversationRoutes:
    def test_start_creates_v16_lifecycle_metadata(self, client, tmp_path):
        with patch.object(
            unified_routes.ConversationEngine,
            "generate_opening",
            new=AsyncMock(return_value="What kind of place shall we build?"),
        ):
            response = client.post("/api/session/unified/start", json={})
        assert response.status_code == 200
        payload = response.json()
        assert payload["interface_version"] == 16
        assert payload["opening_message"].startswith("What kind")
        session_dir = tmp_path / payload["session_id"]
        meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
        persisted = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        assert meta["interface_version"] == persisted["interface_version"] == 16
        assert meta["queue_policy"] == "shared_fifo_compilation"
        assert meta["lifecycle"] == "session_manager_ttl"

    def test_message_continues_the_same_conversation(self, client):
        with patch.object(
            unified_routes.ConversationEngine,
            "generate_opening",
            new=AsyncMock(return_value="Opening"),
        ):
            session_id = client.post("/api/session/unified/start", json={}).json()["session_id"]
        with patch.object(
            unified_routes.ConversationEngine,
            "interpret_response",
            new=AsyncMock(return_value="Warm oak and rainy-window light will lead the design."),
        ):
            response = client.post(
                f"/api/session/{session_id}/message",
                json={"message": "Make it a warm kitchenette."},
            )
        assert response.status_code == 200
        assert response.json()["message"].startswith("Warm oak")
        assert response.json()["interface_version"] == 16

    def test_empty_message_is_rejected(self, client):
        with patch.object(
            unified_routes.ConversationEngine,
            "generate_opening",
            new=AsyncMock(return_value="Opening"),
        ):
            session_id = client.post("/api/session/unified/start", json={}).json()["session_id"]
        response = client.post(f"/api/session/{session_id}/message", json={"message": " "})
        assert response.status_code == 400


class TestUnifiedArtifactsAndEvents:
    def test_blockout_route_serves_only_v16_session_artifact(self, client, tmp_path):
        session_dir = _create_v16_session(tmp_path, "blockout-session")
        content = b"\x89PNG\r\n\x1a\nroute-test"
        (session_dir / "blockout_r1.png").write_bytes(content)
        response = client.get("/api/session/blockout-session/blockout")
        assert response.status_code == 200
        assert response.content == content
        assert "no-store" in response.headers["cache-control"]

    def test_mesh_route_serves_unified_mesh_without_changing_legacy_path(self, client, tmp_path):
        session_dir = _create_v16_session(tmp_path, "mesh-session")
        (session_dir / "meshes").mkdir()
        content = b"glTF\x02\x00\x00\x00"
        (session_dir / "meshes" / "table.glb").write_bytes(content)
        response = client.get("/api/session/mesh-session/mesh/table")
        assert response.status_code == 200
        assert response.content == content
        assert response.headers["content-type"] == "model/gltf-binary"

    def test_dream_and_canon_routes_return_404_until_artifacts_exist(self, client, tmp_path):
        _create_v16_session(tmp_path, "artifact-session")
        assert client.get("/api/session/artifact-session/dream_preview").status_code == 404
        assert client.get("/api/session/artifact-session/canon").status_code == 404

    def test_sse_replays_progress_and_terminates(self, client, tmp_path):
        session_dir = _create_v16_session(tmp_path, "event-session", state="completed")
        progress_dir = session_dir / "orchestrator"
        progress_dir.mkdir()
        event = {
            "sequence": 1,
            "session_id": "event-session",
            "current_stage": "blockout",
            "object_id": None,
            "objects_complete": 1,
            "objects_total": 1,
            "elapsed_seconds": 2.0,
            "eta_seconds": 0.0,
            "state": "completed",
            "plan_revision": 1,
            "canonical_hash": "",
            "finality": "provisional",
            "timestamp": 1.0,
            "message": "",
        }
        (progress_dir / "progress.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        response = client.get("/api/session/event-session/events")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "event: pipeline.progress" in response.text
        assert "event: pipeline.terminal" in response.text

    def test_path_traversal_identifiers_are_rejected(self, client):
        response = client.get("/api/session/%2E%2E/blockout")
        assert response.status_code in {400, 404}


class _Decision:
    def to_dict(self):
        return {"stage": "blockout_approval", "approved": True, "plan_revision": 2}


class _FakeOrchestrator:
    session_id = "approval-session"
    current_plan_revision = 2

    @contextmanager
    def approval_writer(self, writer_id):
        yield "token"

    def record_approval(self, **kwargs):
        assert kwargs["stage"] == "blockout_approval"
        assert kwargs["plan_revision"] == 2
        return _Decision()

    async def run(self):
        return None


class TestUnifiedApprovals:
    def test_approval_is_written_through_attached_orchestrator(self, client, tmp_path):
        _create_v16_session(tmp_path, "approval-session")
        unified_routes.register_unified_orchestrator(_FakeOrchestrator())
        response = client.post(
            "/api/session/approval-session/approve/blockout",
            json={"approved": True, "plan_revision": 2},
        )
        assert response.status_code == 200
        assert response.json()["decision"]["approved"] is True

    def test_approval_fails_closed_without_orchestrator(self, client, tmp_path):
        _create_v16_session(tmp_path, "no-orchestrator")
        response = client.post("/api/session/no-orchestrator/approve/canon", json={})
        assert response.status_code == 409

    def test_material_websocket_route_is_registered(self):
        paths = {route.path for route in web.app.routes}
        assert "/api/session/{session_id}/materials" in paths
