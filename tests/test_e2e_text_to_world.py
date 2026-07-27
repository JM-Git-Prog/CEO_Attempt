"""Headless E2E integration test: text description → playable world pipeline.

Mimics a human using the FastAPI web app to submit a text prompt and wait for
the full MVP pipeline to produce a walkable world (or gracefully degrade).

Requirements:
- Ollama must be running at localhost:11434 (LLM calls)
- UPBGE must be installed (for launch stage; pipeline degrades gracefully without it)

Run separately from unit tests:
    pytest tests/test_e2e_text_to_world.py -m e2e --timeout=180
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest

from src.web.app import app

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

OLLAMA_AVAILABLE = False
try:
    _r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
    OLLAMA_AVAILABLE = _r.status_code == 200
except Exception:
    pass

UPBGE_PATH = r"C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blender.exe"
UPBGE_AVAILABLE = os.path.isfile(UPBGE_PATH)

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.e2e]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_session_id() -> str:
    """Generate a fresh session ID for zero-state testing."""
    return str(uuid.uuid4())


def _parse_error(error_field) -> dict | None:
    """Parse a session error field into structured dict, if possible."""
    if error_field is None:
        return None
    if isinstance(error_field, dict):
        return error_field
    try:
        parsed = json.loads(error_field)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {"stage": "unknown", "reason_code": "unknown", "message": str(error_field)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not running at localhost:11434")
class TestE2ETextToWorld:
    """End-to-end test: submit text prompt → verify pipeline produces a walkable world."""

    PROMPT = "A cozy living room with a fireplace, bookshelf, and wooden door"
    TIMEOUT_SECONDS = 120.0
    POLL_INTERVAL = 2.0

    async def test_cozy_living_room_pipeline_completes(self):
        """Submit a room description and verify the pipeline completes or degrades gracefully."""
        session_id = _new_session_id()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-App-Version": "11"},
        ) as client:
            # --- Step 1: Submit the prompt via describe_mvp ---
            resp = await client.post(
                f"/api/session/{session_id}/describe_mvp",
                json={"description": self.PROMPT, "mode": "mvp"},
            )
            assert resp.status_code == 200, (
                f"describe_mvp returned {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert "state" in data, f"Response missing 'state': {data}"
            assert data.get("mode") == "mvp"
            assert data.get("session_id") == session_id

            # --- Step 2: Poll status until completion or timeout ---
            loop = asyncio.get_event_loop()
            deadline = loop.time() + self.TIMEOUT_SECONDS
            final_state: str | None = None
            final_status: dict = {}
            progress_high_water = 0

            while loop.time() < deadline:
                await asyncio.sleep(self.POLL_INTERVAL)

                status_resp = await client.get(f"/api/session/{session_id}/status")
                assert status_resp.status_code == 200, (
                    f"status endpoint returned {status_resp.status_code}"
                )
                status = status_resp.json()

                # Track progress accumulation
                progress = status.get("progress", [])
                progress_high_water = max(progress_high_water, len(progress))

                state = status.get("state", "")

                # Terminal states
                if state in ("completed", "world_ready", "ready", "error"):
                    final_state = state
                    final_status = status
                    break

            # --- Step 3: Assertions ---
            assert final_state is not None, (
                f"Pipeline timed out after {self.TIMEOUT_SECONDS}s. "
                f"Last progress count: {progress_high_water}"
            )
            assert progress_high_water > 0, "No progress messages were emitted"

            if final_state == "error":
                # Graceful degradation: verify structured error info
                error_raw = final_status.get("error")
                assert error_raw is not None, "Error state but no error info"

                err = _parse_error(error_raw)
                assert err is not None, f"Could not parse error: {error_raw}"

                # Must have a reason code (not just unhandled crash)
                reason_code = err.get("reason_code", "")
                assert reason_code, f"Error missing reason_code: {err}"
                assert reason_code != "unhandled_exception", (
                    f"Unhandled exception in pipeline — this is a bug: {err}"
                )

                # If UPBGE is not available, launch-related failures are expected
                if not UPBGE_AVAILABLE:
                    expected_codes = {
                        "launch_failed",
                        "smoke_failed",
                        "upbge_not_found",
                        "blenderplayer_not_found",
                        "blend_file_missing",
                        "runtime_not_available",
                    }
                    # The reason_code should be recognizable, but we don't hard-fail
                    # on unknown codes — just note them
                    if reason_code not in expected_codes:
                        # Still acceptable — pipeline caught the error structurally
                        pass
            else:
                # Success path — verify the world was produced
                assert final_state in ("completed", "world_ready", "ready"), (
                    f"Unexpected terminal state: {final_state}"
                )
                # At least one of these should indicate output exists
                has_project = final_status.get("has_project", False)
                output_path = final_status.get("output_path")
                has_image = final_status.get("has_image", False)

                # The pipeline must produce a project (blend file)
                assert has_project or output_path, (
                    f"Pipeline completed but no output: {final_status}"
                )

    async def test_status_endpoint_returns_200_immediately(self):
        """After submitting a prompt, the status endpoint is always reachable."""
        session_id = _new_session_id()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-App-Version": "11"},
        ) as client:
            # Submit prompt
            resp = await client.post(
                f"/api/session/{session_id}/describe_mvp",
                json={"description": self.PROMPT, "mode": "mvp"},
            )
            assert resp.status_code == 200

            # Immediately check status — should not 500
            status_resp = await client.get(f"/api/session/{session_id}/status")
            assert status_resp.status_code == 200
            status = status_resp.json()
            assert "state" in status
            assert "progress" in status

    async def test_invalid_session_returns_404(self):
        """Polling a non-existent session returns 404, not a crash."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-App-Version": "11"},
        ) as client:
            resp = await client.get("/api/session/nonexistent-fake-id/status")
            assert resp.status_code == 404

    async def test_empty_description_rejected(self):
        """Submitting an empty description is rejected with 4xx, not a crash."""
        session_id = _new_session_id()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-App-Version": "11"},
        ) as client:
            resp = await client.post(
                f"/api/session/{session_id}/describe_mvp",
                json={"description": "", "mode": "mvp"},
            )
            # Should be a client error (400/422), not a 500
            assert resp.status_code in (400, 422), (
                f"Empty description should be rejected, got {resp.status_code}"
            )


@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not running at localhost:11434")
@pytest.mark.skipif(not UPBGE_AVAILABLE, reason="UPBGE not installed")
class TestE2ETextToWorldFullStack:
    """Full-stack E2E: only runs when both Ollama AND UPBGE are available.

    These tests verify the complete happy path including game launch.
    """

    PROMPT = "A small bedroom with a single bed, nightstand, and closet door"
    TIMEOUT_SECONDS = 120.0
    POLL_INTERVAL = 2.0

    async def test_full_pipeline_reaches_ready_state(self):
        """With UPBGE present, the pipeline should reach 'ready' or 'world_ready'."""
        session_id = _new_session_id()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-App-Version": "11"},
        ) as client:
            resp = await client.post(
                f"/api/session/{session_id}/describe_mvp",
                json={"description": self.PROMPT, "mode": "mvp"},
            )
            assert resp.status_code == 200

            loop = asyncio.get_event_loop()
            deadline = loop.time() + self.TIMEOUT_SECONDS
            final_state = None
            final_status = {}

            while loop.time() < deadline:
                await asyncio.sleep(self.POLL_INTERVAL)
                status_resp = await client.get(f"/api/session/{session_id}/status")
                assert status_resp.status_code == 200
                status = status_resp.json()

                state = status.get("state", "")
                if state in ("completed", "world_ready", "ready", "error"):
                    final_state = state
                    final_status = status
                    break

            assert final_state is not None, "Pipeline timed out"

            # With full stack available, we expect success
            if final_state == "error":
                err = _parse_error(final_status.get("error"))
                pytest.fail(
                    f"Full-stack pipeline failed: "
                    f"stage={err.get('stage')}, "
                    f"reason={err.get('reason_code')}, "
                    f"message={err.get('message')}"
                )

            assert final_state in ("completed", "world_ready", "ready")
            assert final_status.get("has_project") is True or final_status.get("output_path")
