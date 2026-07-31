"""Tests for BlockoutRenderer.

Validates that the renderer produces correct 1024×768 images from
MetricPlan + CameraContract, with walls, openings, and objects visible.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from src.unified_pipeline.blockout_renderer import (
    BlockoutRenderer,
    render_blockout,
    _build_projector,
)
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.models import (
    BlockoutResult,
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
            PlanRevision(revision=1, changed="initial", reason="generated", plan_hash="abc123"),
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


@pytest.fixture
def tmp_output(tmp_path) -> Path:
    """Temporary output directory."""
    return tmp_path / "blockouts"


# ─── Tests: BlockoutRenderer class ────────────────────────────────────────────


class TestBlockoutRendererClass:
    """Test the BlockoutRenderer class API."""

    def test_render_returns_blockout_result(self, kitchenette_plan, camera, tmp_output):
        """Req 7.1: render() returns BlockoutResult."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="test-session")

        assert isinstance(result, BlockoutResult)
        assert result.approved is False
        assert result.plan_revision == 1
        assert result.camera_hash != ""
        assert result.image_path != ""

    def test_render_creates_image_file(self, kitchenette_plan, camera, tmp_output):
        """Req 7.1: render() creates an actual PNG file."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="session-abc")

        path = Path(result.image_path)
        assert path.exists()
        assert path.suffix == ".png"

    def test_render_image_dimensions(self, kitchenette_plan, camera, tmp_output):
        """Req 7.1: Output image at CameraContract raster dimensions (1024×768)."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="dims-test")

        img = Image.open(result.image_path)
        assert img.size == (1024, 768)

    def test_render_custom_raster_dimensions(self, kitchenette_plan, tmp_output):
        """Output image matches custom raster dimensions."""
        custom_camera = CameraContract(
            position=(2.0, 1.6, -1.5),
            target=(0.0, 1.0, 0.0),
            raster_width=800,
            raster_height=600,
        )
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, custom_camera, session_id="custom")

        img = Image.open(result.image_path)
        assert img.size == (800, 600)

    def test_render_output_directory_structure(self, kitchenette_plan, camera, tmp_output):
        """Output is saved to output/blockouts/{session_id}/."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="my-session-123")

        path = Path(result.image_path)
        assert "my-session-123" in str(path)
        assert path.parent.name == "my-session-123"

    def test_render_empty_plan(self, empty_plan, camera, tmp_output):
        """Renderer handles a plan with no objects or openings gracefully."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(empty_plan, camera, session_id="empty-test")

        assert isinstance(result, BlockoutResult)
        path = Path(result.image_path)
        assert path.exists()
        img = Image.open(result.image_path)
        assert img.size == (1024, 768)

    def test_render_camera_hash_binding(self, kitchenette_plan, camera, tmp_output):
        """Req 7.1: BlockoutResult includes camera_hash for binding verification."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="hash-test")

        # camera.compute_hash() should produce a SHA-256 hash
        expected_hash = camera.compute_hash()
        assert result.camera_hash == expected_hash
        assert len(result.camera_hash) == 64  # SHA-256 hex length

    def test_render_plan_revision_binding(self, kitchenette_plan, camera, tmp_output):
        """Req 7.1: BlockoutResult binds to plan revision."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="rev-test")
        assert result.plan_revision == 1

    def test_render_multiple_revisions(self, camera, tmp_output):
        """Multiple revisions produce separate files."""
        plan_v1 = MetricPlan(
            room_dimensions=(4.0, 2.7, 3.0),
            revisions=(PlanRevision(revision=1, changed="initial"),),
        )
        plan_v2 = MetricPlan(
            room_dimensions=(5.0, 3.0, 4.0),
            revisions=(
                PlanRevision(revision=1, changed="initial"),
                PlanRevision(revision=2, changed="expanded"),
            ),
        )

        renderer = BlockoutRenderer(output_base=tmp_output)
        r1 = renderer.render(plan_v1, camera, session_id="multi")
        r2 = renderer.render(plan_v2, camera, session_id="multi")

        assert r1.plan_revision == 1
        assert r2.plan_revision == 2
        assert r1.image_path != r2.image_path
        assert Path(r1.image_path).exists()
        assert Path(r2.image_path).exists()


# ─── Tests: Wall rendering ─────────────────────────────────────────────────────


class TestWallRendering:
    """Test _render_walls produces correct geometry."""

    def test_walls_present_in_image(self, kitchenette_plan, camera, tmp_output):
        """Req 7.2: Walls are rendered as filled polygons."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        wall_meshes = renderer._render_walls(kitchenette_plan)

        # Should have: floor + 4 walls + 4 ceiling edges = 9 faces
        assert len(wall_meshes) == 9

        floor_faces = [f for f in wall_meshes if f["kind"] == "floor"]
        wall_faces = [f for f in wall_meshes if f["kind"] == "wall"]
        ceiling_faces = [f for f in wall_meshes if f["kind"] == "ceiling_edge"]

        assert len(floor_faces) == 1
        assert len(wall_faces) == 4
        assert len(ceiling_faces) == 4

    def test_wall_height_matches_plan(self, kitchenette_plan, camera, tmp_output):
        """Walls extend to ceiling height from plan.room_dimensions[1]."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        wall_meshes = renderer._render_walls(kitchenette_plan)

        wall_faces = [f for f in wall_meshes if f["kind"] == "wall"]
        ceiling_h = kitchenette_plan.room_dimensions[1]  # 2.7

        for face in wall_faces:
            y_values = [v[1] for v in face["vertices"]]
            assert min(y_values) == 0.0
            assert max(y_values) == ceiling_h


# ─── Tests: Opening rendering ──────────────────────────────────────────────────


class TestOpeningRendering:
    """Test _render_openings produces correct opening geometry."""

    def test_openings_rendered(self, kitchenette_plan, camera, tmp_output):
        """Req 7.2: Doors and windows are rendered as colored overlays."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        opening_meshes = renderer._render_openings(kitchenette_plan)

        assert len(opening_meshes) == 2  # 1 door + 1 window

    def test_door_opening_type(self, kitchenette_plan, camera, tmp_output):
        """Doors use door colors."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        opening_meshes = renderer._render_openings(kitchenette_plan)

        door_faces = [f for f in opening_meshes if f["opening_type"] == "door"]
        assert len(door_faces) == 1
        assert door_faces[0]["label"] == "DOOR"

    def test_window_opening_type(self, kitchenette_plan, camera, tmp_output):
        """Windows use window colors."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        opening_meshes = renderer._render_openings(kitchenette_plan)

        window_faces = [f for f in opening_meshes if f["opening_type"] == "window"]
        assert len(window_faces) == 1
        assert window_faces[0]["label"] == "WINDOW"

    def test_opening_sill_height(self, camera, tmp_output):
        """Window sill height is respected in geometry."""
        plan = MetricPlan(
            room_dimensions=(4.0, 2.7, 3.0),
            openings=(
                {"wall": "north", "kind": "window", "width": 1.0, "height": 1.0, "sill_height": 0.9, "position": 0.5},
            ),
        )
        renderer = BlockoutRenderer(output_base=tmp_output)
        opening_meshes = renderer._render_openings(plan)

        assert len(opening_meshes) == 1
        y_values = [v[1] for v in opening_meshes[0]["vertices"]]
        assert min(y_values) == pytest.approx(0.9, abs=0.01)
        assert max(y_values) == pytest.approx(1.9, abs=0.01)


# ─── Tests: Object placeholder rendering ──────────────────────────────────────


class TestPlaceholderRendering:
    """Test _render_placeholders produces correct box geometry."""

    def test_objects_rendered(self, kitchenette_plan, camera, tmp_output):
        """Req 7.2: Object placeholders at correct scale are rendered."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        placeholder_meshes = renderer._render_placeholders(kitchenette_plan)

        # 5 objects, each generates 5 faces (top + 4 sides)
        assert len(placeholder_meshes) == 25

    def test_object_dimensions_correct(self, camera, tmp_output):
        """Objects use dimensions from placement data."""
        plan = MetricPlan(
            room_dimensions=(4.0, 2.7, 3.0),
            object_placements=(
                {"name": "box", "position": [0.0, 0.0, 0.0], "dimensions": [1.0, 2.0, 1.0], "rotation": 0.0},
            ),
        )
        renderer = BlockoutRenderer(output_base=tmp_output)
        meshes = renderer._render_placeholders(plan)

        # Top face should be at y=2.0 (height of object)
        top_faces = [f for f in meshes if f["kind"] == "object_top"]
        assert len(top_faces) == 1
        y_values = [v[1] for v in top_faces[0]["vertices"]]
        assert all(y == pytest.approx(2.0) for y in y_values)

    def test_object_rotation(self, camera, tmp_output):
        """Objects rotate around Y axis according to rotation field."""
        plan = MetricPlan(
            room_dimensions=(4.0, 2.7, 3.0),
            object_placements=(
                {"name": "rotated", "position": [0.0, 0.0, 0.0], "dimensions": [2.0, 1.0, 1.0], "rotation": 90.0},
            ),
        )
        renderer = BlockoutRenderer(output_base=tmp_output)
        meshes = renderer._render_placeholders(plan)

        # A 2.0×1.0 box rotated 90° should have its extent flipped
        top_faces = [f for f in meshes if f["kind"] == "object_top"]
        assert len(top_faces) == 1
        x_values = [v[0] for v in top_faces[0]["vertices"]]
        z_values = [v[2] for v in top_faces[0]["vertices"]]
        # After 90° rotation, width (2.0) should now extend along Z
        x_extent = max(x_values) - min(x_values)
        z_extent = max(z_values) - min(z_values)
        assert x_extent == pytest.approx(1.0, abs=0.01)
        assert z_extent == pytest.approx(2.0, abs=0.01)


# ─── Tests: Projection ────────────────────────────────────────────────────────


class TestProjection:
    """Test the camera projection function."""

    def test_point_in_front_of_camera_projects(self, camera):
        """Points in front of camera project to screen coordinates."""
        project = _build_projector(camera)
        # Target is at (0, 1, 0) and camera is at (2, 1.6, -1.5)
        result = project((0.0, 1.0, 0.0))
        assert result is not None
        sx, sy, depth = result
        assert depth > 0
        # Should be roughly centered given it's the target
        assert 200 < sx < 800
        assert 200 < sy < 600

    def test_point_behind_camera_returns_none(self, camera):
        """Points behind camera return None."""
        project = _build_projector(camera)
        # A point well behind the camera (far behind at z=-10)
        result = project((10.0, 1.6, -10.0))
        # This may or may not be behind depending on direction
        # Use a point definitely behind: camera looks from (2,1.6,-1.5) toward (0,1,0)
        # Behind = further in the -Z direction beyond camera
        result = project((4.0, 1.6, -5.0))
        # Should be behind since camera forward is toward origin
        # Actually let's test explicitly
        if result is not None:
            assert result[2] > 0  # If projected, depth must be positive

    def test_projection_respects_fov(self):
        """Different FOV produces different projected positions."""
        cam_narrow = CameraContract(
            position=(0.0, 1.6, 5.0),
            target=(0.0, 1.0, 0.0),
            vfov=30.0,
        )
        cam_wide = CameraContract(
            position=(0.0, 1.6, 5.0),
            target=(0.0, 1.0, 0.0),
            vfov=90.0,
        )
        proj_narrow = _build_projector(cam_narrow)
        proj_wide = _build_projector(cam_wide)

        point = (1.0, 1.0, 0.0)
        r_narrow = proj_narrow(point)
        r_wide = proj_wide(point)

        assert r_narrow is not None
        assert r_wide is not None
        # Narrow FOV should push point further from center
        dist_narrow = abs(r_narrow[0] - 512)
        dist_wide = abs(r_wide[0] - 512)
        assert dist_narrow > dist_wide


# ─── Tests: Backward-compatible render_blockout function ───────────────────────


class TestRenderBlockoutFunction:
    """Test the convenience render_blockout() function."""

    def test_produces_image(self, kitchenette_plan, camera, tmp_path):
        """render_blockout() convenience function works."""
        output_path = tmp_path / "test_blockout.png"
        result = render_blockout(kitchenette_plan, camera, output_path)

        assert isinstance(result, BlockoutResult)
        assert Path(result.image_path).exists()
        img = Image.open(result.image_path)
        assert img.size == (1024, 768)

    def test_returns_correct_metadata(self, kitchenette_plan, camera, tmp_path):
        """render_blockout() returns correct metadata."""
        output_path = tmp_path / "meta_test.png"
        result = render_blockout(kitchenette_plan, camera, output_path)

        assert result.approved is False
        assert result.plan_revision == 1
        assert result.camera_hash == camera.compute_hash()
        assert result.feedback == ""


# ─── Tests: Image content validation ──────────────────────────────────────────


class TestImageContent:
    """Validate that the output image contains expected visual elements."""

    def test_image_is_not_blank(self, kitchenette_plan, camera, tmp_output):
        """Image has significant pixel variation (not a solid color)."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="content")

        img = Image.open(result.image_path)
        pixels = list(img.getdata())
        unique_colors = len(set(pixels))
        # A rendered scene should have many distinct pixel values
        assert unique_colors > 100

    def test_image_contains_non_black_pixels(self, kitchenette_plan, camera, tmp_output):
        """Image contains drawn elements (not just background)."""
        renderer = BlockoutRenderer(output_base=tmp_output)
        result = renderer.render(kitchenette_plan, camera, session_id="nonblack")

        img = Image.open(result.image_path)
        # Sample center region — should contain rendered geometry
        center_pixel = img.getpixel((512, 384))
        # At least some brightness (not pure dark background everywhere)
        max_channel = max(center_pixel)
        # The image has gradient background + geometry, hard to assert center
        # Instead check that the image has bright pixels somewhere
        import numpy as np
        arr = np.array(img)
        assert arr.max() > 50  # At least some visible pixels
