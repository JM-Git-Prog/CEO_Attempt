"""Deterministic direct-read unprojection consumer for aux-channel containers.

Reads depth + instance-ID directly from the lossless multi-channel container
(OpenEXR or npz fallback) emitted at generation time, and unprojects each
masked pixel to 3D world coordinates using the inverse of the controlled-camera
projection from _build_projector.

This is ADDITIVE — it does NOT modify mesh_generators.prepare_generator_input
(composite-on-white / hidden-RGB-discard) or object_isolator.apply_mask_to_image
(instance-ID / RGBA alpha emission). Those paths remain untouched.

Requirements: 2.4, 3.1, 3.2, 3.5
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src.unified_pipeline.models import CameraContract, SceneCanon

logger = logging.getLogger(__name__)


# ─── Result Type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UnprojectionResult:
    """Result of deterministic unprojection from direct channel reads.

    All points come from lossless aux-channel depth + instance-ID, never from
    monocular estimation or visible-pixel smuggling.

    Attributes:
        points_3d: (N, 3) float64 world coordinates.
        instance_ids: (N,) int32 instance ID per point.
        pixel_coords: (N, 2) int32 pixel (x, y) coordinates.
        camera_hash: Provenance camera hash from SceneCanon.
        plan_revision: Provenance plan revision from SceneCanon.
        deterministic: Always True for the direct-read path.
    """

    points_3d: np.ndarray  # (N, 3) float64 world coords
    instance_ids: np.ndarray  # (N,) int32
    pixel_coords: np.ndarray  # (N, 2) int32 pixel x, y
    camera_hash: str = ""
    plan_revision: int = 1
    deterministic: bool = True  # always True for direct-read path


# ─── Aux Channel Loading ───────────────────────────────────────────────────────


def load_aux_channels(aux_path: Path) -> dict[str, np.ndarray]:
    """Load the lossless multi-channel container (OpenEXR or npz fallback).

    Returns a dict mapping channel name to float32 ndarray. Handles both
    EXR (via OpenEXR library) and npz formats transparently.

    Args:
        aux_path: Path to the aux container file (.aux.exr).

    Returns:
        Dict mapping channel name (e.g., "Z", "instance_id") to float32 ndarray.

    Raises:
        FileNotFoundError: If aux_path does not exist.
        ValueError: If the file cannot be read as either EXR or npz.
    """
    if not aux_path.exists():
        raise FileNotFoundError(f"Aux channel container not found: {aux_path}")

    # Try OpenEXR first
    try:
        return _load_exr_channels(aux_path)
    except (ImportError, Exception) as exr_err:
        logger.debug("EXR load failed (%s), trying npz fallback", exr_err)

    # Fallback: try numpy archive
    try:
        return _load_npz_channels(aux_path)
    except Exception as npz_err:
        raise ValueError(
            f"Cannot load aux channels from {aux_path}: "
            f"EXR failed ({exr_err}), npz failed ({npz_err})"
        ) from npz_err


def _load_exr_channels(aux_path: Path) -> dict[str, np.ndarray]:
    """Load channels from an OpenEXR file.

    Returns dict mapping channel name to float32 ndarray.
    """
    import OpenEXR  # type: ignore[import]
    import Imath  # type: ignore[import]

    exr_file = OpenEXR.InputFile(str(aux_path))
    header = exr_file.header()

    dw = header["dataWindow"]
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1

    channels: dict[str, np.ndarray] = {}
    pt = Imath.PixelType(Imath.PixelType.FLOAT)

    for name in header["channels"]:
        # Skip provenance metadata channels
        if name.startswith("_provenance"):
            continue
        raw = exr_file.channel(name, pt)
        arr = np.frombuffer(raw, dtype=np.float32).reshape((height, width))
        channels[name] = arr.copy()

    exr_file.close()
    return channels


def _load_npz_channels(aux_path: Path) -> dict[str, np.ndarray]:
    """Load channels from a numpy .npz archive (fallback format).

    Returns dict mapping channel name to float32 ndarray.
    """
    import io as _io

    data = np.load(_io.BytesIO(aux_path.read_bytes()), allow_pickle=False)
    channels: dict[str, np.ndarray] = {}
    for name in data.files:
        # Skip provenance metadata arrays
        if name.startswith("_provenance"):
            continue
        arr = data[name]
        channels[name] = arr.astype(np.float32)
    return channels


# ─── Inverse Projection (screen → world) ──────────────────────────────────────


def _build_camera_basis(camera: CameraContract):
    """Build camera basis vectors and focal length from CameraContract.

    Returns (cam_pos, forward, right, up, focal, width, height, near).
    """
    cam_pos = np.array(camera.position, dtype=np.float64)
    cam_target = np.array(camera.target, dtype=np.float64)
    cam_up = np.array(camera.up, dtype=np.float64)

    forward = cam_target - cam_pos
    forward_len = np.linalg.norm(forward)
    if forward_len < 1e-9:
        forward = np.array([0.0, 0.0, -1.0])
    else:
        forward = forward / forward_len

    right = np.cross(forward, cam_up)
    right_len = np.linalg.norm(right)
    if right_len < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / right_len

    up = np.cross(right, forward)

    width = camera.raster_width
    height = camera.raster_height
    focal = (height / 2.0) / math.tan(math.radians(camera.vfov) / 2.0)
    near = camera.near

    return cam_pos, forward, right, up, focal, width, height, near


def unproject_cutout(
    pixel_coords: np.ndarray,
    depth_channel: np.ndarray,
    camera: CameraContract,
) -> np.ndarray:
    """Unproject pixel coordinates to 3D world coordinates using aux-channel depth.

    Given pixel coordinates (x, y) from a cutout and the depth channel from the
    aux container, reads depth per pixel and computes the inverse of the
    controlled-camera projection to recover 3D world coordinates.

    The inverse projection from (screen_x, screen_y, depth) -> world:
        relative_right = (sx - width/2) * depth / focal
        relative_up = (height/2 - sy) * depth / focal
        world_point = cam_pos + depth*forward + relative_right*right + relative_up*up

    Args:
        pixel_coords: (N, 2) int32 array of (x, y) pixel coordinates.
        depth_channel: (height, width) float32 depth buffer from aux container.
            np.inf values indicate no geometry.
        camera: CameraContract defining the projection parameters.

    Returns:
        (M, 3) float64 array of world coordinates for pixels with finite depth.
        M <= N because pixels with np.inf depth are excluded.

    Note:
        Use deterministic_unproject() for the full pipeline including instance-ID
        lookup and provenance binding.
    """
    if pixel_coords.size == 0:
        return np.empty((0, 3), dtype=np.float64)

    cam_pos, forward, right, up, focal, width, height, near = _build_camera_basis(camera)

    # Extract depth at each pixel coordinate
    xs = pixel_coords[:, 0].astype(int)
    ys = pixel_coords[:, 1].astype(int)

    # Clip to valid raster bounds
    xs_clipped = np.clip(xs, 0, depth_channel.shape[1] - 1)
    ys_clipped = np.clip(ys, 0, depth_channel.shape[0] - 1)

    depths = depth_channel[ys_clipped, xs_clipped].astype(np.float64)

    # Filter out inf (no geometry) and values at/below near plane
    valid_mask = np.isfinite(depths) & (depths > near)

    if not np.any(valid_mask):
        return np.empty((0, 3), dtype=np.float64)

    valid_xs = xs[valid_mask].astype(np.float64)
    valid_ys = ys[valid_mask].astype(np.float64)
    valid_depths = depths[valid_mask]

    # Inverse projection:
    # sx = width/2 + dot(relative, right) * focal / depth
    # sy = height/2 - dot(relative, up) * focal / depth
    # Therefore:
    #   relative_right_component = (sx - width/2) * depth / focal
    #   relative_up_component = (height/2 - sy) * depth / focal
    #   world = cam_pos + depth*forward + relative_right*right + relative_up*up
    relative_right = (valid_xs - width / 2.0) * valid_depths / focal
    relative_up = (height / 2.0 - valid_ys) * valid_depths / focal

    # Vectorized world coordinate computation
    # world_point = cam_pos + depth*forward + relative_right*right + relative_up*up
    points_3d = (
        cam_pos[np.newaxis, :]
        + valid_depths[:, np.newaxis] * forward[np.newaxis, :]
        + relative_right[:, np.newaxis] * right[np.newaxis, :]
        + relative_up[:, np.newaxis] * up[np.newaxis, :]
    )

    return points_3d


# ─── High-Level Deterministic Unprojection ─────────────────────────────────────


def deterministic_unproject(
    canon: SceneCanon,
    camera: CameraContract,
    pixel_mask: np.ndarray,
) -> UnprojectionResult:
    """High-level deterministic unprojection from direct aux-channel reads.

    Reads the aux container from canon.aux_channel_path, extracts the depth
    channel (named canon.depth_channel, default "Z"), and for each pixel where
    pixel_mask > 0, reads depth and unprojects to 3D world coordinates.

    This is the deterministic direct-read unprojection path that satisfies
    Requirement 2.4. It does NOT use monocular estimation or visible-pixel
    data. It does NOT modify mesh_generators or object_isolator behavior.

    Args:
        canon: SceneCanon with aux_channel_path, depth_channel, instance_id_channel
            fields populated by the emission step.
        camera: CameraContract defining the controlled-camera projection.
        pixel_mask: (height, width) ndarray where nonzero pixels are unprojected.
            Typically an instance mask or object mask from the RGBA alpha.

    Returns:
        UnprojectionResult with points_3d, instance_ids, pixel_coords,
        camera_hash, plan_revision, and deterministic=True.

    Raises:
        FileNotFoundError: If the aux container does not exist.
        ValueError: If required channels are missing from the container.
        ValueError: If canon.aux_channel_path is empty (no aux emission occurred).
    """
    if not canon.aux_channel_path:
        raise ValueError(
            "canon.aux_channel_path is empty — no auxiliary channel emission "
            "occurred for this Canon. Deterministic unprojection requires "
            "controlled-camera aux channels emitted at generation time."
        )

    aux_path = Path(canon.aux_channel_path)

    # Load all channels from the lossless container
    channels = load_aux_channels(aux_path)

    # Resolve channel names with defaults
    depth_name = canon.depth_channel or "Z"
    instance_name = canon.instance_id_channel or "instance_id"

    if depth_name not in channels:
        raise ValueError(
            f"Depth channel '{depth_name}' not found in aux container {aux_path}. "
            f"Available channels: {list(channels.keys())}"
        )

    depth_channel = channels[depth_name]

    # Instance-ID channel (optional — may not be present if only depth was emitted)
    instance_channel = channels.get(instance_name)

    # Find all pixels where mask > 0
    mask_ys, mask_xs = np.where(pixel_mask > 0)

    if mask_ys.size == 0:
        # No masked pixels — return empty result
        return UnprojectionResult(
            points_3d=np.empty((0, 3), dtype=np.float64),
            instance_ids=np.empty((0,), dtype=np.int32),
            pixel_coords=np.empty((0, 2), dtype=np.int32),
            camera_hash=canon.camera_hash,
            plan_revision=canon.plan_revision,
            deterministic=True,
        )

    # Stack as (N, 2) pixel coordinates: column 0 = x, column 1 = y
    pixel_coords = np.stack([mask_xs, mask_ys], axis=1).astype(np.int32)

    # Extract depth values at mask pixels
    depths = depth_channel[mask_ys, mask_xs].astype(np.float64)

    # Filter: exclude np.inf (no geometry) and values at/below near plane
    cam_pos, forward, right, up, focal, width, height, near = _build_camera_basis(camera)
    valid_mask = np.isfinite(depths) & (depths > near)

    if not np.any(valid_mask):
        return UnprojectionResult(
            points_3d=np.empty((0, 3), dtype=np.float64),
            instance_ids=np.empty((0,), dtype=np.int32),
            pixel_coords=np.empty((0, 2), dtype=np.int32),
            camera_hash=canon.camera_hash,
            plan_revision=canon.plan_revision,
            deterministic=True,
        )

    # Apply filter
    valid_pixel_coords = pixel_coords[valid_mask]
    valid_depths = depths[valid_mask]
    valid_xs = valid_pixel_coords[:, 0].astype(np.float64)
    valid_ys = valid_pixel_coords[:, 1].astype(np.float64)

    # Inverse projection (vectorized)
    relative_right = (valid_xs - width / 2.0) * valid_depths / focal
    relative_up = (height / 2.0 - valid_ys) * valid_depths / focal

    points_3d = (
        cam_pos[np.newaxis, :]
        + valid_depths[:, np.newaxis] * forward[np.newaxis, :]
        + relative_right[:, np.newaxis] * right[np.newaxis, :]
        + relative_up[:, np.newaxis] * up[np.newaxis, :]
    )

    # Extract instance IDs at valid pixels
    if instance_channel is not None:
        instance_ids = instance_channel[
            valid_pixel_coords[:, 1], valid_pixel_coords[:, 0]
        ].astype(np.int32)
    else:
        # No instance-ID channel — fill with zeros
        instance_ids = np.zeros(valid_pixel_coords.shape[0], dtype=np.int32)

    logger.info(
        "Deterministic unprojection: %d valid points from %d masked pixels "
        "(aux=%s, depth=%s, camera_hash=%s, plan_rev=%d)",
        points_3d.shape[0],
        pixel_coords.shape[0],
        aux_path.name,
        depth_name,
        canon.camera_hash,
        canon.plan_revision,
    )

    return UnprojectionResult(
        points_3d=points_3d,
        instance_ids=instance_ids,
        pixel_coords=valid_pixel_coords,
        camera_hash=canon.camera_hash,
        plan_revision=canon.plan_revision,
        deterministic=True,
    )
