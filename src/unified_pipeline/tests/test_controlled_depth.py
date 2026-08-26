"""Tests for render_controlled_depth — deterministic controlled-camera depth source.

Validates that the controlled-camera z-render produces a valid float32 depth map
from a MetricPlan + CameraContract using _build_projector (not monocular estimation).

Requirements: 2.1, 3.3, 3.4
"""

from __future__ import annotations

import numpy as np
import pytest

from src.unified_pipeline.blockout_renderer import render_controlled_depth
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.models import (
    ControlledCameraDepth,
    MetricPlan,
    PlanRevision,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def camera() -> CameraContract:
    """Standard camera positioned at corner looking at center."""
    return CameraContract(
        position=(2.0, 1.6, -1.5),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        aspect=1024.0 / 768.0,
        near=0.05,
        far=100.0,
        raster_width=1024,
        raster_height=768,
    )


@pytest.fixture
def kitchenette_plan() -> MetricPlan:
    """Danny's kitchenette plan with typical objects and openings."""
    return MetricPlan(
        room_dimensions=(4.0, 2.7, 3.0),
        walls=(
            {"name": "north", "start": (-2, 0, 1.5), "end": (2, 0, 1.5)},
            {"name": "south", "start": (2, 0, -1.5), "end": (-2, 0, -1.5)},
            {"name": "east", "start": (2, 0, 1.5), "end": (2, 0, -1.5)},
            {"name": "west", "start": (-2, 0, -1.5), "end": (-2, 0, 1.5)},
        ),
        openings=(
            {"wall": "south", "kind": "door", "width": 0.9, "height": 2.1, "sill_height": 0.0, "position": 0.3},
            {"wall": "north", "kind": "window", "width": 1.2, "height": 1.0, "sill_height": 0.9, "position": 0.5},
        ),
        object_placements=(
            {"name": "round_table", "position": [0.0, 0.0, 0.0], "dimensions": [0.8, 0.75, 0.8], "rotation": 0.0},
            {"name": "chair_1", "position": [-0.5, 0.0, -0.5], "dimensions": [0.4, 0.85, 0.4], "rotation": 45.0},
            {"name": "chair_2", "position": [0.5, 0.0, 0.5], "dimensions": [0.4, 0.85, 0.4], "rotation": -45.0},
            {"name": "counter", "position": [0.0, 0.0, 1.2], "dimensions": [2.0, 0.9, 0.6], "rotation": 0.0},
            {"name": "coffee_maker", "position": [0.5, 0.9, 1.2], "dimensions": [0.3, 0.4, 0.25], "rotation": 0.0},
        ),
        revisions=(
            PlanRevision(revision=3, changed="layout", reason="generated", plan_hash="abc123"),
        ),
        template_id="kitchenette_standard",
    )


@pytest.fixture
def empty_plan() -> MetricPlan:
    """Minimal plan with no objects or openings."""
    return MetricPlan(
        room_dimensions=(3.0, 2.5, 3.0),
        walls=(),
        openings=(),
        object_placements=(),
        revisions=(),
        template_id="empty",
    )


# ─── Tests: render_controlled_depth ───────────────────────────────────────────


class TestRenderControlledDepth:
    """Test the deterministic controlled-camera depth rendering."""

    def test_returns_controlled_camera_depth(self, kitchenette_plan, camera):
        """render_controlled_depth returns a ControlledCameraDepth instance."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert isinstance(result, ControlledCameraDepth)

    def test_depth_map_shape_matches_raster(self, kitchenette_plan, camera):
        """Depth map shape is (raster_height, raster_width) from the CameraContract."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert result.depth_map.shape == (768, 1024)

    def test_depth_map_dtype_float32(self, kitchenette_plan, camera):
        """Depth map is float32."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert result.depth_map.dtype == np.float32

    def test_depth_map_has_geometry(self, kitchenette_plan, camera):
        """With scene geometry, some pixels have finite depth values."""
        result = render_controlled_depth(kitchenette_plan, camera)
        finite_mask = np.isfinite(result.depth_map)
        # Must have at least some geometry visible
        assert finite_mask.sum() > 0

    def test_depth_values_positive(self, kitchenette_plan, camera):
        """All finite depth values are positive (in front of camera)."""
        result = render_controlled_depth(kitchenette_plan, camera)
        finite = result.depth_map[np.isfinite(result.depth_map)]
        assert (finite > 0).all()

    def test_no_geometry_pixels_are_inf(self, kitchenette_plan, camera):
        """Pixels with no geometry have np.inf depth."""
        result = render_controlled_depth(kitchenette_plan, camera)
        # Background pixels should be inf
        inf_mask = np.isinf(result.depth_map)
        # There should be some background pixels (not 100% coverage)
        assert inf_mask.sum() > 0

    def test_camera_hash_bound(self, kitchenette_plan, camera):
        """Result carries camera_hash for provenance."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert result.camera_hash != ""
        assert result.camera_hash == camera.compute_hash()

    def test_plan_revision_bound(self, kitchenette_plan, camera):
        """Result carries plan_revision for provenance."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert result.plan_revision == 3  # from the fixture

    def test_provenance_dict_present(self, kitchenette_plan, camera):
        """Result carries provenance dict with camera_hash + plan_revision."""
        result = render_controlled_depth(kitchenette_plan, camera)
        assert "camera_hash" in result.provenance
        assert "plan_revision" in result.provenance
        assert result.provenance["source"] == "controlled_camera_z_render"
        assert result.provenance["authority"] == "geometry_echo"

    def test_deterministic_across_calls(self, kitchenette_plan, camera):
        """Same inputs produce identical depth maps (deterministic)."""
        result1 = render_controlled_depth(kitchenette_plan, camera)
        result2 = render_controlled_depth(kitchenette_plan, camera)
        np.testing.assert_array_equal(result1.depth_map, result2.depth_map)

    def test_empty_plan_no_geometry_pixels(self, empty_plan, camera):
        """With no walls/objects, only floor gives geometry (if visible)."""
        result = render_controlled_depth(empty_plan, camera)
        assert result.depth_map.shape == (768, 1024)
        assert result.depth_map.dtype == np.float32

    def test_to_dict_round_trip(self, kitchenette_plan, camera):
        """ControlledCameraDepth.to_dict serializes metadata (not the array)."""
        result = render_controlled_depth(kitchenette_plan, camera)
        d = result.to_dict()
        assert d["camera_hash"] == result.camera_hash
        assert d["plan_revision"] == result.plan_revision
        assert d["depth_map_shape"] == [768, 1024]
        assert d["depth_map_dtype"] == "float32"

    def test_depth_map_not_override_metric_plan(self, kitchenette_plan, camera):
        """Provenance explicitly marks this as geometry_echo — not spatial authority."""
        result = render_controlled_depth(kitchenette_plan, camera)
        # The depth is read-only, does NOT override MetricPlan
        assert result.provenance["authority"] == "geometry_echo"
        assert result.provenance["source"] == "controlled_camera_z_render"
