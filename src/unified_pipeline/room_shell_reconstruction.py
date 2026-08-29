"""Room-shell reconstruction from the capture manifest (integration seam).

Wires the capture-planning modules into the mesh builder. Given a MetricPlan
and a CaptureManifest (exact known cameras), this:

1. Renders metric depth from MetricPlan at each manifest camera
   (DepthSequenceRenderer — the geometry is AUTHORED, not estimated).
2. Back-projects each depth map into world space using the exact known K/R/t
   (DepthBackprojector — no pose estimation).
3. Fuses the per-view clouds and reconstructs a room-shell mesh
   (VolumetricReconstructor).

If a per-view DA3 depth map is supplied (from a live generation run), the
GeometryValidationGate is used to confirm the generated image followed the
conditioning before that view contributes to the cloud. Without DA3 depth
(no GPU / no generation), reconstruction proceeds from the authored MetricPlan
depth directly, which is exact.

Returns None on any failure so callers fall back to the parametric room shell
(Requirement 6.7). MetricPlan remains the sole spatial authority throughout.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Minimum fused points required to attempt reconstruction.
MIN_FUSED_POINTS = 500


def reconstruct_room_shell(
    metric_plan: Any,
    capture_manifest: Any,
    output_dir: Path,
    *,
    da3_depths: dict[str, np.ndarray] | None = None,
    room_center: tuple[float, float, float] | None = None,
) -> Path | None:
    """Reconstruct a room-shell GLB from the capture manifest.

    Args:
        metric_plan: The MetricPlan (spatial authority) to render depth from.
        capture_manifest: A CaptureManifest with PlannedCamera records that
            carry exact intrinsic/extrinsic matrices.
        output_dir: Directory to write the reconstructed ``room_shell.glb``.
        da3_depths: Optional map of camera_label -> DA3 estimated depth map.
            When present, each view is validated (generated image must follow
            the conditioning) before contributing to the cloud.
        room_center: Optional interior point for inward normal orientation.
            Defaults to the room center derived from MetricPlan dimensions.

    Returns:
        Path to the reconstructed GLB, or ``None`` if reconstruction was not
        possible (caller should fall back to the parametric shell).
    """
    if capture_manifest is None:
        logger.info("room_shell_reconstruction: no capture manifest; skipping")
        return None

    try:
        from src.unified_pipeline.depth_backprojector import DepthBackprojector
        from src.unified_pipeline.depth_sequence_renderer import (
            DepthSequenceRenderer,
        )
        from src.unified_pipeline.geometry_validation_gate import (
            GeometryValidationGate,
        )
        from src.unified_pipeline.volumetric_reconstructor import (
            VolumetricReconstructor,
        )
    except ImportError as exc:
        logger.warning("room_shell_reconstruction: modules unavailable (%s)", exc)
        return None

    try:
        renderer = DepthSequenceRenderer(metric_plan)
        backprojector = DepthBackprojector()
        gate = GeometryValidationGate()

        clouds: list[np.ndarray] = []
        cameras = getattr(capture_manifest, "cameras", [])
        if not cameras:
            logger.info("room_shell_reconstruction: manifest has no cameras")
            return None

        for camera in cameras:
            render = renderer.render_one(camera)
            conditioning = render.depth_map  # metric, np.inf = no geometry

            # If DA3 depth is available for this view, validate conditioning held.
            depth_for_backproj = conditioning
            if da3_depths is not None:
                estimated = da3_depths.get(camera.label)
                if estimated is not None:
                    result = gate.compare(estimated, conditioning)
                    if not result.passed:
                        logger.info(
                            "room_shell_reconstruction: view %s failed gate "
                            "(%s); excluding from cloud",
                            camera.label,
                            result.failure_reason,
                        )
                        continue

            # Replace np.inf (no geometry) with 0 so it is filtered by min_depth.
            depth_clean = np.where(
                np.isfinite(depth_for_backproj), depth_for_backproj, 0.0
            ).astype(np.float32)

            points, _ = backprojector.backproject(
                depth_clean,
                camera.intrinsic_array(),
                camera.extrinsic_array(),
                min_depth=0.1,
                max_depth=15.0,
            )
            if points.shape[0] > 0:
                clouds.append(points)

        if not clouds:
            logger.info("room_shell_reconstruction: no valid view clouds")
            return None

        fused, _ = backprojector.fuse(clouds, [None] * len(clouds), merge_radius_m=0.02)
        if fused.shape[0] < MIN_FUSED_POINTS:
            logger.info(
                "room_shell_reconstruction: only %d fused points (< %d); "
                "falling back to parametric shell",
                fused.shape[0],
                MIN_FUSED_POINTS,
            )
            return None

        if room_center is None:
            dims = getattr(metric_plan, "room_dimensions", (4.0, 3.0, 2.7))
            room_center = (0.0, dims[2] / 2.0, 0.0)

        reconstructor = VolumetricReconstructor()
        mesh = reconstructor.reconstruct(
            fused, method="poisson", room_center=room_center
        )
        if mesh is None:
            logger.info("room_shell_reconstruction: reconstructor returned None")
            return None

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        shell_path = output_dir / "room_shell.glb"
        reconstructor.export_glb(mesh, shell_path)
        logger.info(
            "room_shell_reconstruction: reconstructed shell from %d points -> %s",
            fused.shape[0],
            shell_path,
        )
        return shell_path

    except Exception as exc:  # noqa: BLE001 - always fall back on failure
        logger.warning(
            "room_shell_reconstruction failed (%s); falling back to parametric shell",
            exc,
        )
        return None
