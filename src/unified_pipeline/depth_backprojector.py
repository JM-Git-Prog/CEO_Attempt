"""Back-projects depth into 3D using exact known camera matrices — no pose estimation. Authority comes from the known cameras (declared by MetricPlan), not from the depth estimator.

This module consumes depth maps plus the EXACT intrinsic (K) and extrinsic
(world-to-camera) matrices produced by ``capture_planner.PlannedCamera`` and
lifts each valid pixel into world space. Multiple per-view clouds are then
fused (voxel-grid deduplicated) into a single mesh-ready point cloud that can
be exported to PLY via trimesh.

Convention (matching capture_planner): right-handed, camera looks down -Z.
The extrinsic maps ``p_camera = R @ p_world + t`` where ``R = extrinsic[:3, :3]``
and ``t = extrinsic[:3, 3]``. Inverting gives ``p_world = R.T @ (p_camera - t)``.
The intrinsic K is a standard pinhole ``[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]``.

No pose is ever estimated here: the spatial authority is the declared camera,
never the depth estimator. Depth only supplies per-ray scale.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


class DepthBackprojector:
    """Lift depth maps into world-space point clouds using known cameras.

    Every method is stateless with respect to instance data; the class exists
    to group the back-projection / fusion / export operations behind one API.
    """

    def backproject(
        self,
        depth_map: np.ndarray,
        intrinsic: np.ndarray,
        extrinsic: np.ndarray,
        rgb_image: np.ndarray | None = None,
        min_depth: float = 0.1,
        max_depth: float = 15.0,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Back-project a float32 depth map (H, W) to world points.

        For each valid pixel (u, v) with depth d::

            ray_camera = K_inv @ [u, v, 1]^T
            P_camera   = ray_camera * d
            P_world    = R.T @ (P_camera - t)

        where ``R = extrinsic[:3, :3]`` and ``t = extrinsic[:3, 3]``.

        Fully vectorized (no per-pixel Python loop). Pixels are rejected when
        depth is ``<= min_depth``, ``> max_depth``, NaN, or inf.

        Args:
            depth_map: (H, W) array of per-pixel depth along the camera ray's
                scale. Cast to float64 internally.
            intrinsic: 3x3 pinhole camera matrix K.
            extrinsic: 4x4 world-to-camera matrix.
            rgb_image: Optional (H, W, 3) image; when given, per-point colors
                are sampled at each valid pixel.
            min_depth: Minimum accepted depth (exclusive lower bound).
            max_depth: Maximum accepted depth (inclusive upper bound).

        Returns:
            Tuple of (Nx3 float64 world points, Nx3 uint8 colors) where colors
            is ``None`` if ``rgb_image`` is ``None``.
        """
        depth = np.asarray(depth_map, dtype=np.float64)
        if depth.ndim != 2:
            raise ValueError(
                f"depth_map must be 2D (H, W); got shape {depth.shape}"
            )

        height, width = depth.shape
        k = np.asarray(intrinsic, dtype=np.float64)
        ext = np.asarray(extrinsic, dtype=np.float64)
        if k.shape != (3, 3):
            raise ValueError(f"intrinsic must be 3x3; got {k.shape}")
        if ext.shape != (4, 4):
            raise ValueError(f"extrinsic must be 4x4; got {ext.shape}")

        rotation = ext[:3, :3]
        translation = ext[:3, 3]

        # Validity mask: finite, positive, within [min_depth, max_depth].
        valid = (
            np.isfinite(depth)
            & (depth > min_depth)
            & (depth <= max_depth)
        )
        if not np.any(valid):
            logger.debug("backproject: no valid pixels after filtering")
            empty_pts = np.empty((0, 3), dtype=np.float64)
            empty_colors = (
                np.empty((0, 3), dtype=np.uint8) if rgb_image is not None else None
            )
            return empty_pts, empty_colors

        # Pixel grid. u -> column (x), v -> row (y).
        us, vs = np.meshgrid(
            np.arange(width, dtype=np.float64),
            np.arange(height, dtype=np.float64),
        )
        u_valid = us[valid]
        v_valid = vs[valid]
        d_valid = depth[valid]

        # Homogeneous pixel coordinates -> camera rays via K_inv.
        k_inv = np.linalg.inv(k)
        ones = np.ones_like(u_valid)
        pixels_h = np.stack([u_valid, v_valid, ones], axis=0)  # (3, N)
        rays_camera = k_inv @ pixels_h  # (3, N)

        # Scale each ray by its depth to get camera-space points.
        points_camera = rays_camera * d_valid[np.newaxis, :]  # (3, N)

        # World = R.T @ (P_camera - t).
        points_world = rotation.T @ (points_camera - translation[:, np.newaxis])
        points_world = points_world.T  # (N, 3)

        colors: np.ndarray | None = None
        if rgb_image is not None:
            rgb = np.asarray(rgb_image)
            if rgb.ndim != 3 or rgb.shape[2] < 3:
                raise ValueError(
                    f"rgb_image must be (H, W, 3+); got shape {rgb.shape}"
                )
            rows = v_valid.astype(np.intp)
            cols = u_valid.astype(np.intp)
            colors = rgb[rows, cols, :3].astype(np.uint8)

        logger.debug(
            "backproject: %d/%d pixels valid -> %d world points",
            int(valid.sum()),
            height * width,
            points_world.shape[0],
        )
        return points_world, colors

    def fuse(
        self,
        clouds: list[np.ndarray],
        colors: list[np.ndarray | None],
        merge_radius_m: float = 0.02,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Merge multiple point clouds, deduplicating nearby points.

        Deduplication is a voxel-grid downsample: points are rounded onto a
        grid of cell size ``merge_radius_m`` and one representative point is
        kept per occupied cell.

        Args:
            clouds: List of (Ni, 3) point arrays.
            colors: Parallel list of (Ni, 3) color arrays (or ``None`` each).
            merge_radius_m: Grid cell size used for deduplication (meters).

        Returns:
            Tuple of (Mx3 fused points, Mx3 colors) where colors is ``None`` if
            no input cloud carried colors.
        """
        non_empty = [c for c in clouds if c is not None and len(c) > 0]
        if not non_empty:
            logger.debug("fuse: no input points")
            return np.empty((0, 3), dtype=np.float64), None

        all_points = np.vstack(
            [np.asarray(c, dtype=np.float64).reshape(-1, 3) for c in non_empty]
        )

        # Colors are usable only if every non-empty cloud provided them.
        color_parts: list[np.ndarray] = []
        colors_usable = True
        for cloud, color in zip(clouds, colors):
            if cloud is None or len(cloud) == 0:
                continue
            if color is None:
                colors_usable = False
                break
            color_parts.append(np.asarray(color, dtype=np.uint8).reshape(-1, 3))

        all_colors: np.ndarray | None = None
        if colors_usable and color_parts:
            all_colors = np.vstack(color_parts)
            if all_colors.shape[0] != all_points.shape[0]:
                logger.warning(
                    "fuse: color/point count mismatch (%d vs %d); dropping colors",
                    all_colors.shape[0],
                    all_points.shape[0],
                )
                all_colors = None

        if merge_radius_m <= 0:
            return all_points, all_colors

        # Voxel-grid dedup: round to grid, keep first point per unique cell.
        voxel_indices = np.floor(all_points / merge_radius_m).astype(np.int64)
        _, unique_idx = np.unique(voxel_indices, axis=0, return_index=True)
        unique_idx = np.sort(unique_idx)

        fused_points = all_points[unique_idx]
        fused_colors = all_colors[unique_idx] if all_colors is not None else None

        logger.debug(
            "fuse: %d points -> %d after voxel dedup (radius=%.4f m)",
            all_points.shape[0],
            fused_points.shape[0],
            merge_radius_m,
        )
        return fused_points, fused_colors

    def export_ply(
        self,
        points: np.ndarray,
        colors: np.ndarray | None,
        output_path,
    ) -> Path:
        """Export a point cloud as a PLY file via ``trimesh.PointCloud``.

        Args:
            points: (N, 3) world points.
            colors: Optional (N, 3) uint8 colors.
            output_path: Destination path (str or pathlib.Path).

        Returns:
            The output path as a ``pathlib.Path``.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if colors is not None:
            cloud = trimesh.PointCloud(
                vertices=pts, colors=np.asarray(colors, dtype=np.uint8).reshape(-1, 3)
            )
        else:
            cloud = trimesh.PointCloud(vertices=pts)

        cloud.export(str(out))
        logger.info("export_ply: wrote %d points to %s", pts.shape[0], out)
        return out
