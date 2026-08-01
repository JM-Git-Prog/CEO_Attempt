"""Unit tests for the deterministic render configuration module.

Tests cover:
- DeterministicRenderConfig dataclass defaults and serialization
- Hardware ID detection stability and format
- verify_determinism error handling for various failure modes

Requirements: 1.1, 1.2, 1.3
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.e2e.framework.deterministic_render import (
    DeterministicRenderConfig,
    DeterministicRenderError,
    detect_hardware_id,
    verify_determinism,
    _slugify_gpu,
    _slugify_driver,
)


class TestDeterministicRenderConfig:
    """Tests for DeterministicRenderConfig dataclass."""

    def test_default_values(self):
        """Config defaults match design spec: antialias off, buffer preserved, seed 42."""
        cfg = DeterministicRenderConfig()
        assert cfg.antialias is False
        assert cfg.preserve_draw_buffer is True
        assert cfg.seed == 42
        assert cfg.viewport_width == 1920
        assert cfg.viewport_height == 1080
        assert cfg.output_color_space == "SRGBColorSpace"

    def test_frozen_dataclass(self):
        """Config is immutable once created."""
        cfg = DeterministicRenderConfig()
        with pytest.raises(AttributeError):
            cfg.antialias = True  # type: ignore[misc]

    def test_to_renderer_args(self):
        """to_renderer_args produces correct WebGLRenderer constructor dict."""
        cfg = DeterministicRenderConfig()
        args = cfg.to_renderer_args()
        assert args == {
            "antialias": False,
            "preserveDrawingBuffer": True,
        }

    def test_to_dict(self):
        """to_dict includes all config values for logging and comparison."""
        cfg = DeterministicRenderConfig()
        d = cfg.to_dict()
        assert d["antialias"] is False
        assert d["preserveDrawingBuffer"] is True
        assert d["seed"] == 42
        assert d["viewport_width"] == 1920
        assert d["viewport_height"] == 1080
        assert d["outputColorSpace"] == "SRGBColorSpace"

    def test_custom_values(self):
        """Config accepts custom viewport and seed values."""
        cfg = DeterministicRenderConfig(
            seed=99,
            viewport_width=1024,
            viewport_height=768,
        )
        assert cfg.seed == 99
        assert cfg.viewport_width == 1024
        assert cfg.viewport_height == 768
        # Other defaults unchanged
        assert cfg.antialias is False
        assert cfg.preserve_draw_buffer is True


class TestHardwareIdDetection:
    """Tests for hardware ID detection and slugification."""

    def test_hardware_id_is_nonempty_string(self):
        """detect_hardware_id always returns a non-empty string."""
        hw_id = detect_hardware_id()
        assert isinstance(hw_id, str)
        assert len(hw_id) > 0

    def test_hardware_id_is_deterministic(self):
        """Same hardware should produce the same ID across calls."""
        id1 = detect_hardware_id()
        id2 = detect_hardware_id()
        assert id1 == id2

    def test_hardware_id_filesystem_safe(self):
        """Hardware ID should be safe for use in directory paths."""
        hw_id = detect_hardware_id()
        # No spaces, special chars that would break paths
        unsafe_chars = set(' /\\:*?"<>|')
        for char in hw_id:
            assert char not in unsafe_chars, f"Unsafe char '{char}' in hardware ID"

    @patch(
        "tests.e2e.framework.deterministic_render._detect_gpu_model",
        return_value="",
    )
    @patch(
        "tests.e2e.framework.deterministic_render._detect_driver_version",
        return_value="",
    )
    def test_hardware_id_fallback(self, mock_driver, mock_gpu):
        """Returns 'unknown-hardware' when detection fails."""
        hw_id = detect_hardware_id()
        assert hw_id == "unknown-hardware"

    @patch(
        "tests.e2e.framework.deterministic_render._detect_gpu_model",
        return_value="NVIDIA GeForce RTX 4090",
    )
    @patch(
        "tests.e2e.framework.deterministic_render._detect_driver_version",
        return_value="560.35.03",
    )
    def test_hardware_id_with_known_gpu(self, mock_driver, mock_gpu):
        """Produces readable slug for known GPU models."""
        hw_id = detect_hardware_id()
        assert hw_id.startswith("rtx4090-driver")
        assert len(hw_id) > 10  # slug + hash suffix

    def test_slugify_gpu_nvidia(self):
        """NVIDIA GPU names are slugified correctly."""
        assert _slugify_gpu("NVIDIA GeForce RTX 4090") == "rtx4090"
        assert _slugify_gpu("NVIDIA GeForce GTX 1080 Ti") == "gtx1080ti"

    def test_slugify_gpu_amd(self):
        """AMD GPU names are slugified correctly."""
        assert _slugify_gpu("AMD Radeon RX 7900 XTX") == "rx7900xtx"

    def test_slugify_gpu_apple(self):
        """Apple GPU names are slugified correctly."""
        assert _slugify_gpu("Apple M2 Pro") == "m2pro"

    def test_slugify_gpu_truncation(self):
        """Long GPU names are truncated to 20 chars."""
        result = _slugify_gpu("NVIDIA GeForce RTX 4090 Super Ultra Mega")
        assert len(result) <= 20

    def test_slugify_driver(self):
        """Driver versions produce readable slugs."""
        assert _slugify_driver("560.35.03") == "driver5603503"
        assert _slugify_driver("32.0.15.6081") == "driver320156081"
        assert _slugify_driver("macOS-14.5") == "drivermacos145"

    def test_slugify_driver_empty(self):
        """Empty driver string produces 'driver' fallback."""
        assert _slugify_driver("") == "driver"


class TestVerifyDeterminism:
    """Tests for verify_determinism async helper."""

    def _run(self, coro):
        """Helper to run async tests."""
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_raises_when_qa_unavailable(self):
        """Raises DeterministicRenderError when window.__qa is missing."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=False)

        with pytest.raises(DeterministicRenderError, match="window.__qa is not available"):
            self._run(verify_determinism(page))

    def test_raises_when_method_missing(self):
        """Raises when getRendererInfo method doesn't exist."""
        page = AsyncMock()
        # First call: window.__qa exists
        # Second call: getRendererInfo doesn't exist
        page.evaluate = AsyncMock(side_effect=[True, False])

        with pytest.raises(DeterministicRenderError, match="getRendererInfo.*not available"):
            self._run(verify_determinism(page))

    def test_raises_on_invalid_return(self):
        """Raises when getRendererInfo returns non-dict."""
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=[True, True, None])

        with pytest.raises(DeterministicRenderError, match="returned invalid data"):
            self._run(verify_determinism(page))

    def test_raises_on_wrong_antialias(self):
        """Raises when antialias is true (non-deterministic)."""
        page = AsyncMock()
        renderer_info = {
            "antialias": True,
            "preserveDrawingBuffer": True,
            "seed": 42,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        with pytest.raises(DeterministicRenderError, match="antialias must be false"):
            self._run(verify_determinism(page))

    def test_raises_on_wrong_buffer(self):
        """Raises when preserveDrawingBuffer is false."""
        page = AsyncMock()
        renderer_info = {
            "antialias": False,
            "preserveDrawingBuffer": False,
            "seed": 42,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        with pytest.raises(DeterministicRenderError, match="preserveDrawingBuffer must be true"):
            self._run(verify_determinism(page))

    def test_raises_on_wrong_seed(self):
        """Raises when seed doesn't match expected value."""
        page = AsyncMock()
        renderer_info = {
            "antialias": False,
            "preserveDrawingBuffer": True,
            "seed": 99,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        with pytest.raises(DeterministicRenderError, match="seed must be 42"):
            self._run(verify_determinism(page))

    def test_reports_multiple_errors(self):
        """Reports all incorrect settings in a single error."""
        page = AsyncMock()
        renderer_info = {
            "antialias": True,
            "preserveDrawingBuffer": False,
            "seed": 99,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        with pytest.raises(DeterministicRenderError) as exc_info:
            self._run(verify_determinism(page))

        msg = str(exc_info.value)
        assert "antialias" in msg
        assert "preserveDrawingBuffer" in msg
        assert "seed" in msg

    def test_success_returns_renderer_info(self):
        """Returns renderer info dict on successful verification."""
        page = AsyncMock()
        renderer_info = {
            "antialias": False,
            "preserveDrawingBuffer": True,
            "seed": 42,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        result = self._run(verify_determinism(page))
        assert result == renderer_info

    def test_error_message_mentions_abort(self):
        """Error message explicitly says test should be aborted (Req 1.3)."""
        page = AsyncMock()
        renderer_info = {
            "antialias": True,
            "preserveDrawingBuffer": True,
            "seed": 42,
        }
        page.evaluate = AsyncMock(side_effect=[True, True, renderer_info])

        with pytest.raises(DeterministicRenderError, match="Aborting test"):
            self._run(verify_determinism(page))
