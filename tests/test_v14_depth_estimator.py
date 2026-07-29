"""Unit tests for DepthAnything3Estimator with validation and fallback logic.

Tests the validate_depth_map pixel ratio computation, fallback chain order
(DA3 → MoGe-2 → flat-floor), and .npy file save/load round-trip.

Requirements: 14.1, 14.3, 14.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIError
from src.photo_pipeline.models import DepthResult, PhotoPipelineConfig
from src.photo_pipeline.stages.depth_anything3 import (
    DepthAnything3Estimator,
    _FLAT_FLOOR_BOTTOM_DEPTH_M,
    _FLAT_FLOOR_TOP_DEPTH_M,
    _MAX_INDOOR_DEPTH_M,
    _VALID_PIXEL_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock ComfyUIClient."""
    client = MagicMock(spec=ComfyUIClient)
    client.submit_workflow = AsyncMock()
    client.wait_for_completion = AsyncMock()
    return client


@pytest.fixture
def estimator(mock_client: MagicMock, tmp_path: Path) -> DepthAnything3Estimator:
    """Create a DepthAnything3Estimator with mocked client."""
    return DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)


@pytest.fixture
def config() -> PhotoPipelineConfig:
    """Standard pipeline configuration."""
    return PhotoPipelineConfig()


@pytest.fixture
def source_image(tmp_path: Path) -> Path:
    """Create a minimal 100x100 PNG image for testing."""
    from PIL import Image

    img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    img_path = tmp_path / "source.png"
    img.save(img_path)
    return img_path


# ---------------------------------------------------------------------------
# validate_depth_map tests
# ---------------------------------------------------------------------------


class TestValidateDepthMap:
    """Tests for validate_depth_map pixel ratio computation."""

    def test_all_valid_depth_map(self, estimator: DepthAnything3Estimator) -> None:
        """All-valid depth map (positive, finite, <20m) → ratio = 1.0."""
        depth = np.full((100, 100), 3.0, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 1.0

    def test_all_invalid_zeros(self, estimator: DepthAnything3Estimator) -> None:
        """All-zero depth map → ratio = 0.0 (zeros are not positive)."""
        depth = np.zeros((100, 100), dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_mixed_50_percent_valid(self, estimator: DepthAnything3Estimator) -> None:
        """Mixed (50% valid) → ratio = 0.5."""
        depth = np.zeros((100, 100), dtype=np.float32)
        # Fill top half with valid values
        depth[:50, :] = 5.0
        ratio = estimator.validate_depth_map(depth)
        assert ratio == pytest.approx(0.5)

    def test_nan_values_invalid(self, estimator: DepthAnything3Estimator) -> None:
        """NaN values are counted as invalid."""
        depth = np.full((10, 10), np.nan, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_inf_values_invalid(self, estimator: DepthAnything3Estimator) -> None:
        """Inf values are counted as invalid."""
        depth = np.full((10, 10), np.inf, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_negative_values_invalid(self, estimator: DepthAnything3Estimator) -> None:
        """Negative values are counted as invalid."""
        depth = np.full((10, 10), -1.0, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_exactly_20m_invalid(self, estimator: DepthAnything3Estimator) -> None:
        """Exactly 20.0m is invalid (must be strictly less than 20m)."""
        depth = np.full((10, 10), 20.0, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_just_under_20m_valid(self, estimator: DepthAnything3Estimator) -> None:
        """19.99m is valid (less than 20m)."""
        depth = np.full((10, 10), 19.99, dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 1.0

    def test_empty_depth_map(self, estimator: DepthAnything3Estimator) -> None:
        """Empty depth map returns 0.0."""
        depth = np.array([], dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        assert ratio == 0.0

    def test_mixed_edge_cases(self, estimator: DepthAnything3Estimator) -> None:
        """Mixed array with NaN, inf, negative, zero, and valid values."""
        # 10 pixels total: 4 valid, 6 invalid
        depth = np.array([
            [np.nan, np.inf, -1.0, 0.0, 20.0],
            [1.0, 5.0, 10.0, 19.9, -np.inf],
        ], dtype=np.float32)
        ratio = estimator.validate_depth_map(depth)
        # valid: 1.0, 5.0, 10.0, 19.9 → 4/10 = 0.4
        assert ratio == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Fallback chain tests
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Tests for the DA3 → MoGe-2 → flat-floor fallback order."""

    @pytest.mark.asyncio
    async def test_da3_fails_moge2_succeeds(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """When DA3 fails with ComfyUIError, MoGe-2 fallback is used."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # DA3 workflow raises ComfyUIError
        # MoGe-2 workflow succeeds with a valid depth map
        valid_depth = np.full((100, 100), 3.0, dtype=np.float32)

        call_count = {"value": 0}

        async def mock_submit(workflow, placeholders=None):
            call_count["value"] += 1
            if call_count["value"] == 1:
                # DA3 attempt
                raise ComfyUIError("DA3 model not available")
            # MoGe-2 attempt
            return "prompt_id_moge2"

        mock_client.submit_workflow = AsyncMock(side_effect=mock_submit)
        mock_client.wait_for_completion = AsyncMock()

        # Mock load_workflow to succeed for both
        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            # After MoGe-2 "completes", mock the output directory to have a .npy file
            moge2_raw_dir = tmp_path / "depth" / "moge2_raw"
            moge2_raw_dir.mkdir(parents=True, exist_ok=True)
            np.save(moge2_raw_dir / "depth.npy", valid_depth)

            result = await estimator.estimate(source_image, config)

        assert isinstance(result, DepthResult)
        assert result.valid_pixel_ratio == 1.0

    @pytest.mark.asyncio
    async def test_both_fail_flat_floor_used(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """When both DA3 and MoGe-2 fail, flat-floor heuristic is used."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # Both workflows raise ComfyUIError
        mock_client.submit_workflow = AsyncMock(
            side_effect=ComfyUIError("Model not available")
        )

        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            result = await estimator.estimate(source_image, config)

        assert isinstance(result, DepthResult)
        # Flat-floor should produce valid depths (all between 1-5m)
        assert result.valid_pixel_ratio == 1.0

        # Verify the saved depth map is the flat-floor linear gradient
        depth_loaded = np.load(result.depth_map_path)
        assert depth_loaded.shape == (100, 100)

        # Top row should be ~1m, bottom row should be ~5m
        assert depth_loaded[0, 0] == pytest.approx(_FLAT_FLOOR_TOP_DEPTH_M, abs=0.01)
        assert depth_loaded[-1, 0] == pytest.approx(_FLAT_FLOOR_BOTTOM_DEPTH_M, abs=0.01)

    @pytest.mark.asyncio
    async def test_flat_floor_linear_from_1_to_5(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """Flat-floor output is linear from 1m (top) to 5m (bottom)."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # Force fallback to flat-floor
        mock_client.submit_workflow = AsyncMock(
            side_effect=ComfyUIError("unavailable")
        )

        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            result = await estimator.estimate(source_image, config)

        depth = np.load(result.depth_map_path)

        # All columns in the same row should have the same value (broadcast)
        assert np.allclose(depth[0, :], depth[0, 0])
        assert np.allclose(depth[-1, :], depth[-1, 0])

        # Check linearity: middle row should be ~3m for 100 rows
        mid_row = depth.shape[0] // 2
        expected_mid = _FLAT_FLOOR_TOP_DEPTH_M + (
            _FLAT_FLOOR_BOTTOM_DEPTH_M - _FLAT_FLOOR_TOP_DEPTH_M
        ) * (mid_row / (depth.shape[0] - 1))
        assert depth[mid_row, 0] == pytest.approx(expected_mid, abs=0.05)

        # Verify monotonically increasing from top to bottom
        col_values = depth[:, 0]
        assert np.all(np.diff(col_values) >= 0)


# ---------------------------------------------------------------------------
# .npy save/load tests
# ---------------------------------------------------------------------------


class TestNpySaveLoad:
    """Tests for .npy file save and load of depth maps."""

    @pytest.mark.asyncio
    async def test_depth_map_saved_as_npy(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """estimate() saves depth map as .npy at the expected path."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # Mock DA3 to succeed with a known depth map
        valid_depth = np.full((100, 100), 4.5, dtype=np.float32)

        mock_client.submit_workflow = AsyncMock(return_value="prompt_123")
        mock_client.wait_for_completion = AsyncMock()

        # Pre-create the DA3 raw output dir with a .npy file
        da3_raw_dir = tmp_path / "depth" / "da3_raw"
        da3_raw_dir.mkdir(parents=True, exist_ok=True)
        np.save(da3_raw_dir / "depth.npy", valid_depth)

        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            result = await estimator.estimate(source_image, config)

        # Verify .npy file exists at the returned path
        assert result.depth_map_path.exists()
        assert result.depth_map_path.suffix == ".npy"

    @pytest.mark.asyncio
    async def test_npy_round_trip_matches(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """Loaded .npy matches the expected depth values (bit-identical)."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # Create a depth map with specific known values
        expected_depth = np.random.default_rng(42).uniform(
            0.5, 15.0, size=(100, 100)
        ).astype(np.float32)

        mock_client.submit_workflow = AsyncMock(return_value="prompt_abc")
        mock_client.wait_for_completion = AsyncMock()

        da3_raw_dir = tmp_path / "depth" / "da3_raw"
        da3_raw_dir.mkdir(parents=True, exist_ok=True)
        np.save(da3_raw_dir / "depth.npy", expected_depth)

        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            result = await estimator.estimate(source_image, config)

        # Load saved file and verify bit-identical round-trip
        loaded = np.load(result.depth_map_path)
        assert loaded.dtype == np.float32
        assert loaded.shape == (100, 100)
        np.testing.assert_array_equal(loaded, expected_depth)

    @pytest.mark.asyncio
    async def test_depth_range_in_result(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        config: PhotoPipelineConfig,
        source_image: Path,
    ) -> None:
        """DepthResult includes correct depth_range_m from valid pixels."""
        estimator = DepthAnything3Estimator(client=mock_client, output_dir=tmp_path)

        # Depth map with known min/max
        depth = np.full((100, 100), 5.0, dtype=np.float32)
        depth[0, 0] = 1.5  # min
        depth[99, 99] = 15.0  # max

        mock_client.submit_workflow = AsyncMock(return_value="prompt_range")
        mock_client.wait_for_completion = AsyncMock()

        da3_raw_dir = tmp_path / "depth" / "da3_raw"
        da3_raw_dir.mkdir(parents=True, exist_ok=True)
        np.save(da3_raw_dir / "depth.npy", depth)

        with patch(
            "src.photo_pipeline.stages.depth_anything3.load_workflow",
            return_value={"nodes": {}},
        ):
            result = await estimator.estimate(source_image, config)

        assert result.depth_range_m[0] == pytest.approx(1.5)
        assert result.depth_range_m[1] == pytest.approx(15.0)
