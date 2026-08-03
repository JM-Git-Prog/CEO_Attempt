"""Integration tests for blockout and canon stage handlers.

Verifies that _handle_blockout and _handle_canon_honesty actually produce
PNG files in the artifacts directory, regardless of ComfyUI availability.
"""
from __future__ import annotations

import nest_asyncio
nest_asyncio.apply()

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.unified_pipeline.orchestrator import StageExecutionContext
from src.unified_pipeline.stage_handlers import _handle_blockout, _handle_canon_honesty

# Patch target: the handlers do `from src.photo_pipeline.comfyui_client import ComfyUIClient`
# inside the function body, so we patch the class at its source module.
COMFYUI_CLIENT_PATCH = "src.photo_pipeline.comfyui_client.ComfyUIClient"


def _make_ctx(tmp_path: Path, session_id: str = "test-session", stage: str = "blockout") -> StageExecutionContext:
    """Create a minimal StageExecutionContext for testing."""
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return StageExecutionContext(
        session_id=session_id,
        session_dir=session_dir,
        stage=stage,
        object_id="obj-001",
        plan_revision=1,
        approval_revision=0,
        attempt=1,
        values={
            "brief": {
                "room_purpose": "kitchen",
                "era": {"period": "modern"},
                "atmosphere": {"mood": "warm morning"},
                "palette": {"primary": "warm oak tones"},
                "object_manifest": [
                    {"name": "round_table", "role": "furniture"},
                    {"name": "chair", "role": "furniture"},
                    {"name": "coffee_maker", "role": "appliance"},
                ],
            },
            "plan": {
                "camera": {"angle": "eye-level"},
            },
        },
    )


@pytest.mark.layer("scene")
class TestBlockoutHandler:
    """Tests for _handle_blockout generating a real artifact file."""

    def test_blockout_produces_png_degraded(self, tmp_path):
        """When ComfyUI is unavailable, handler produces a placeholder PNG."""
        ctx = _make_ctx(tmp_path)

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=False)

            result = asyncio.run(_handle_blockout(ctx))

        # Verify result status
        assert result.output["status"] == "blockout_rendered"
        assert result.output.get("degraded") is True

        # Verify file exists
        image_path = Path(result.output["image_path"])
        assert image_path.exists(), f"blockout.png not created at {image_path}"
        assert image_path.stat().st_size > 0, "blockout.png is empty"
        assert image_path.name == "blockout.png"

    def test_blockout_produces_png_with_comfyui(self, tmp_path):
        """When ComfyUI is available, handler submits workflow and saves image."""
        ctx = _make_ctx(tmp_path)
        artifacts_dir = ctx.session_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

        async def mock_get_output(prompt_id, output_dir, filename):
            out = output_dir / filename
            out.write_bytes(fake_png)
            return out

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=True)
            instance.submit_workflow = AsyncMock(return_value="prompt-123")
            instance.wait_for_completion = AsyncMock(return_value={"outputs": {}})
            instance.get_output_image = AsyncMock(side_effect=mock_get_output)

            result = asyncio.run(_handle_blockout(ctx))

        assert result.output["status"] == "blockout_rendered"
        assert "degraded" not in result.output

        image_path = Path(result.output["image_path"])
        assert image_path.exists()
        assert image_path.read_bytes() == fake_png

    def test_blockout_has_prompt_in_output(self, tmp_path):
        """Handler output includes the prompt used for generation."""
        ctx = _make_ctx(tmp_path)

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=False)

            result = asyncio.run(_handle_blockout(ctx))

        assert "prompt" in result.output
        assert "kitchen" in result.output["prompt"]


@pytest.mark.layer("scene")
class TestCanonHonestyHandler:
    """Tests for _handle_canon_honesty generating a real artifact file."""

    def test_canon_produces_png_degraded(self, tmp_path):
        """When ComfyUI is unavailable, handler produces a placeholder PNG."""
        ctx = _make_ctx(tmp_path, stage="canon_honesty")

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=False)

            result = asyncio.run(_handle_canon_honesty(ctx))

        assert result.output["status"] == "canon_rendered"
        assert result.output.get("degraded") is True

        image_path = Path(result.output["image_path"])
        assert image_path.exists(), f"canon.png not created at {image_path}"
        assert image_path.stat().st_size > 0, "canon.png is empty"
        assert image_path.name == "canon.png"

    def test_canon_produces_png_with_comfyui(self, tmp_path):
        """When ComfyUI is available, handler submits workflow and saves image."""
        ctx = _make_ctx(tmp_path, stage="canon_honesty")
        artifacts_dir = ctx.session_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

        async def mock_get_output(prompt_id, output_dir, filename):
            out = output_dir / filename
            out.write_bytes(fake_png)
            return out

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=True)
            instance.submit_workflow = AsyncMock(return_value="prompt-456")
            instance.wait_for_completion = AsyncMock(return_value={"outputs": {}})
            instance.get_output_image = AsyncMock(side_effect=mock_get_output)

            result = asyncio.run(_handle_canon_honesty(ctx))

        assert result.output["status"] == "canon_rendered"
        assert "degraded" not in result.output

        image_path = Path(result.output["image_path"])
        assert image_path.exists()
        assert image_path.read_bytes() == fake_png

    def test_canon_uses_higher_steps(self, tmp_path):
        """Canon handler uses 30 steps (vs blockout's 20)."""
        ctx = _make_ctx(tmp_path, stage="canon_honesty")
        artifacts_dir = ctx.session_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

        async def mock_get_output(prompt_id, output_dir, filename):
            out = output_dir / filename
            out.write_bytes(fake_png)
            return out

        submitted_workflow = {}

        async def capture_workflow(workflow, client_id, timeout_s=None):
            nonlocal submitted_workflow
            submitted_workflow = workflow
            return "prompt-789"

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=True)
            instance.submit_workflow = AsyncMock(side_effect=capture_workflow)
            instance.wait_for_completion = AsyncMock(return_value={"outputs": {}})
            instance.get_output_image = AsyncMock(side_effect=mock_get_output)

            result = asyncio.run(_handle_canon_honesty(ctx))

        # Verify the KSampler node has 30 steps
        ksampler = submitted_workflow.get("4", {})
        assert ksampler["inputs"]["steps"] == 30

    def test_canon_prompt_is_photorealistic(self, tmp_path):
        """Canon prompt includes photorealistic quality keywords."""
        ctx = _make_ctx(tmp_path, stage="canon_honesty")

        with patch(COMFYUI_CLIENT_PATCH) as MockClient:
            instance = MockClient.return_value
            instance.health_check = AsyncMock(return_value=False)

            result = asyncio.run(_handle_canon_honesty(ctx))

        prompt = result.output["prompt"]
        assert "Photorealistic" in prompt or "photorealistic" in prompt.lower()
        assert "kitchen" in prompt
