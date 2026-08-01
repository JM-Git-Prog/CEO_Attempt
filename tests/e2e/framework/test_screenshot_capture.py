"""Unit tests for the ScreenshotCapture module.

Tests filename generation/parsing (round-trip), CameraPose construction,
ScreenshotCapture initialization, and capture_stage flow with mocked
Playwright pages.

Requirements: 2.1–2.5, 1.1
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.deterministic_render import DeterministicRenderError
from tests.e2e.framework.screenshot_capture import (
    CameraPose,
    CaptureResult,
    FilenameParseError,
    ParsedFilename,
    ScreenshotCapture,
    ScreenshotCaptureError,
    generate_filename,
    parse_filename,
)


# ---------------------------------------------------------------------------
# Tests for generate_filename
# ---------------------------------------------------------------------------


class TestGenerateFilename:
    """Tests for the generate_filename helper."""

    def test_basic_generation(self):
        ts = datetime(2026, 7, 30, 14, 22, 0, tzinfo=timezone.utc)
        result = generate_filename("canon", "v16-model-a1b2c3", ts)
        assert result == "canon__v16-model-a1b2c3__20260730T142200Z.png"

    def test_stage_with_underscores(self):
        ts = datetime(2026, 7, 30, 14, 22, 0, tzinfo=timezone.utc)
        result = generate_filename("dream_preview", "v16-model-a1b2c3", ts)
        assert result == "dream_preview__v16-model-a1b2c3__20260730T142200Z.png"

    def test_defaults_to_utc_now_when_no_timestamp(self):
        result = generate_filename("world", "v16-model-x")
        # Should have .png extension and the expected prefix
        assert result.startswith("world__v16-model-x__")
        assert result.endswith(".png")

    def test_invalid_stage_name_empty(self):
        with pytest.raises(ValueError, match="stage_name"):
            generate_filename("", "v16-model-x")

    def test_invalid_stage_name_uppercase(self):
        with pytest.raises(ValueError, match="stage_name"):
            generate_filename("Canon", "v16-model-x")

    def test_invalid_stage_name_starts_with_digit(self):
        with pytest.raises(ValueError, match="stage_name"):
            generate_filename("3d_scene", "v16-model-x")

    def test_invalid_model_version_empty(self):
        with pytest.raises(ValueError, match="model_version"):
            generate_filename("canon", "")

    def test_invalid_model_version_special_chars(self):
        with pytest.raises(ValueError, match="model_version"):
            generate_filename("canon", "v16 model (bad)")

    def test_model_version_with_double_underscore_rejected(self):
        with pytest.raises(ValueError, match="must not contain"):
            generate_filename("canon", "v16__bad")

    def test_model_version_with_dots_and_hyphens(self):
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = generate_filename("blockout", "v16.2-rc1", ts)
        assert result == "blockout__v16.2-rc1__20260101T000000Z.png"


# ---------------------------------------------------------------------------
# Tests for parse_filename
# ---------------------------------------------------------------------------


class TestParseFilename:
    """Tests for the parse_filename helper."""

    def test_basic_parse(self):
        result = parse_filename("canon__v16-model-a1b2c3__20260730T142200Z.png")
        assert result.stage_name == "canon"
        assert result.model_version == "v16-model-a1b2c3"
        assert result.timestamp == datetime(2026, 7, 30, 14, 22, 0, tzinfo=timezone.utc)

    def test_parse_stage_with_underscores(self):
        result = parse_filename("dream_preview__v16-model-a1b2c3__20260730T142200Z.png")
        assert result.stage_name == "dream_preview"

    def test_parse_with_directory_prefix_forward_slash(self):
        result = parse_filename("some/dir/canon__v16-x__20260101T000000Z.png")
        assert result.stage_name == "canon"
        assert result.model_version == "v16-x"

    def test_parse_with_directory_prefix_backslash(self):
        result = parse_filename("some\\dir\\canon__v16-x__20260101T000000Z.png")
        assert result.stage_name == "canon"

    def test_invalid_filename_raises_error(self):
        with pytest.raises(FilenameParseError):
            parse_filename("not_a_valid_filename.png")

    def test_invalid_timestamp_raises_error(self):
        with pytest.raises(FilenameParseError):
            parse_filename("canon__v16-x__99999999T999999Z.png")

    def test_missing_extension_raises_error(self):
        with pytest.raises(FilenameParseError):
            parse_filename("canon__v16-x__20260101T000000Z")


# ---------------------------------------------------------------------------
# Tests for filename round-trip (Property 2)
# ---------------------------------------------------------------------------


class TestFilenameRoundTrip:
    """Validates Property 2: Screenshot Filename Encoding Completeness.

    For any combination of stage name, pipeline model version, and capture
    timestamp, the filename SHALL encode all three such that each can be
    unambiguously parsed back.
    """

    def test_roundtrip_canon(self):
        ts = datetime(2026, 7, 30, 14, 22, 0, tzinfo=timezone.utc)
        filename = generate_filename("canon", "v16-model-a1b2c3", ts)
        parsed = parse_filename(filename)
        assert parsed.stage_name == "canon"
        assert parsed.model_version == "v16-model-a1b2c3"
        assert parsed.timestamp == ts

    def test_roundtrip_dream_preview(self):
        ts = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        filename = generate_filename("dream_preview", "v16.2-rc1", ts)
        parsed = parse_filename(filename)
        assert parsed.stage_name == "dream_preview"
        assert parsed.model_version == "v16.2-rc1"
        assert parsed.timestamp == ts

    def test_roundtrip_world(self):
        ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        filename = generate_filename("world", "model-0.1.0", ts)
        parsed = parse_filename(filename)
        assert parsed.stage_name == "world"
        assert parsed.model_version == "model-0.1.0"
        assert parsed.timestamp == ts

    def test_roundtrip_blockout(self):
        ts = datetime(2026, 6, 15, 8, 30, 45, tzinfo=timezone.utc)
        filename = generate_filename("blockout", "v16-abc123", ts)
        parsed = parse_filename(filename)
        assert parsed.stage_name == "blockout"
        assert parsed.model_version == "v16-abc123"
        assert parsed.timestamp == ts


# ---------------------------------------------------------------------------
# Tests for CameraPose
# ---------------------------------------------------------------------------


class TestCameraPose:
    """Tests for CameraPose dataclass."""

    def test_from_dict(self):
        data = {
            "position": [0, 1.6, 3.0],
            "target": [0, 1.0, 0],
            "up": [0, 1, 0],
            "vfov": 60,
        }
        pose = CameraPose.from_dict(data)
        assert pose.position == [0, 1.6, 3.0]
        assert pose.target == [0, 1.0, 0]
        assert pose.up == [0, 1, 0]
        assert pose.vfov == 60.0

    def test_from_dict_missing_key_raises(self):
        data = {"position": [0, 0, 0], "target": [0, 0, 0]}
        with pytest.raises(ValueError, match="missing required keys"):
            CameraPose.from_dict(data)

    def test_to_dict_roundtrip(self):
        original = {"position": [1, 2, 3], "target": [4, 5, 6], "up": [0, 1, 0], "vfov": 75}
        pose = CameraPose.from_dict(original)
        result = pose.to_dict()
        assert result["position"] == [1, 2, 3]
        assert result["target"] == [4, 5, 6]
        assert result["up"] == [0, 1, 0]
        assert result["vfov"] == 75.0


# ---------------------------------------------------------------------------
# Tests for ScreenshotCapture initialization
# ---------------------------------------------------------------------------


class TestScreenshotCaptureInit:
    """Tests for ScreenshotCapture constructor."""

    def test_valid_initialization(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        capture = ScreenshotCapture(artifact_store=store, model_version="v16-model-x")
        assert capture.model_version == "v16-model-x"

    def test_invalid_model_version_raises(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ValueError, match="model_version"):
            ScreenshotCapture(artifact_store=store, model_version="")

    def test_model_version_with_double_underscore_raises(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ValueError, match="must not contain"):
            ScreenshotCapture(artifact_store=store, model_version="bad__version")


# ---------------------------------------------------------------------------
# Tests for ScreenshotCapture.capture_stage (async)
# ---------------------------------------------------------------------------


class TestScreenshotCaptureStage:
    """Tests for ScreenshotCapture.capture_stage() method."""

    @pytest.fixture
    def artifact_store(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("test-run-001")
        return store

    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page that satisfies the capture flow."""
        page = AsyncMock()

        # Mock evaluate calls in sequence
        async def eval_side_effect(script, *args, **kwargs):
            if "typeof window.__qa !== 'undefined'" in script and "getRendererInfo" not in script:
                return True
            if "typeof window.__qa.getRendererInfo" in script:
                return True
            if "window.__qa.getRendererInfo()" in script:
                return {
                    "antialias": False,
                    "preserveDrawingBuffer": True,
                    "seed": 42,
                }
            if "setCameraPose" in script and "typeof" in script:
                return True
            if "window.__qa.setCameraPose" in script:
                return None
            if "requestAnimationFrame" in script:
                return None
            return None

        page.evaluate = AsyncMock(side_effect=eval_side_effect)
        page.set_viewport_size = AsyncMock()

        # Mock screenshot to return fake PNG bytes
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        page.screenshot = AsyncMock(return_value=fake_png)

        return page

    @pytest.mark.asyncio
    async def test_capture_returns_result(self, artifact_store, mock_page):
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        camera_pose = {
            "position": [0, 1.6, 3.0],
            "target": [0, 1.0, 0],
            "up": [0, 1, 0],
            "vfov": 60,
        }
        result = await capture.capture_stage(mock_page, "canon", camera_pose)

        assert isinstance(result, CaptureResult)
        assert result.stage_name == "canon"
        assert result.model_version == "v16-test"
        assert result.filename.endswith(".png")
        assert "canon" in result.filename
        assert "v16-test" in result.filename

    @pytest.mark.asyncio
    async def test_capture_stores_artifact(self, artifact_store, mock_page, tmp_path):
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        camera_pose = {
            "position": [0, 1.6, 3.0],
            "target": [0, 1.0, 0],
            "up": [0, 1, 0],
            "vfov": 60,
        }
        result = await capture.capture_stage(mock_page, "world", camera_pose)

        # Verify the file was stored
        from pathlib import Path

        artifact_path = Path(result.artifact_path)
        assert artifact_path.exists()
        assert artifact_path.read_bytes() == b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    @pytest.mark.asyncio
    async def test_capture_verifies_determinism(self, artifact_store):
        """Verify that capture_stage calls verify_determinism."""
        page = AsyncMock()

        # Make window.__qa unavailable — should trigger DeterministicRenderError
        async def eval_side_effect(script, *args, **kwargs):
            if "typeof window.__qa !== 'undefined'" in script:
                return False
            return None

        page.evaluate = AsyncMock(side_effect=eval_side_effect)

        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        camera_pose = {"position": [0, 0, 0], "target": [0, 0, -1], "up": [0, 1, 0], "vfov": 60}

        with pytest.raises(DeterministicRenderError, match="window.__qa is not available"):
            await capture.capture_stage(page, "canon", camera_pose)

    @pytest.mark.asyncio
    async def test_capture_sets_viewport_size(self, artifact_store, mock_page):
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        camera_pose = {"position": [0, 0, 0], "target": [0, 0, -1], "up": [0, 1, 0], "vfov": 60}
        await capture.capture_stage(mock_page, "blockout", camera_pose)

        mock_page.set_viewport_size.assert_called_once_with(
            {"width": 1920, "height": 1080}
        )

    @pytest.mark.asyncio
    async def test_capture_with_camera_pose_object(self, artifact_store, mock_page):
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        pose = CameraPose(position=[0, 1, 2], target=[0, 0, 0], up=[0, 1, 0], vfov=90)
        result = await capture.capture_stage(mock_page, "dream_preview", pose)

        assert result.camera_pose == pose

    @pytest.mark.asyncio
    async def test_capture_invalid_camera_pose_raises(self, artifact_store, mock_page):
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-test",
        )
        # Missing 'vfov' key
        bad_pose = {"position": [0, 0, 0], "target": [0, 0, -1], "up": [0, 1, 0]}

        with pytest.raises(ScreenshotCaptureError, match="Invalid camera_pose"):
            await capture.capture_stage(mock_page, "canon", bad_pose)

    @pytest.mark.asyncio
    async def test_filename_is_parseable(self, artifact_store, mock_page):
        """Captured filename must be round-trippable (Property 2).

        Note: timestamp encoding has second-level precision (no microseconds),
        so the round-trip comparison truncates to seconds.
        """
        capture = ScreenshotCapture(
            artifact_store=artifact_store,
            model_version="v16-model-abc",
        )
        camera_pose = {"position": [0, 0, 0], "target": [0, 0, -1], "up": [0, 1, 0], "vfov": 60}
        result = await capture.capture_stage(mock_page, "canon", camera_pose)

        # Parse back and verify components match
        parsed = parse_filename(result.filename)
        assert parsed.stage_name == "canon"
        assert parsed.model_version == "v16-model-abc"
        # Timestamp round-trips at second precision (microseconds not encoded)
        assert parsed.timestamp == result.timestamp.replace(microsecond=0)
