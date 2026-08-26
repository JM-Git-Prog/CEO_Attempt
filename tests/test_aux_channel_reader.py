"""Unit tests for aux_channel_reader — deterministic direct-read unprojection consumer.

Validates that the reader correctly loads lossless aux-channel containers (EXR/npz),
unprojects masked pixels to 3D world coordinates using the inverse of the controlled-
camera projection, excludes np.inf pixels, and marks results as deterministic.

**Validates: Requirements 2.4, 3.1, 3.2, 3.5**
"""

from __future__ import annotations

import io
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.unified_pipeline.aux_channel_reader import (
    UnprojectionResult,
    _build_camera_basis,
    deterministic_unproject,
    load_aux_channels,
    unproject_cutout,
)
from src.unified_pipeline.models import CameraContract, SceneCanon


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def camera() -> CameraContract:
    """Standard CameraContract for testing."""
    return CameraContract(
        position=(2.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        aspect=1024.0 / 768.0,
        near=0.1,
        far=100.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_hash_test_reader",
    )


@pytest.fixture
def simple_camera() -> CameraContract:
    """Camera looking down -Z axis from origin for simpler math verification."""
    return CameraContract(
        position=(0.0, 0.0, 0.0),
        target=(0.0, 0.0, -1.0),
        up=(0.0, 1.0, 0.0),
        vfov=90.0,
        aspect=1.0,
        near=0.1,
        far=100.0,
        raster_width=100,
        raster_height=100,
        camera_hash="simple_cam",
    )


@pytest.fixture
def sample_depth_map() -> np.ndarray:
    """A 768x1024 float32 depth map with finite and inf values."""
    depth = np.full((768, 1024), 5.0, dtype=np.float32)
    # No geometry in corners
    depth[:50, :50] = np.inf
    depth[:50, 974:] = np.inf
    return depth


@pytest.fixture
def sample_instance_id_map() -> np.ndarray:
    """A 768x1024 int32 instance-ID map. 0 = background, 1+ = objects."""
    ids = np.zeros((768, 1024), dtype=np.int32)
    # Object 1 in center
    ids[200:400, 300:600] = 1
    # Object 2 in lower-right
    ids[500:700, 600:900] = 2
    return ids


def _write_npz_aux(
    aux_path: Path,
    depth_map: np.ndarray,
    instance_id_map: np.ndarray,
    camera_hash: str = "test_cam",
    plan_revision: int = 1,
) -> Path:
    """Write a synthetic npz aux container (same format as the writer fallback)."""
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        Z=depth_map.astype(np.float32),
        instance_id=instance_id_map.astype(np.float32),
        _provenance_camera_hash=np.array([camera_hash], dtype="U"),
        _provenance_plan_revision=np.array([plan_revision], dtype=np.int32),
    )
    aux_path.write_bytes(buf.getvalue())
    return aux_path


# ─── Tests: load_aux_channels ──────────────────────────────────────────────────


class TestLoadAuxChannels:
    """Tests for loading the lossless multi-channel container."""

    def test_loads_npz_format(self, tmp_path: Path, sample_depth_map, sample_instance_id_map):
        """Can load channels from npz fallback format."""
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, sample_depth_map, sample_instance_id_map)

        channels = load_aux_channels(aux_path)

        assert "Z" in channels
        assert "instance_id" in channels
        assert channels["Z"].dtype == np.float32
        assert channels["instance_id"].dtype == np.float32

    def test_depth_channel_values_preserved(self, tmp_path: Path, sample_depth_map, sample_instance_id_map):
        """Depth values round-trip losslessly through the container."""
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, sample_depth_map, sample_instance_id_map)

        channels = load_aux_channels(aux_path)
        np.testing.assert_array_equal(channels["Z"], sample_depth_map)

    def test_instance_id_values_preserved(self, tmp_path: Path, sample_depth_map, sample_instance_id_map):
        """Instance-ID values round-trip through the container (as float32)."""
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, sample_depth_map, sample_instance_id_map)

        channels = load_aux_channels(aux_path)
        recovered_ids = channels["instance_id"].astype(np.int32)
        np.testing.assert_array_equal(recovered_ids, sample_instance_id_map)

    def test_excludes_provenance_metadata(self, tmp_path: Path, sample_depth_map, sample_instance_id_map):
        """Provenance arrays (_provenance_*) are NOT included as channels."""
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, sample_depth_map, sample_instance_id_map)

        channels = load_aux_channels(aux_path)
        for name in channels:
            assert not name.startswith("_provenance")

    def test_file_not_found_raises(self, tmp_path: Path):
        """FileNotFoundError raised for missing aux container."""
        with pytest.raises(FileNotFoundError):
            load_aux_channels(tmp_path / "nonexistent.aux.exr")


# ─── Tests: unproject_cutout ───────────────────────────────────────────────────


class TestUnprojectCutout:
    """Tests for the low-level inverse projection function."""

    def test_empty_pixel_coords(self, camera):
        """Empty input returns empty (0, 3) array."""
        depth = np.full((768, 1024), 5.0, dtype=np.float32)
        coords = np.empty((0, 2), dtype=np.int32)

        result = unproject_cutout(coords, depth, camera)
        assert result.shape == (0, 3)

    def test_inf_depth_excluded(self, camera):
        """Pixels with np.inf depth produce no 3D points."""
        depth = np.full((768, 1024), np.inf, dtype=np.float32)
        coords = np.array([[512, 384], [100, 100]], dtype=np.int32)

        result = unproject_cutout(coords, depth, camera)
        assert result.shape == (0, 3)

    def test_finite_depth_produces_points(self, camera):
        """Pixels with finite depth produce valid 3D points."""
        depth = np.full((768, 1024), 5.0, dtype=np.float32)
        coords = np.array([[512, 384]], dtype=np.int32)

        result = unproject_cutout(coords, depth, camera)
        assert result.shape == (1, 3)
        assert np.all(np.isfinite(result))

    def test_result_is_deterministic(self, camera):
        """Same inputs produce identical outputs (no randomness)."""
        depth = np.full((768, 1024), 3.5, dtype=np.float32)
        coords = np.array([[200, 300], [500, 400]], dtype=np.int32)

        result1 = unproject_cutout(coords, depth, camera)
        result2 = unproject_cutout(coords, depth, camera)
        np.testing.assert_array_equal(result1, result2)

    def test_round_trip_project_unproject(self, simple_camera):
        """Project a 3D point → screen + depth → unproject → recover original."""
        # Simple camera: at origin, looking down -Z, vfov=90, 100x100 raster
        cam = simple_camera
        width = cam.raster_width
        height = cam.raster_height
        focal = (height / 2.0) / math.tan(math.radians(cam.vfov) / 2.0)

        # Build forward/right/up from the camera
        cam_pos, forward, right, up, focal_calc, w, h, near = _build_camera_basis(cam)
        assert abs(focal - focal_calc) < 1e-9

        # Choose a 3D test point in front of the camera
        test_point = np.array([1.0, 0.5, -3.0], dtype=np.float64)

        # Forward projection (same as _build_projector logic):
        relative = test_point - cam_pos
        depth = float(np.dot(relative, forward))
        sx = width / 2.0 + float(np.dot(relative, right)) * focal / depth
        sy = height / 2.0 - float(np.dot(relative, up)) * focal / depth

        # Write depth at the projected pixel into a depth buffer
        px = int(round(sx))
        py = int(round(sy))
        depth_buf = np.full((height, width), np.inf, dtype=np.float32)
        depth_buf[py, px] = float(depth)

        # Unproject
        coords = np.array([[px, py]], dtype=np.int32)
        recovered = unproject_cutout(coords, depth_buf, cam)

        assert recovered.shape == (1, 3)
        # Tolerance accounts for integer pixel rounding (sub-pixel precision lost)
        np.testing.assert_allclose(recovered[0], test_point, atol=0.05)

    def test_round_trip_multiple_points(self, simple_camera):
        """Multiple 3D points project → unproject round-trip within tolerance."""
        cam = simple_camera
        cam_pos, forward, right, up, focal, width, height, near = _build_camera_basis(cam)

        # Several test points at varying depths in front of camera
        test_points = np.array([
            [0.5, 0.2, -2.0],
            [-0.3, 0.1, -4.0],
            [0.0, 0.0, -1.5],
            [0.8, -0.3, -5.0],
        ], dtype=np.float64)

        depth_buf = np.full((height, width), np.inf, dtype=np.float32)
        pixel_coords_list = []

        for pt in test_points:
            relative = pt - cam_pos
            depth = float(np.dot(relative, forward))
            sx = width / 2.0 + float(np.dot(relative, right)) * focal / depth
            sy = height / 2.0 - float(np.dot(relative, up)) * focal / depth
            px = int(round(sx))
            py = int(round(sy))
            if 0 <= px < width and 0 <= py < height:
                depth_buf[py, px] = float(depth)
                pixel_coords_list.append([px, py])

        coords = np.array(pixel_coords_list, dtype=np.int32)
        recovered = unproject_cutout(coords, depth_buf, cam)

        # Each recovered point should match (within float32→float64 tolerance
        # and integer pixel rounding)
        assert recovered.shape[0] == len(pixel_coords_list)
        for i, pt in enumerate(test_points[: recovered.shape[0]]):
            np.testing.assert_allclose(recovered[i], pt, atol=0.1)


# ─── Tests: deterministic_unproject ────────────────────────────────────────────


class TestDeterministicUnproject:
    """Tests for the high-level deterministic unprojection consumer."""

    def test_result_marked_deterministic(self, tmp_path: Path, camera):
        """Result has deterministic=True always."""
        depth = np.full((768, 1024), 5.0, dtype=np.float32)
        ids = np.ones((768, 1024), dtype=np.int32)
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth, ids)

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[384, 512] = 1

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="Z",
            instance_id_channel="instance_id",
            camera_hash="cam_hash_test_reader",
            plan_revision=3,
        )

        result = deterministic_unproject(canon, camera, mask)
        assert result.deterministic is True
        assert result.camera_hash == "cam_hash_test_reader"
        assert result.plan_revision == 3

    def test_inf_pixels_excluded(self, tmp_path: Path, camera):
        """Pixels at np.inf depth are excluded from the result."""
        depth = np.full((768, 1024), np.inf, dtype=np.float32)
        ids = np.ones((768, 1024), dtype=np.int32)
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth, ids)

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[300:400, 400:600] = 1  # all these pixels have inf depth

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="Z",
            instance_id_channel="instance_id",
            camera_hash="cam_hash",
            plan_revision=1,
        )

        result = deterministic_unproject(canon, camera, mask)
        assert result.points_3d.shape[0] == 0
        assert result.instance_ids.shape[0] == 0
        assert result.pixel_coords.shape[0] == 0
        assert result.deterministic is True

    def test_instance_ids_read_correctly(self, tmp_path: Path, camera):
        """Instance IDs are read from the aux container at the masked pixel coords."""
        depth = np.full((768, 1024), 5.0, dtype=np.float32)
        ids = np.zeros((768, 1024), dtype=np.int32)
        ids[380:390, 510:520] = 7  # specific object region

        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth, ids)

        # Mask exactly the region with instance_id=7
        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[385, 515] = 1

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="Z",
            instance_id_channel="instance_id",
            camera_hash="cam",
            plan_revision=1,
        )

        result = deterministic_unproject(canon, camera, mask)
        assert result.points_3d.shape[0] == 1
        assert result.instance_ids[0] == 7

    def test_empty_mask_returns_empty(self, tmp_path: Path, camera):
        """All-zero mask produces empty result."""
        depth = np.full((768, 1024), 5.0, dtype=np.float32)
        ids = np.ones((768, 1024), dtype=np.int32)
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth, ids)

        mask = np.zeros((768, 1024), dtype=np.uint8)

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="Z",
            instance_id_channel="instance_id",
            camera_hash="cam",
            plan_revision=1,
        )

        result = deterministic_unproject(canon, camera, mask)
        assert result.points_3d.shape == (0, 3)
        assert result.deterministic is True

    def test_raises_on_empty_aux_path(self, camera):
        """ValueError raised when canon.aux_channel_path is empty."""
        canon = SceneCanon(aux_channel_path="", depth_channel="Z")
        mask = np.ones((768, 1024), dtype=np.uint8)

        with pytest.raises(ValueError, match="aux_channel_path is empty"):
            deterministic_unproject(canon, camera, mask)

    def test_raises_on_missing_depth_channel(self, tmp_path: Path, camera):
        """ValueError raised when depth channel is not in the container."""
        depth = np.full((10, 10), 5.0, dtype=np.float32)
        ids = np.ones((10, 10), dtype=np.int32)
        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth, ids)

        mask = np.ones((10, 10), dtype=np.uint8)

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="nonexistent_channel",
            instance_id_channel="instance_id",
            camera_hash="cam",
            plan_revision=1,
        )

        with pytest.raises(ValueError, match="nonexistent_channel"):
            deterministic_unproject(canon, camera, mask)

    def test_full_round_trip_via_aux_container(self, tmp_path: Path, simple_camera):
        """Full pipeline: project 3D point → write aux → deterministic_unproject → recover.

        This validates the entire bug-fix flow: depth is emitted as a real lossless
        channel, read back directly, and used for deterministic unprojection.
        """
        cam = simple_camera
        cam_pos, forward, right, up, focal, width, height, near = _build_camera_basis(cam)

        # Known 3D point
        test_point = np.array([0.5, 0.3, -2.5], dtype=np.float64)

        # Forward projection
        relative = test_point - cam_pos
        depth = float(np.dot(relative, forward))
        sx = width / 2.0 + float(np.dot(relative, right)) * focal / depth
        sy = height / 2.0 - float(np.dot(relative, up)) * focal / depth
        px = int(round(sx))
        py = int(round(sy))

        # Build aux container with depth at projected pixel
        depth_buf = np.full((height, width), np.inf, dtype=np.float32)
        depth_buf[py, px] = float(depth)
        ids = np.zeros((height, width), dtype=np.int32)
        ids[py, px] = 3  # object 3 at this pixel

        aux_path = tmp_path / "canon_v1.aux.exr"
        _write_npz_aux(aux_path, depth_buf, ids)

        # Build mask at that pixel
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[py, px] = 1

        canon = SceneCanon(
            aux_channel_path=str(aux_path),
            depth_channel="Z",
            instance_id_channel="instance_id",
            camera_hash="simple_cam",
            plan_revision=2,
        )

        result = deterministic_unproject(canon, cam, mask)

        # Verify round-trip
        assert result.deterministic is True
        assert result.points_3d.shape == (1, 3)
        np.testing.assert_allclose(result.points_3d[0], test_point, atol=1e-4)
        assert result.instance_ids[0] == 3
        assert result.camera_hash == "simple_cam"
        assert result.plan_revision == 2


# ─── Tests: UnprojectionResult dataclass ───────────────────────────────────────


class TestUnprojectionResult:
    """Tests for the UnprojectionResult frozen dataclass."""

    def test_frozen(self):
        """UnprojectionResult is immutable."""
        result = UnprojectionResult(
            points_3d=np.zeros((1, 3)),
            instance_ids=np.zeros((1,), dtype=np.int32),
            pixel_coords=np.zeros((1, 2), dtype=np.int32),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.deterministic = False  # type: ignore[misc]

    def test_defaults(self):
        """Default values are correct."""
        result = UnprojectionResult(
            points_3d=np.zeros((0, 3)),
            instance_ids=np.zeros((0,), dtype=np.int32),
            pixel_coords=np.zeros((0, 2), dtype=np.int32),
        )
        assert result.camera_hash == ""
        assert result.plan_revision == 1
        assert result.deterministic is True
