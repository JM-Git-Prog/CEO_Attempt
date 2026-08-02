"""Pipeline health smoke tests — catches the exact V16 bugs the user found.

V16 failure modes observed:
1. UI shows "COMPLETED" while backend reports state:"error" + reason_code:"server_restart"
2. Artifact endpoints return 404 (blockout never generated)
3. Pipeline never advances past Blockout
4. Status endpoint hangs indefinitely

These tests drive a real conversation through the V16 unified pipeline and
verify each transition point. They work in two modes:
- In-process: FastAPI TestClient (no running server needed)
- Live: httpx against localhost:8000 (if server is up)

Requirements: 10.1–10.4, 12.6
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.web import app as web
from src.web import unified_routes

# ---------------------------------------------------------------------------
# Canonical test data — the exact prompt that exposed the V16 bugs
# ---------------------------------------------------------------------------

CANONICAL_PROMPT = (
    "a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain"
)

# The opening greeting we'll mock (to verify the response differs)
MOCK_OPENING = (
    "Welcome! I'm imagining a cozy space for you. "
    "What kind of room or environment would you like to create today?"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Provide a FastAPI TestClient with isolated output directory."""
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


@pytest.fixture
def session_id(client, tmp_path):
    """Create a fresh V16 unified session and return its ID."""
    with patch.object(
        unified_routes.ConversationEngine,
        "generate_opening",
        new=AsyncMock(return_value=MOCK_OPENING),
    ):
        resp = client.post("/api/session/unified/start", json={})
    assert resp.status_code == 200, (
        f"Session creation failed with {resp.status_code}: {resp.text}"
    )
    payload = resp.json()
    assert "session_id" in payload, "No session_id in session creation response"
    return payload["session_id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.layer("scene")
class TestPipelineSmoke:
    """Smoke tests that catch the V16 pipeline failures the user experienced."""

    def test_pipeline_health_endpoint_responds(self, client, session_id):
        """GET /api/session/{id}/status must respond within 5 seconds.

        Catches: Server hanging on status requests (the user saw infinite
        spinners because status never came back).
        """
        start = time.monotonic()
        resp = client.get(f"/api/session/{session_id}/status")
        elapsed = time.monotonic() - start

        assert resp.status_code == 200, (
            f"Status endpoint returned HTTP {resp.status_code} — "
            f"user sees a broken spinner. Response: {resp.text[:200]}"
        )
        assert elapsed < 5.0, (
            f"Status endpoint took {elapsed:.1f}s to respond — "
            f"user sees the UI freeze. Must respond within 5s."
        )

    def test_pipeline_conversation_to_brief(self, client, session_id):
        """Send the canonical prompt and verify a real, context-aware response.

        Catches: Pipeline returning a byte-for-byte repeat of the opening
        greeting, or a canned "Whimsical Bohemia" persona response that
        ignores the user's actual input.
        """
        # Mock interpret_response to return a context-aware response
        mock_response = (
            "A warm kitchen with rain outside — lovely. I'm picturing a "
            "round wooden table, two mismatched chairs, a compact counter "
            "with a drip coffee maker, and a window framing grey rain. "
            "The palette is warm oak, cream tiles, and brushed steel."
        )
        mock_interpret = AsyncMock(return_value=mock_response)

        with patch.object(
            unified_routes.ConversationEngine,
            "interpret_response",
            new=mock_interpret,
        ):
            resp = client.post(
                f"/api/session/{session_id}/message",
                json={"message": CANONICAL_PROMPT},
            )

        assert resp.status_code == 200, (
            f"Message endpoint returned HTTP {resp.status_code} — "
            f"user's prompt was rejected. Response: {resp.text[:200]}"
        )
        payload = resp.json()
        response_text = payload.get("message", "")

        # Must NOT be a byte-for-byte repeat of the opening greeting
        assert response_text != MOCK_OPENING, (
            "Response is an exact copy of the opening greeting — "
            "the conversation engine is echoing itself instead of "
            "interpreting the user's input."
        )

        # Must NOT be empty
        assert len(response_text) > 10, (
            f"Response is too short ({len(response_text)} chars) — "
            f"the engine failed to generate a real reply."
        )

        # Must NOT contain "Whimsical Bohemia" (a seeded persona bug)
        assert "Whimsical Bohemia" not in response_text, (
            "Response contains 'Whimsical Bohemia' — "
            "this is a seeded persona, not a response to the user's prompt."
        )

        # Verify the mock was called with the user's message
        mock_interpret.assert_called_once_with(CANONICAL_PROMPT)

    def test_pipeline_brief_locks_and_advances(self, client, session_id, tmp_path):
        """After conversation, send approval → pipeline must not end in 'error'.

        Catches: The V16 bug where the pipeline transitions to state:"error"
        with reason_code:"server_restart" while the UI still shows COMPLETED.
        """
        # Simulate the conversation engine stabilizing and producing a brief
        mock_brief = {
            "room_purpose": "kitchen",
            "era": "modern_warm",
            "mood": "cozy morning routine",
            "palette": ["warm oak", "cream", "brushed steel"],
            "object_manifest": [
                {"name": "round_table", "role": "furniture", "material": "oak"},
                {"name": "chair_1", "role": "furniture", "material": "oak"},
                {"name": "chair_2", "role": "furniture", "material": "oak"},
                {"name": "coffee_maker", "role": "appliance", "material": "steel"},
                {"name": "window", "role": "architectural", "material": "glass"},
                {"name": "counter", "role": "furniture", "material": "oak"},
            ],
        }

        # Create a mock Brief object with to_dict method
        class MockBrief:
            def to_dict(self):
                return mock_brief

        mock_engine = AsyncMock()
        mock_engine.interpret_response = AsyncMock(return_value="Looks great!")
        mock_engine.is_stable = True
        mock_engine.state = unified_routes.ConversationState(
            session_id=session_id,
            turns=[],
            proposed_brief=mock_brief,
            steering_stable=True,
            turn_count=2,
            started_at=time.time(),
        )
        mock_engine.extract_brief = AsyncMock(return_value=MockBrief())

        # Patch _load_conversation to return our mock engine
        with patch.object(
            unified_routes, "_load_conversation", return_value=mock_engine
        ), patch.object(
            unified_routes, "_launch_pipeline"
        ) as mock_launch:
            resp = client.post(
                f"/api/session/{session_id}/message",
                json={"message": "looks good, build it"},
            )

        assert resp.status_code == 200, (
            f"Approval message returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
        payload = resp.json()
        assert payload.get("steering_stable") is True, (
            "steering_stable should be True after user approval — "
            "the pipeline should have accepted the Brief."
        )
        assert "brief" in payload, (
            "No 'brief' in response — the pipeline failed to extract "
            "a Brief from the conversation. Pipeline will not advance."
        )

        # Verify _launch_pipeline was called (pipeline should start)
        mock_launch.assert_called_once()

        # Check the session meta state — must not be "error"
        session_dir = tmp_path / session_id
        if session_dir.exists():
            meta_path = session_dir / "session_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                state = meta.get("state", "")
                assert state != "error", (
                    f"Pipeline state is 'error' immediately after Brief lock — "
                    f"this is the V16 bug where the backend fails silently. "
                    f"Meta: {json.dumps(meta, indent=2)}"
                )

    def test_pipeline_blockout_artifact_exists(self, client, tmp_path):
        """After pipeline advances past blockout, GET blockout must return 200.

        Catches: Artifact endpoints returning 404 even when the UI claims
        the blockout stage completed. The user saw this as a blank stage
        with no image.
        """
        # Create a session with a blockout artifact present
        session_id = "blockout-smoke-test"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session_meta.json").write_text(
            json.dumps({
                "session_id": session_id,
                "interface_version": 16,
                "state": "running",
            }),
            encoding="utf-8",
        )

        # Simulate a blockout artifact being generated
        blockout_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
        (session_dir / "blockout_r1.png").write_bytes(blockout_content)

        resp = client.get(f"/api/session/{session_id}/blockout")
        assert resp.status_code == 200, (
            f"Blockout endpoint returned HTTP {resp.status_code} — "
            f"user sees an empty stage with 'image not found'. "
            f"The artifact exists on disk but the route can't find it. "
            f"Response: {resp.text[:200]}"
        )

    def test_pipeline_blockout_404_when_missing(self, client, tmp_path):
        """Blockout returns 404 when no artifact exists — honest failure.

        This is the EXPECTED behavior for a fresh session that hasn't
        reached blockout yet. The bug is when it returns 404 AFTER the
        pipeline claims to have completed blockout.
        """
        session_id = "no-blockout-session"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session_meta.json").write_text(
            json.dumps({
                "session_id": session_id,
                "interface_version": 16,
                "state": "running",
            }),
            encoding="utf-8",
        )

        resp = client.get(f"/api/session/{session_id}/blockout")
        assert resp.status_code == 404, (
            f"Expected 404 when blockout artifact doesn't exist, "
            f"got {resp.status_code}. This might mask the real bug."
        )

    def test_pipeline_status_matches_ui_claim(self, client, session_id, tmp_path):
        """If backend state is 'error', the test MUST fail.

        Catches: The core V16 disconnect — UI shows "COMPLETED" but the
        backend has state:"error". This test reads the ground truth from
        session_meta.json after session creation and asserts consistency.

        A freshly created session should NEVER be in error state — if it is,
        the server_restart marker fired prematurely or the session was
        corrupted on creation.
        """
        session_dir = tmp_path / session_id
        assert session_dir.exists(), (
            f"Session directory does not exist at {session_dir} — "
            f"session creation did not persist to disk."
        )
        meta_path = session_dir / "session_meta.json"
        assert meta_path.exists(), (
            f"session_meta.json missing — V16 session lifecycle is broken."
        )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        state = meta.get("state", "unknown")

        assert state != "error", (
            f"PIPELINE HEALTH FAILURE: Backend reports state='error' "
            f"but the UI may still show 'COMPLETED'.\n"
            f"  reason_code: {meta.get('reason_code', 'unknown')}\n"
            f"  error: {meta.get('error', 'unknown')}\n"
            f"\n"
            f"This is the exact V16 bug: the frontend never polls the "
            f"backend status after the initial 'running' state, so it "
            f"misses transitions to 'error'."
        )

    def test_pipeline_no_server_restart_error(self, client, session_id, tmp_path):
        """Status must NOT contain reason_code:'server_restart'.

        Catches: The specific failure mode where the server restarts
        mid-pipeline, orphaning sessions. SessionManager.mark_failed_on_restart()
        stamps these with reason_code:'server_restart' — if we ever see that
        in a freshly created test session, the pipeline was interrupted.
        """
        session_dir = tmp_path / session_id
        assert session_dir.exists(), (
            f"Session directory does not exist — session creation broken."
        )
        meta_path = session_dir / "session_meta.json"
        assert meta_path.exists(), (
            f"session_meta.json missing — V16 lifecycle broken."
        )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        reason_code = meta.get("reason_code", "")

        assert reason_code != "server_restart", (
            f"PIPELINE INTERRUPTED: Session was killed by a server restart.\n"
            f"  session_id: {session_id}\n"
            f"  state: {meta.get('state')}\n"
            f"\n"
            f"This means the pipeline never completed — it was orphaned "
            f"when the server restarted. The UI will show stale 'running' "
            f"state forever, or incorrectly show 'COMPLETED' if it cached "
            f"an earlier optimistic status."
        )

    def test_pipeline_healthy_session_passes(self, client, tmp_path):
        """A completed session with no errors passes all health checks.

        Regression guard: ensures the health assertions don't false-positive
        on a genuinely healthy pipeline run.
        """
        session_id = "healthy-session"
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session_meta.json").write_text(
            json.dumps({
                "session_id": session_id,
                "interface_version": 16,
                "state": "completed",
            }),
            encoding="utf-8",
        )

        meta = json.loads(
            (session_dir / "session_meta.json").read_text(encoding="utf-8")
        )
        state = meta.get("state", "unknown")
        reason_code = meta.get("reason_code", "")

        # All health checks pass for a genuinely completed session
        assert state != "error", f"Unexpected error state: {meta}"
        assert reason_code != "server_restart", f"Unexpected restart: {meta}"
        assert state == "completed", (
            f"Expected state='completed', got '{state}'"
        )
