"""Unit tests for V14 layout estimation updates.

Tests the V14LayoutEstimator class and supporting utilities:
- Back-projection with DA3 depth via camera_math.back_project
- Invalid depth fallback (averaging mask region)
- Position clamping within room shell bounds (0.05m margin)
- Mesh scaling from normalized bounding box to ScaleResult.dimensions_m

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.photo_pipeline.models import LayoutResult, ScaleResult, SegmentedObject
from src.photo_pipeline.stages.layout_estimator import (
    V14LayoutEstimator,
    compute_room_bounds,
    sample_depth_at_centroid,
    scale_mesh_to_dimensions,
)
from src.photo_pipeline.stages.camera_math import back_project, clamp_to_bounds
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def estimator() -> V14LayoutEstimator:
    """Default V14 layout estimator with standard settings."""
    return V14LayoutEstimator(fov_v_deg=60.0, clamp_margin=0.05)


@pytest.fixture
def valid_depth_map() -> np.ndarray:
    """A simple 100x100 depth map with uniform depth 3.0m."""
    return np.full((100, 100), 3.0, dtype=np.float32)


@pytest.fixture
def depth_map_with_invalid_center() -> np.ndarray:
    """Depth map with invalid (zero) depth at center, valid elsewhere."""
    dm = np.full((100, 100), 2.5, dtype=np.float32)
    # Make center region invalid
    dm[45:55, 45:55] = 0.0
    return dm


@pytest.fixture
def sample_object() -> SegmentedObject:
    """A sample segmented object at image center."""
    return SegmentedObject(
        mask_id="obj_01",
        bbox=(30, 30, 40, 40),  # x, y, width, height
        area_px=1600,
        centroid_px=(50.0, 50.0),
        object_png_path=Path("test_obj.png"),
    )


@pytest.fixture
def sample_scale() -> ScaleResult:
    """Sample scale result: 0.5m × 0.8m × 0.3m object."""
    return ScaleResult(
        dimensions_m=(0.5, 0.8, 0.3),
        scale_factor=1.0,
        confidence=0.85,
    )


# ---------------------------------------------------------------------------
# Tests: sample_depth_at_centroid (Requirement 4.5)
# ---------------------------------------------------------------------------


class TestSampleDepthAtCentroid:
    """Tests for depth sampling with mask-region fallback."""

    def test_valid_depth_at_centroid(self, valid_depth_map: np.ndarray):
        """Returns depth directly when centroid has valid value."""
        d = sample_depth_at_centroid(valid_depth_map, (50.0, 50.0))
        assert d == pytest.approx(3.0)

    def test_invalid_depth_falls_back_to_mask_region(
        self, depth_map_with_invalid_center: np.ndarray
    ):
        """Averages mask region when centroid depth is zero."""
        # Centroid at (50, 50) is in the invalid zone
        d = sample_depth_at_centroid(
            depth_map_with_invalid_center,
            (50.0, 50.0),
            mask_bbox=(30, 30, 40, 40),
        )
        # The mask region (30:70, 30:70) contains both valid (2.5) and invalid (0) areas
        # Valid pixels in that region should average to 2.5
        assert d == pytest.approx(2.5)

    def test_invalid_depth_no_bbox_uses_whole_map(
        self, depth_map_with_invalid_center: np.ndarray
    ):
        """Falls back to entire map average when no bbox provided."""
        d = sample_depth_at_centroid(
            depth_map_with_invalid_center, (50.0, 50.0), mask_bbox=None
        )
        # Most pixels are 2.5, some are 0 (excluded from valid)
        assert d == pytest.approx(2.5)

    def test_all_invalid_depth_returns_fallback(self):
        """Returns 3.0m when entire depth map is invalid."""
        invalid_map = np.zeros((50, 50), dtype=np.float32)
        d = sample_depth_at_centroid(invalid_map, (25.0, 25.0), mask_bbox=(0, 0, 50, 50))
        assert d == pytest.approx(3.0)

    def test_infinite_depth_triggers_fallback(self):
        """Handles infinite depth at centroid."""
        dm = np.full((50, 50), 4.0, dtype=np.float32)
        dm[25, 25] = np.inf
        d = sample_depth_at_centroid(dm, (25.0, 25.0), mask_bbox=(0, 0, 50, 50))
        assert d == pytest.approx(4.0)

    def test_negative_depth_triggers_fallback(self):
        """Handles negative depth at centroid."""
        dm = np.full((50, 50), 2.0, dtype=np.float32)
        dm[25, 25] = -1.0
        d = sample_depth_at_centroid(dm, (25.0, 25.0), mask_bbox=(0, 0, 50, 50))
        assert d == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Tests: scale_mesh_to_dimensions (Requirement 4.6)
# ---------------------------------------------------------------------------


class TestScaleMeshToDimensions:
    """Tests for mesh bounding box to real-world dimension scaling."""

    def test_normalized_unit_mesh(self):
        """Scales [-1,1] mesh bbox to target dimensions."""
        # Hunyuan3D normalizes to approximately [-1, 1]
        bbox_min = (-1.0, -1.0, -1.0)
        bbox_max = (1.0, 1.0, 1.0)
        target = (0.5, 0.8, 0.3)

        sx, sy, sz = scale_mesh_to_dimensions(bbox_min, bbox_max, target)
        # Extent is 2.0 on each axis
        assert sx == pytest.approx(0.5 / 2.0)  # 0.25
        assert sy == pytest.approx(0.8 / 2.0)  # 0.4
        assert sz == pytest.approx(0.3 / 2.0)  # 0.15

    def test_asymmetric_mesh_bbox(self):
        """Handles non-centered mesh bounding boxes."""
        bbox_min = (0.0, 0.0, 0.0)
        bbox_max = (2.0, 4.0, 1.0)
        target = (1.0, 2.0, 0.5)

        sx, sy, sz = scale_mesh_to_dimensions(bbox_min, bbox_max, target)
        assert sx == pytest.approx(1.0 / 2.0)  # 0.5
        assert sy == pytest.approx(2.0 / 4.0)  # 0.5
        assert sz == pytest.approx(0.5 / 1.0)  # 0.5

    def test_zero_extent_returns_unit_scale(self):
        """Returns scale 1.0 for degenerate (zero-extent) mesh axes."""
        bbox_min = (0.0, 0.0, 0.0)
        bbox_max = (2.0, 0.0, 1.0)  # Y extent is 0
        target = (0.5, 0.8, 0.3)

        sx, sy, sz = scale_mesh_to_dimensions(bbox_min, bbox_max, target)
        assert sx == pytest.approx(0.5 / 2.0)
        assert sy == 1.0  # degenerate axis
        assert sz == pytest.approx(0.3 / 1.0)

    def test_already_correct_size_returns_one(self):
        """Returns (1, 1, 1) when mesh already matches target."""
        bbox_min = (0.0, 0.0, 0.0)
        bbox_max = (0.5, 0.8, 0.3)
        target = (0.5, 0.8, 0.3)

        sx, sy, sz = scale_mesh_to_dimensions(bbox_min, bbox_max, target)
        assert sx == pytest.approx(1.0)
        assert sy == pytest.approx(1.0)
        assert sz == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: compute_room_bounds
# ---------------------------------------------------------------------------


class TestComputeRoomBounds:
    """Tests for room bounding box computation."""

    def test_standard_room(self):
        """Room 4m wide, 2.7m tall, 5m deep."""
        bbox_min, bbox_max = compute_room_bounds((4.0, 2.7, 5.0))
        assert bbox_min == (-2.0, 0.0, -5.0)
        assert bbox_max == (2.0, 2.7, 0.0)

    def test_small_room(self):
        """Small room dimensions."""
        bbox_min, bbox_max = compute_room_bounds((2.0, 2.4, 3.0))
        assert bbox_min == (-1.0, 0.0, -3.0)
        assert bbox_max == (1.0, 2.4, 0.0)


# ---------------------------------------------------------------------------
# Tests: V14LayoutEstimator.estimate_position (Requirements 4.1, 4.2, 4.4, 4.5)
# ---------------------------------------------------------------------------


class TestV14LayoutEstimatorPosition:
    """Tests for single-object position estimation."""

    def test_center_pixel_projects_to_origin_xz(self, estimator: V14LayoutEstimator):
        """Center pixel at known depth projects near (0, 0, -d)."""
        dm = np.full((100, 100), 3.0, dtype=np.float32)
        pos = estimator.estimate_position(
            centroid_px=(50.0, 50.0),
            depth_map=dm,
            image_size=(100, 100),
            room_dimensions_m=(6.0, 3.0, 6.0),
        )
        # At center: x ≈ 0, z ≈ -3.0
        assert pos[0] == pytest.approx(0.0, abs=0.01)
        assert pos[2] == pytest.approx(-3.0, abs=0.01)

    def test_off_center_pixel_produces_lateral_offset(
        self, estimator: V14LayoutEstimator
    ):
        """Pixel to the right of center produces positive x."""
        dm = np.full((100, 100), 2.0, dtype=np.float32)
        pos = estimator.estimate_position(
            centroid_px=(75.0, 50.0),
            depth_map=dm,
            image_size=(100, 100),
            room_dimensions_m=(10.0, 3.0, 10.0),
        )
        # x > 0 because u > cx
        assert pos[0] > 0

    def test_position_clamped_within_room_bounds(
        self, estimator: V14LayoutEstimator
    ):
        """Position at extreme depth gets clamped to room bounds."""
        # Very large depth → position would exceed room bounds
        dm = np.full((100, 100), 50.0, dtype=np.float32)
        pos = estimator.estimate_position(
            centroid_px=(10.0, 10.0),  # Top-left → large x offset
            depth_map=dm,
            image_size=(100, 100),
            room_dimensions_m=(4.0, 2.7, 5.0),
        )
        # Should be clamped to within room bounds minus margin
        bbox_min, bbox_max = compute_room_bounds((4.0, 2.7, 5.0))
        margin = 0.05
        assert pos[0] >= bbox_min[0] + margin - 1e-9
        assert pos[0] <= bbox_max[0] - margin + 1e-9
        assert pos[1] >= bbox_min[1] + margin - 1e-9
        assert pos[1] <= bbox_max[1] - margin + 1e-9
        assert pos[2] >= bbox_min[2] + margin - 1e-9
        assert pos[2] <= bbox_max[2] - margin + 1e-9

    def test_invalid_depth_uses_mask_region_fallback(
        self, estimator: V14LayoutEstimator
    ):
        """When centroid depth is invalid, uses mask region average."""
        dm = np.full((100, 100), 4.0, dtype=np.float32)
        dm[50, 50] = 0.0  # Invalid at centroid
        pos = estimator.estimate_position(
            centroid_px=(50.0, 50.0),
            depth_map=dm,
            image_size=(100, 100),
            room_dimensions_m=(10.0, 5.0, 10.0),
            mask_bbox=(30, 30, 40, 40),
        )
        # Should use ~4.0m depth from mask region, project to ~ (0, 0, -4)
        assert pos[2] == pytest.approx(-4.0, abs=0.1)


# ---------------------------------------------------------------------------
# Tests: V14LayoutEstimator.estimate_all (Requirement 4.3)
# ---------------------------------------------------------------------------


class TestV14LayoutEstimatorAll:
    """Tests for batch estimation with physics settle."""

    def test_empty_objects_returns_empty(self, estimator: V14LayoutEstimator):
        """No objects → no results."""
        results = estimator.estimate_all(
            objects=[],
            scales=[],
            depth_map=np.full((100, 100), 3.0, dtype=np.float32),
            image_size=(100, 100),
            room_dimensions_m=(4.0, 2.7, 5.0),
        )
        assert results == []

    def test_mismatched_lengths_raises(self, estimator: V14LayoutEstimator):
        """Mismatched objects/scales lengths raises ValueError."""
        obj = SegmentedObject(
            mask_id="obj_01",
            bbox=(10, 10, 20, 20),
            area_px=400,
            centroid_px=(20.0, 20.0),
            object_png_path=Path("obj.png"),
        )
        with pytest.raises(ValueError, match="must have same length"):
            estimator.estimate_all(
                objects=[obj],
                scales=[],
                depth_map=np.full((100, 100), 3.0, dtype=np.float32),
                image_size=(100, 100),
                room_dimensions_m=(4.0, 2.7, 5.0),
            )

    def test_single_object_produces_layout_result(
        self, estimator: V14LayoutEstimator, sample_object: SegmentedObject,
        sample_scale: ScaleResult, valid_depth_map: np.ndarray
    ):
        """Single object produces valid LayoutResult."""
        results = estimator.estimate_all(
            objects=[sample_object],
            scales=[sample_scale],
            depth_map=valid_depth_map,
            image_size=(100, 100),
            room_dimensions_m=(6.0, 3.0, 6.0),
        )
        assert len(results) == 1
        assert isinstance(results[0], LayoutResult)
        assert len(results[0].position_m) == 3
        assert len(results[0].rotation_deg) == 3

    def test_multiple_objects(self, estimator: V14LayoutEstimator):
        """Multiple objects all get positions within room bounds."""
        objects = [
            SegmentedObject(
                mask_id=f"obj_{i:02d}",
                bbox=(10 + i * 20, 10, 15, 15),
                area_px=225,
                centroid_px=(17.5 + i * 20, 17.5),
                object_png_path=Path(f"obj_{i}.png"),
            )
            for i in range(3)
        ]
        scales = [
            ScaleResult(dimensions_m=(0.3, 0.4, 0.2), scale_factor=1.0, confidence=0.8)
            for _ in range(3)
        ]
        dm = np.full((100, 100), 2.5, dtype=np.float32)
        room_dims = (6.0, 3.0, 6.0)

        results = estimator.estimate_all(
            objects=objects,
            scales=scales,
            depth_map=dm,
            image_size=(100, 100),
            room_dimensions_m=room_dims,
        )
        assert len(results) == 3

        bbox_min, bbox_max = compute_room_bounds(room_dims)
        for r in results:
            for axis in range(3):
                assert r.position_m[axis] >= bbox_min[axis] + 0.05 - 1e-9
                assert r.position_m[axis] <= bbox_max[axis] - 0.05 + 1e-9


# ---------------------------------------------------------------------------
# Tests: V14LayoutEstimator.compute_mesh_scale (Requirement 4.6)
# ---------------------------------------------------------------------------


class TestV14LayoutEstimatorMeshScale:
    """Tests for mesh scale computation."""

    def test_normalized_mesh_scaling(self, estimator: V14LayoutEstimator):
        """Normalized [-1,1] mesh scales to ScaleResult dimensions."""
        scale_result = ScaleResult(
            dimensions_m=(0.5, 0.8, 0.3), scale_factor=1.0, confidence=0.9
        )
        sx, sy, sz = estimator.compute_mesh_scale(
            mesh_bbox_min=(-1.0, -1.0, -1.0),
            mesh_bbox_max=(1.0, 1.0, 1.0),
            scale_result=scale_result,
        )
        assert sx == pytest.approx(0.25)  # 0.5 / 2.0
        assert sy == pytest.approx(0.40)  # 0.8 / 2.0
        assert sz == pytest.approx(0.15)  # 0.3 / 2.0

    def test_hunyuan3d_typical_mesh(self, estimator: V14LayoutEstimator):
        """Handles typical Hunyuan3D mesh range [-0.9999, 0.9999]."""
        scale_result = ScaleResult(
            dimensions_m=(1.0, 1.5, 0.8), scale_factor=1.0, confidence=0.85
        )
        sx, sy, sz = estimator.compute_mesh_scale(
            mesh_bbox_min=(-0.9999, -0.9999, -0.9999),
            mesh_bbox_max=(0.9999, 0.9999, 0.9999),
            scale_result=scale_result,
        )
        expected_extent = 1.9998
        assert sx == pytest.approx(1.0 / expected_extent, rel=1e-3)
        assert sy == pytest.approx(1.5 / expected_extent, rel=1e-3)
        assert sz == pytest.approx(0.8 / expected_extent, rel=1e-3)
