"""Tests for depth_backprojector — back-projection with exact known cameras."""

from __future__ import annotations

import numpy as np
import pytest

from src.unified_pipeline.depth_backprojector import DepthBackprojector


def _identity_intrinsic(width: int, height: int, focal: float = 500.0) -> np.ndarray:
    """Standard pinhole K with principal point at the image center."""
    return np.array(
        [
            [focal, 0.0, width / 2.0],
            [0.0, focal, height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def test_backproject_flat_wall():
    """Constant depth from an identity camera -> all points on one plane.

    With extrinsic = identity, R = I and t = 0, so P_world = P_camera. Camera
    coordinates put depth along +Z here (K_inv gives z=1 rays scaled by d), so
    every point shares the same Z = 3.0 within tolerance.
    """
    bp = DepthBackprojector()
    width, height = 16, 12
    depth = np.full((height, width), 3.0, dtype=np.float32)
    intrinsic = _identity_intrinsic(width, height)
    extrinsic = np.eye(4, dtype=np.float64)

    points, colors = bp.backproject(depth, intrinsic, extrinsic)

    assert colors is None
    # Every valid pixel produced a point.
    assert points.shape[0] == width * height
    assert points.shape[1] == 3

    # All points share the same plane distance along the ray-z axis.
    plane = points[:, 2]
    assert np.allclose(plane, plane[0], atol=1e-6)
    assert np.isclose(plane[0], 3.0, atol=1e-6)


def test_filter_invalid():
    """NaN, inf, below-min, and above-max depths are rejected."""
    bp = DepthBackprojector()
    width, height = 2, 2
    depth = np.array(
        [
            [np.nan, np.inf],
            [0.05, 20.0],  # below min_depth, above max_depth
        ],
        dtype=np.float32,
    )
    intrinsic = _identity_intrinsic(width, height)
    extrinsic = np.eye(4, dtype=np.float64)

    points, _ = bp.backproject(
        depth, intrinsic, extrinsic, min_depth=0.1, max_depth=15.0
    )
    assert points.shape[0] == 0

    # Now make one pixel valid and confirm exactly one survives.
    depth[0, 0] = 5.0
    points, _ = bp.backproject(
        depth, intrinsic, extrinsic, min_depth=0.1, max_depth=15.0
    )
    assert points.shape[0] == 1


def test_backproject_colors():
    """Returned colors match valid-pixel count with shape (N, 3) uint8."""
    bp = DepthBackprojector()
    width, height = 8, 6
    depth = np.full((height, width), 2.0, dtype=np.float32)
    intrinsic = _identity_intrinsic(width, height)
    extrinsic = np.eye(4, dtype=np.float64)
    rgb = np.random.randint(0, 256, size=(height, width, 3), dtype=np.uint8)

    points, colors = bp.backproject(depth, intrinsic, extrinsic, rgb_image=rgb)

    assert colors is not None
    assert colors.shape == (points.shape[0], 3)
    assert colors.dtype == np.uint8
    assert points.shape[0] == width * height


def test_fuse_deduplicates():
    """Two identical clouds of the same 100 points fuse to ~100 points."""
    bp = DepthBackprojector()
    rng = np.random.default_rng(42)
    # Spread points well beyond the merge radius so each is its own cell.
    cloud = rng.uniform(-5.0, 5.0, size=(100, 3)).astype(np.float64)

    fused, colors = bp.fuse([cloud, cloud.copy()], [None, None], merge_radius_m=0.02)

    assert colors is None
    # Duplicates collapse; count is at most 100 and near it.
    assert fused.shape[0] <= 100
    assert fused.shape[0] >= 95


def test_fuse_preserves_distinct():
    """Well-separated points (>merge_radius apart) are all preserved."""
    bp = DepthBackprojector()
    merge_radius = 0.02
    cloud_a = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
    cloud_b = np.array([[0.0, 1.0, 0.0], [1.0, 1.0, 0.0]], dtype=np.float64)

    fused, _ = bp.fuse([cloud_a, cloud_b], [None, None], merge_radius_m=merge_radius)

    assert fused.shape[0] == 4


def test_export_ply_valid(tmp_path):
    """Exporting a small cloud writes a non-empty file that exists."""
    bp = DepthBackprojector()
    points = np.array(
        [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 0.0, 1.0]], dtype=np.float64
    )
    out_path = tmp_path / "cloud.ply"

    result = bp.export_ply(points, None, out_path)

    assert result.exists()
    assert result.stat().st_size > 0


def test_backproject_vectorized_shape():
    """A 100x100 all-valid depth map returns (10000, 3)."""
    bp = DepthBackprojector()
    width, height = 100, 100
    depth = np.full((height, width), 4.0, dtype=np.float32)
    intrinsic = _identity_intrinsic(width, height)
    extrinsic = np.eye(4, dtype=np.float64)

    points, colors = bp.backproject(depth, intrinsic, extrinsic)

    assert points.shape == (10000, 3)
    assert colors is None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
