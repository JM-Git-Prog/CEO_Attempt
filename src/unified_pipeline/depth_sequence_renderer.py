"""Depth sequence renderer for the Unified World Pipeline.

Renders MetricPlan geometry — the spatial authority — into per-camera float32
depth maps for ControlNet depth conditioning. The depth here is AUTHORED from
the Plan, not estimated: every value comes from rasterizing the declared
MetricPlan geometry through a fully controlled CameraContract, reusing the
existing ``render_controlled_depth`` z-render. It is never monocular depth
estimation and carries no independent spatial authority.

For each camera in a CaptureManifest this module produces one DepthRender whose
``depth_map`` is a float32 ndarray of shape (height, width) with ``np.inf``
where no geometry is hit. These maps drive geometry-conditioned generation
downstream; MetricPlan remains the sole spatial authority.

Requirements: 2.1, 3.3, 3.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.unified_pipeline.blockout_renderer import render_controlled_depth
from src.unified_pipeline.models import MetricPlan

logger = logging.getLogger(__name__)


@dataclass
class DepthRender:
    """A single authored depth map for one camera.

    Attributes:
        depth_map: float32 ndarray of shape (H, W); ``np.inf`` where no geometry
            is hit. Authored from MetricPlan geometry, not estimated.
        camera_hash: Stable hash of the source camera's framing + intrinsics.
        camera_label: Human-readable label of the source camera.
        plan_revision: MetricPlan revision the depth was rendered against.
        path: Filesystem path to the saved ``.npy`` file (set by :meth:`save`).
    """

    depth_map: np.ndarray
    camera_hash: str
    camera_label: str
    plan_revision: int
    path: str = ""


class DepthSequenceRenderer:
    """Renders MetricPlan geometry into a depth map at each planned camera.

    Reuses :func:`render_controlled_depth` for all projection/rasterization —
    this class only orchestrates per-camera rendering and packaging into
    :class:`DepthRender` records. MetricPlan is the spatial authority; the
    produced depth is a geometry echo for ControlNet conditioning.
    """

    def __init__(self, metric_plan: MetricPlan) -> None:
        """Initialize with the MetricPlan whose geometry will be rendered.

        Args:
            metric_plan: Validated MetricPlan providing the spatial authority.
        """
        self._plan = metric_plan

    def render_one(self, camera) -> DepthRender:
        """Render depth for one PlannedCamera.

        Calls ``render_controlled_depth(self._plan, camera.to_camera_contract())``
        and wraps the resulting depth map in a :class:`DepthRender`, carrying the
        camera's hash and label for provenance.

        Args:
            camera: A PlannedCamera exposing ``to_camera_contract()``, ``hash``,
                and ``label``.

        Returns:
            DepthRender with the authored float32 depth map and provenance.
        """
        contract = camera.to_camera_contract()
        controlled = render_controlled_depth(self._plan, contract)

        depth_map = np.asarray(controlled.depth_map, dtype=np.float32)
        camera_label = getattr(camera, "label", "")
        camera_hash = getattr(camera, "hash", "") or controlled.camera_hash

        logger.debug(
            "Rendered depth for camera %s (hash=%s) shape=%s revision=%s",
            camera_label,
            camera_hash,
            depth_map.shape,
            controlled.plan_revision,
        )

        return DepthRender(
            depth_map=depth_map,
            camera_hash=camera_hash,
            camera_label=camera_label,
            plan_revision=controlled.plan_revision,
        )

    def render_all(self, manifest) -> list[DepthRender]:
        """Render depth for every camera in a CaptureManifest.

        Args:
            manifest: A CaptureManifest exposing ``cameras`` (list of
                PlannedCamera).

        Returns:
            One DepthRender per camera, in manifest order.
        """
        renders = [self.render_one(camera) for camera in manifest.cameras]
        logger.info("Rendered %d depth map(s) from manifest", len(renders))
        return renders

    def save(self, render: DepthRender, output_dir) -> str:
        """Save a DepthRender's depth map as a float32 ``.npy`` file.

        The file is named ``depth_{camera_label}.npy`` inside ``output_dir``,
        which is created if it does not exist. Updates ``render.path`` in place.

        Args:
            render: The DepthRender whose ``depth_map`` will be persisted.
            output_dir: Directory to write into (str or Path).

        Returns:
            The path string of the written ``.npy`` file.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"depth_{render.camera_label}.npy"
        depth_map = np.asarray(render.depth_map, dtype=np.float32)
        np.save(str(out_path), depth_map)

        render.path = str(out_path)
        logger.info("Saved depth map for %s -> %s", render.camera_label, render.path)
        return render.path
